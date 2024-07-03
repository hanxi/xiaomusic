#!/usr/bin/env python3
import asyncio
import copy
import json
import logging
import os
import queue
import random
import re
import time
import traceback
import urllib.parse
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout
from miservice import MiAccount, MiIOService, MiNAService

from xiaomusic import (
    __version__,
)
from xiaomusic.config import (
    KEY_WORD_ARG_BEFORE_DICT,
    Config,
)
from xiaomusic.const import (
    COOKIE_TEMPLATE,
    LATEST_ASK_API,
    SUPPORT_MUSIC_TYPE,
)
from xiaomusic.httpserver import StartHTTPServer
from xiaomusic.utils import (
    custom_sort_key,
    find_best_match,
    fuzzyfinder,
    get_local_music_duration,
    get_web_music_duration,
    parse_cookie_string,
    walk_to_depth,
)

EOF = object()

PLAY_TYPE_ONE = 0  # 单曲循环
PLAY_TYPE_ALL = 1  # 全部循环
PLAY_TYPE_RND = 2  # 随机播放


class XiaoMusic:
    def __init__(self, config: Config):
        self.config = config

        self.mi_token_home = Path.home() / ".mi.token"
        self.last_timestamp = int(time.time() * 1000)  # timestamp last call mi speaker
        self.last_record = None
        self.cookie_jar = None
        self.device_id = ""
        self.mina_service = None
        self.miio_service = None
        self.polling_event = asyncio.Event()
        self.new_record_event = asyncio.Event()
        self.queue = queue.Queue()

        self.music_path = config.music_path
        self.conf_path = config.conf_path
        if not self.conf_path:
            self.conf_path = config.music_path

        self.hostname = config.hostname
        self.port = config.port
        self.proxy = config.proxy
        self.search_prefix = config.search_prefix
        self.ffmpeg_location = config.ffmpeg_location
        self.active_cmd = config.active_cmd.split(",")
        self.exclude_dirs = set(config.exclude_dirs.split(","))
        self.music_path_depth = config.music_path_depth

        # 下载对象
        self.download_proc = None
        # 单曲循环，全部循环
        self.play_type = PLAY_TYPE_RND
        self.cur_music = ""
        self._next_timer = None
        self._timeout = 0
        self._volume = 0
        self._all_music = {}
        self._all_radio = {}  # 电台列表
        self._play_list = []
        self._cur_play_list = ""
        self._music_list = {}  # 播放列表 key 为目录名, value 为 play_list
        self._playing = False

        # 关机定时器
        self._stop_timer = None

        # 初始化日志
        self.setup_logger()

        # 尝试从设置里加载配置
        self.try_init_setting()

        # 启动时重新生成一次播放列表
        self._gen_all_music_list()

        # 启动时初始化获取声音
        self.set_last_record("get_volume#")

    def setup_logger(self):
        log_format = f"%(asctime)s [{__version__}] [%(levelname)s] %(message)s"
        date_format = "[%X]"
        formatter = logging.Formatter(fmt=log_format, datefmt=date_format)
        logging.basicConfig(
            format=log_format,
            datefmt=date_format,
        )

        log_file = self.config.log_file
        log_path = os.path.dirname(log_file)
        if not os.path.exists(log_path):
            os.makedirs(log_path)
        if os.path.exists(log_file):
            os.remove(log_file)
        handler = RotatingFileHandler(
            self.config.log_file, maxBytes=10 * 1024 * 1024, backupCount=1
        )
        handler.setFormatter(formatter)
        self.log = logging.getLogger("xiaomusic")
        self.log.addHandler(handler)
        self.log.setLevel(logging.DEBUG if self.config.verbose else logging.INFO)
        debug_config = copy.deepcopy(self.config)
        debug_config.account = "******"
        debug_config.password = "******"
        debug_config.httpauth_username = "******"
        debug_config.httpauth_password = "******"
        self.log.info(debug_config)

    async def poll_latest_ask(self):
        async with ClientSession() as session:
            session._cookie_jar = self.cookie_jar
            while True:
                self.log.debug(
                    "Listening new message, timestamp: %s", self.last_timestamp
                )
                await self.get_latest_ask_from_xiaoai(session)
                start = time.perf_counter()
                self.log.debug("Polling_event, timestamp: %s", self.last_timestamp)
                await self.polling_event.wait()
                if (d := time.perf_counter() - start) < 1:
                    # sleep to avoid too many request
                    self.log.debug("Sleep %f, timestamp: %s", d, self.last_timestamp)
                    await asyncio.sleep(1 - d)

    async def init_all_data(self, session):
        await self.login_miboy(session)
        await self._init_data_hardware()
        cookie_jar = self.get_cookie()
        if cookie_jar:
            session.cookie_jar.update_cookies(cookie_jar)
        self.cookie_jar = session.cookie_jar

    async def login_miboy(self, session):
        account = MiAccount(
            session,
            self.config.account,
            self.config.password,
            str(self.mi_token_home),
        )
        # Forced login to refresh to refresh token
        await account.login("micoapi")
        self.mina_service = MiNAService(account)
        self.miio_service = MiIOService(account)

    async def try_update_device_id(self):
        # fix multi xiaoai problems we check did first
        # why we use this way to fix?
        # some videos and articles already in the Internet
        # we do not want to change old way, so we check if miotDID in `env` first
        # to set device id

        try:
            hardware_data = await self.mina_service.device_list()
            for h in hardware_data:
                if did := self.config.mi_did:
                    if h.get("miotDID", "") == str(did):
                        self.device_id = h.get("deviceID")
                        break
                    else:
                        continue
                if h.get("hardware", "") == self.config.hardware:
                    self.device_id = h.get("deviceID")
                    break
            else:
                self.log.error(
                    f"we have no hardware: {self.config.hardware} please use `micli mina` to check"
                )
        except Exception as e:
            self.log.error(f"Execption {e}")

    async def _init_data_hardware(self):
        if self.config.cookie:
            # if use cookie do not need init
            return
        await self.try_update_device_id()
        if not self.config.mi_did:
            devices = await self.miio_service.device_list()
            try:
                self.config.mi_did = next(
                    d["did"]
                    for d in devices
                    if d["model"].endswith(self.config.hardware.lower())
                )
            except StopIteration:
                self.log.error(
                    f"cannot find did for hardware: {self.config.hardware} "
                    "please set it via MI_DID env"
                )
            except Exception as e:
                self.log.error(f"Execption init hardware {e}")

    def get_cookie(self):
        if self.config.cookie:
            cookie_jar = parse_cookie_string(self.config.cookie)
            # set attr from cookie fix #134
            cookie_dict = cookie_jar.get_dict()
            self.device_id = cookie_dict["deviceId"]
            return cookie_jar

        if not os.path.exists(self.mi_token_home):
            self.log.error(f"{self.mi_token_home} file not exist")
            return None

        with open(self.mi_token_home) as f:
            user_data = json.loads(f.read())
        user_id = user_data.get("userId")
        service_token = user_data.get("micoapi")[1]
        cookie_string = COOKIE_TEMPLATE.format(
            device_id=self.device_id, service_token=service_token, user_id=user_id
        )
        return parse_cookie_string(cookie_string)

    async def get_latest_ask_from_xiaoai(self, session):
        retries = 3
        for i in range(retries):
            try:
                timeout = ClientTimeout(total=15)
                url = LATEST_ASK_API.format(
                    hardware=self.config.hardware,
                    timestamp=str(int(time.time() * 1000)),
                )
                self.log.debug(f"url:{url}")
                r = await session.get(url, timeout=timeout)
            except Exception as e:
                self.log.warning(
                    "Execption when get latest ask from xiaoai: %s", str(e)
                )
                continue
            try:
                data = await r.json()
            except Exception as e:
                self.log.warning(f"get latest ask from xiaoai error {e}, retry")
                if i == 2:
                    # tricky way to fix #282 #272 # if it is the third time we re init all data
                    self.log.info("Maybe outof date trying to re init it")
                    await self.init_all_data(self.session)
            else:
                return self._get_last_query(data)

    def _get_last_query(self, data):
        self.log.debug(f"_get_last_query:{data}")
        if d := data.get("data"):
            records = json.loads(d).get("records")
            if not records:
                return
            last_record = records[0]
            timestamp = last_record.get("time")
            if timestamp > self.last_timestamp:
                self.last_timestamp = timestamp
                self.last_record = last_record
                self.new_record_event.set()

    # 手动发消息
    def set_last_record(self, query):
        self.last_record = {
            "query": query,
            "ctrl_panel": True,
        }
        self.new_record_event.set()

    async def do_tts(self, value):
        self.log.info(f"try do_tts value:{value}")
        if not value:
            self.log.info("do_tts no value")
            return

        await self.force_stop_xiaoai()
        try:
            await self.mina_service.text_to_speech(self.device_id, value)
        except Exception as e:
            self.log.error(f"Execption {e}")
        # 最大等8秒
        sec = min(8, int(len(value) / 3))
        await asyncio.sleep(sec)
        self.log.info(f"do_tts ok. cur_music:{self.cur_music}")
        await self.check_replay()

    # 继续播放被打断的歌曲
    async def check_replay(self):
        if self.isplaying() and not self.isdownloading():
            # 继续播放歌曲
            self.log.info("现在继续播放歌曲")
            await self.play()
        else:
            self.log.info(
                f"不会继续播放歌曲. isplaying:{self.isplaying()} isdownloading:{self.isdownloading()}"
            )

    async def do_set_volume(self, value):
        value = int(value)
        self._volume = value
        self.log.info(f"声音设置为{value}")
        try:
            await self.mina_service.player_set_volume(self.device_id, value)
        except Exception as e:
            self.log.error(f"Execption {e}")

    async def get_if_xiaoai_is_playing(self):
        playing_info = await self.mina_service.player_get_status(self.device_id)
        self.log.info(playing_info)
        # WTF xiaomi api
        is_playing = (
            json.loads(playing_info.get("data", {}).get("info", "{}")).get("status", -1)
            == 1
        )
        return is_playing

    async def stop_if_xiaoai_is_playing(self):
        is_playing = await self.get_if_xiaoai_is_playing()
        if is_playing:
            # stop it
            ret = await self.mina_service.player_stop(self.device_id)
            self.log.info(f"force_stop_xiaoai player_stop ret:{ret}")

    async def force_stop_xiaoai(self):
        ret = await self.mina_service.player_pause(self.device_id)
        self.log.info(f"force_stop_xiaoai player_pause ret:{ret}")
        await self.stop_if_xiaoai_is_playing()

    # 是否在下载中
    def isdownloading(self):
        if not self.download_proc:
            return False

        if self.download_proc.returncode is not None:
            self.log.info(
                f"Process exited with returncode:{self.download_proc.returncode}"
            )
            return False

        self.log.info("Download Process is still running.")
        return True

    # 下载歌曲
    async def download(self, search_key, name):
        if self.download_proc:
            try:
                self.download_proc.kill()
            except ProcessLookupError:
                pass

        sbp_args = (
            "yt-dlp",
            f"{self.search_prefix}{search_key}",
            "-x",
            "--audio-format",
            "mp3",
            "--paths",
            self.music_path,
            "-o",
            f"{name}.mp3",
            "--ffmpeg-location",
            f"{self.ffmpeg_location}",
            "--no-playlist",
        )

        if self.proxy:
            sbp_args += ("--proxy", f"{self.proxy}")

        cmd = " ".join(sbp_args)
        self.log.info(f"download cmd: {cmd}")
        self.download_proc = await asyncio.create_subprocess_exec(*sbp_args)
        await self.do_tts(f"正在下载歌曲{search_key}")

    def get_filename(self, name):
        if name not in self._all_music:
            self.log.debug("get_filename not in. name:%s", name)
            return ""
        filename = self._all_music[name]
        self.log.debug("try get_filename. filename:%s", filename)
        if os.path.exists(filename):
            return filename
        return ""

    # 判断本地音乐是否存在，网络歌曲不判断
    def is_music_exist(self, name):
        if name not in self._all_music:
            return False
        if self.is_web_music(name):
            return True
        filename = self.get_filename(name)
        if filename:
            return True
        return False

    # 是否是网络电台
    def is_web_radio_music(self, name):
        return name in self._all_radio

    # 是否是网络歌曲
    def is_web_music(self, name):
        if name not in self._all_music:
            return False
        url = self._all_music[name]
        return url.startswith(("http://", "https://"))

    # 获取歌曲播放时长，播放地址
    async def get_music_sec_url(self, name):
        sec = 0
        url = self.get_music_url(name)
        if self.is_web_radio_music(name):
            self.log.info("电台不会有播放时长")
            return 0, url

        if self.is_web_music(name):
            origin_url = url
            duration, url = await get_web_music_duration(url)
            sec = int(duration)
            self.log.info(f"网络歌曲 {name} : {origin_url} {url} 的时长 {sec} 秒")
        else:
            filename = self.get_filename(name)
            sec = int(get_local_music_duration(filename))
            self.log.info(f"本地歌曲 {name} : {filename} {url} 的时长 {sec} 秒")

        if sec <= 0:
            self.log.warning(f"获取歌曲时长失败 {name} {url}")
        return sec, url

    def get_music_url(self, name):
        if self.is_web_music(name):
            url = self._all_music[name]
            self.log.debug("get_music_url web music. name:%s, url:%s", name, url)
            return url

        filename = self.get_filename(name)
        self.log.debug(
            "get_music_url local music. name:%s, filename:%s", name, filename
        )
        encoded_name = urllib.parse.quote(filename)
        return f"http://{self.hostname}:{self.port}/{encoded_name}"

    # 递归获取目录下所有歌曲,生成随机播放列表
    def _gen_all_music_list(self):
        self._all_music = {}
        all_music_by_dir = {}
        for root, dirs, filenames in walk_to_depth(
            self.music_path, depth=self.music_path_depth
        ):
            dirs[:] = [d for d in dirs if d not in self.exclude_dirs]
            self.log.debug("root:%s dirs:%s music_path:%s", root, dirs, self.music_path)
            dir_name = os.path.basename(root)
            if self.music_path == root:
                dir_name = "其他"
            if dir_name not in all_music_by_dir:
                all_music_by_dir[dir_name] = {}
            for filename in filenames:
                self.log.debug("gen_all_music_list. filename:%s", filename)
                # 过滤隐藏文件
                if filename.startswith("."):
                    continue
                # 过滤非音乐文件
                (name, extension) = os.path.splitext(filename)
                self.log.debug(
                    "gen_all_music_list. filename:%s, name:%s, extension:%s",
                    filename,
                    name,
                    extension,
                )
                if extension.lower() not in SUPPORT_MUSIC_TYPE:
                    continue

                # 歌曲名字相同会覆盖
                self._all_music[name] = os.path.join(root, filename)
                all_music_by_dir[dir_name][name] = True
        self._play_list = list(self._all_music.keys())
        self._cur_play_list = "全部"
        self._gen_play_list()
        self.log.debug(self._all_music)

        self._music_list = {}
        self._music_list["全部"] = self._play_list
        for dir_name, musics in all_music_by_dir.items():
            self._music_list[dir_name] = list(musics.keys())
            self.log.debug("dir_name:%s, list:%s", dir_name, self._music_list[dir_name])

        try:
            self._append_music_list()
        except Exception as e:
            self.log.error(f"Execption _append_music_list {e}")

    # 给歌单里补充网络歌单
    def _append_music_list(self):
        if not self.config.music_list_json:
            return

        self._all_radio = {}
        music_list = json.loads(self.config.music_list_json)
        try:
            for item in music_list:
                list_name = item.get("name")
                musics = item.get("musics")
                if (not list_name) or (not musics):
                    continue
                one_music_list = []
                for music in musics:
                    name = music.get("name")
                    url = music.get("url")
                    music_type = music.get("type")
                    if (not name) or (not url):
                        continue
                    self._all_music[name] = url
                    one_music_list.append(name)

                    # 处理电台列表
                    if music_type == "radio":
                        self._all_radio[name] = url
                self.log.debug(one_music_list)
                # 歌曲名字相同会覆盖
                self._music_list[list_name] = one_music_list
            if self._all_radio:
                self._music_list["所有电台"] = list(self._all_radio.keys())
            self.log.debug(self._all_music)
            self.log.debug(self._music_list)
        except Exception as e:
            self.log.error(f"Execption music_list:{music_list} {e}")

    # 歌曲排序或者打乱顺序
    def _gen_play_list(self):
        if self.play_type == PLAY_TYPE_RND:
            random.shuffle(self._play_list)
        else:
            self._play_list.sort(key=custom_sort_key)
            self.log.debug("play_list:%s", self._play_list)

    # 把下载的音乐加入播放列表
    def add_download_music(self, name):
        self._all_music[name] = os.path.join(self.music_path, f"{name}.mp3")
        if name not in self._play_list:
            self._play_list.append(name)
            self.log.debug("add_music %s", name)
            self.log.debug(self._play_list)

    # 获取下一首
    def get_next_music(self):
        play_list_len = len(self._play_list)
        if play_list_len == 0:
            self.log.warning("没有随机到歌曲")
            return ""
        # 随机选择一个文件
        index = 0
        try:
            index = self._play_list.index(self.cur_music)
        except ValueError:
            pass
        next_index = index + 1
        if next_index >= play_list_len:
            next_index = 0
        name = self._play_list[next_index]
        if not self.is_music_exist(name):
            self._play_list.pop(next_index)
            self.log.info(f"pop not exist music:{name}")
            return self.get_next_music()
        return name

    # 设置下一首歌曲的播放定时器
    async def set_next_music_timeout(self, sec):
        if sec <= 0:
            return

        if self._next_timer:
            self._next_timer.cancel()
            self.log.info("旧定时器已取消")

        self._timeout = sec

        async def _do_next():
            await asyncio.sleep(self._timeout)
            try:
                await self.play_next()
            except Exception as e:
                self.log.warning(f"执行出错 {str(e)}\n{traceback.format_exc()}")

        self._next_timer = asyncio.ensure_future(_do_next())
        self.log.info(f"{sec}秒后将会播放下一首歌曲")

    async def run_forever(self):
        StartHTTPServer(self.port, self.music_path, self)
        async with ClientSession() as session:
            self.session = session
            await self.init_all_data(session)
            task = asyncio.create_task(self.poll_latest_ask())
            assert task is not None  # to keep the reference to task, do not remove this
            filtered_keywords = [
                keyword for keyword in self.config.key_match_order if "#" not in keyword
            ]
            joined_keywords = "/".join(filtered_keywords)
            self.log.info(f"Running xiaomusic now, 用`{joined_keywords}`开头来控制")
            self.log.info(self.config.key_word_dict)

            while True:
                self.polling_event.set()
                await self.new_record_event.wait()
                self.new_record_event.clear()
                new_record = self.last_record
                if new_record is None:
                    # 其他线程的函数调用
                    try:
                        func, callback, arg1 = self.queue.get(False)
                        ret = await func(arg1=arg1)
                        callback(ret)
                    except queue.Empty:
                        pass
                    continue
                self.polling_event.clear()  # stop polling when processing the question
                query = new_record.get("query", "").strip()
                ctrl_panel = new_record.get("ctrl_panel", False)
                self.log.info("收到消息:%s 控制面板:%s", query, ctrl_panel)

                # 匹配命令
                opvalue, oparg = self.match_cmd(query, ctrl_panel)
                if not opvalue:
                    await asyncio.sleep(1)
                    await self.check_replay()
                    continue

                try:
                    func = getattr(self, opvalue)
                    await func(arg1=oparg)
                except Exception as e:
                    self.log.warning(f"执行出错 {str(e)}\n{traceback.format_exc()}")

    # 检查是否匹配到完全一样的指令
    def check_full_match_cmd(self, query, ctrl_panel):
        if query in self.config.key_match_order:
            opkey = query
            opvalue = self.config.key_word_dict.get(opkey)
            if ctrl_panel or self.isplaying():
                return opvalue
            else:
                if not self.active_cmd or opvalue in self.active_cmd:
                    return opvalue
        return None

    # 匹配命令
    def match_cmd(self, query, ctrl_panel):
        # 优先处理完全匹配
        opvalue = self.check_full_match_cmd(query, ctrl_panel)
        if opvalue:
            self.log.info(f"完全匹配指令. query:{query} opvalue:{opvalue}")
            return (opvalue, "")

        for opkey in self.config.key_match_order:
            patternarg = rf"(.*){opkey}(.*)"
            # 匹配参数
            matcharg = re.match(patternarg, query)
            if not matcharg:
                # self.log.debug(patternarg)
                continue

            argpre = matcharg.groups()[0]
            argafter = matcharg.groups()[1]
            self.log.debug(
                "matcharg. opkey:%s, argpre:%s, argafter:%s",
                opkey,
                argpre,
                argafter,
            )
            oparg = argafter
            if opkey in KEY_WORD_ARG_BEFORE_DICT:
                oparg = argpre
            opvalue = self.config.key_word_dict.get(opkey)
            if not ctrl_panel and not self.isplaying():
                if self.active_cmd and opvalue not in self.active_cmd:
                    self.log.ifno(f"不在激活命令中 {opvalue}")
                    continue
            self.log.info(f"匹配到指令. opkey:{opkey} opvalue:{opvalue} oparg:{oparg}")
            return (opvalue, oparg)
        self.log.info(f"未匹配到指令 {query} {ctrl_panel}")
        return (None, None)

    # 判断是否播放下一首歌曲
    def check_play_next(self):
        # 当前没我在播放的歌曲
        if self.cur_music == "":
            return True
        else:
            # 当前播放的歌曲不存在了
            if not self.is_music_exist(self.cur_music):
                return True
        return False

    async def play_url(self, **kwargs):
        url = kwargs.get("arg1", "")
        if self.config.use_music_api:
            ret = await self.play_by_music_url(self.device_id, url)
            self.log.info(
                f"play_url play_by_music_url {self.config.hardware}. ret:{ret} url:{url}"
            )
        else:
            ret = await self.mina_service.play_by_url(self.device_id, url)
            self.log.info(
                f"play_url play_by_url {self.config.hardware}. ret:{ret} url:{url}"
            )
        return ret

    def find_real_music_name(self, name):
        if not self.config.enable_fuzzy_match:
            self.log.debug("没开启模糊匹配")
            return name

        all_music_list = list(self._all_music.keys())
        real_name = find_best_match(
            name, all_music_list, cutoff=self.config.fuzzy_match_cutoff
        )
        if real_name:
            self.log.info(f"根据【{name}】找到歌曲【{real_name}】")
            return real_name
        self.log.info(f"没找到歌曲【{name}】")
        return name

    # 播放本地歌曲
    async def playlocal(self, **kwargs):
        name = kwargs.get("arg1", "")
        if name == "":
            if self.check_play_next():
                await self.play_next()
                return
            else:
                name = self.cur_music

        self.log.info(f"playlocal. name:{name}")

        # 本地歌曲不存在时下载
        name = self.find_real_music_name(name)
        if not self.is_music_exist(name):
            await self.do_tts(f"本地不存在歌曲{name}")
            return
        await self._playmusic(name)

    async def _playmusic(self, name):
        self._playing = True
        self.cur_music = name
        self.log.info(f"cur_music {self.cur_music}")
        sec, url = await self.get_music_sec_url(name)
        await self.force_stop_xiaoai()
        self.log.info(f"播放 {url}")
        await self.play_url(arg1=url)
        self.log.info("已经开始播放了")
        # 设置下一首歌曲的播放定时器
        await self.set_next_music_timeout(sec)

    # 播放歌曲
    async def play(self, **kwargs):
        parts = kwargs.get("arg1", "").split("|")
        search_key = parts[0]
        name = parts[1] if len(parts) > 1 else search_key
        if name == "":
            name = search_key

        if search_key == "" and name == "":
            if self.check_play_next():
                await self.play_next()
                return
            else:
                name = self.cur_music

        self.log.info("play. search_key:%s name:%s", search_key, name)

        # 本地歌曲不存在时下载
        name = self.find_real_music_name(name)
        if not self.is_music_exist(name):
            if self.config.disable_download:
                await self.do_tts(f"本地不存在歌曲{name}")
                return
            await self.download(search_key, name)
            self.log.info(f"正在下载中 {search_key} {name}")
            await self.download_proc.wait()
            # 把文件插入到播放列表里
            self.add_download_music(name)
        await self._playmusic(name)

    # 下一首
    async def play_next(self, **kwargs):
        self.log.info("下一首")
        name = self.cur_music
        self.log.debug("play_next. name:%s, cur_music:%s", name, self.cur_music)
        if (
            self.play_type == PLAY_TYPE_ALL
            or self.play_type == PLAY_TYPE_RND
            or name == ""
        ):
            name = self.get_next_music()
        if name == "":
            await self.do_tts("本地没有歌曲")
            return
        await self.play(arg1=name)

    # 单曲循环
    async def set_play_type_one(self, **kwargs):
        self.play_type = PLAY_TYPE_ONE
        await self.do_tts("已经设置为单曲循环")

    # 全部循环
    async def set_play_type_all(self, **kwargs):
        self.play_type = PLAY_TYPE_ALL
        self._gen_play_list()
        await self.do_tts("已经设置为全部循环")

    # 随机播放
    async def random_play(self, **kwargs):
        self.play_type = PLAY_TYPE_RND
        self._gen_play_list()
        await self.do_tts("已经设置为随机播放")

    # 刷新列表
    async def gen_music_list(self, **kwargs):
        self._gen_all_music_list()

    # 删除歌曲
    def del_music(self, name):
        filename = self.get_filename(name)
        if filename == "":
            self.log.info(f"${name} not exist")
            return
        try:
            os.remove(filename)
            self.log.info(f"del ${filename} success")
        except OSError:
            self.log.error(f"del ${filename} failed")
        self._gen_all_music_list()

    def find_real_music_list_name(self, list_name):
        if not self.config.enable_fuzzy_match:
            self.log.debug("没开启模糊匹配")
            return list_name

        # 模糊搜一个播放列表
        real_name = find_best_match(
            list_name, self._music_list, cutoff=self.config.fuzzy_match_cutoff
        )
        if real_name:
            self.log.info(f"根据【{list_name}】找到播放列表【{real_name}】")
            list_name = real_name
        self.log.info(f"没找到播放列表【{list_name}】")
        return list_name

    # 播放一个播放列表
    async def play_music_list(self, **kwargs):
        parts = kwargs.get("arg1").split("|")
        list_name = parts[0]

        list_name = self.find_real_music_list_name(list_name)
        if list_name not in self._music_list:
            await self.do_tts(f"播放列表{list_name}不存在")
            return
        self._play_list = self._music_list[list_name]
        self._cur_play_list = list_name
        self._gen_play_list()
        self.log.info(f"开始播放列表{list_name}")

        music_name = ""
        if len(parts) > 1:
            music_name = parts[1]
        else:
            music_name = self.get_next_music()
        await self.play(arg1=music_name)

    async def stop(self, **kwargs):
        self._playing = False
        if kwargs.get("arg1", "") != "notts":
            await self.do_tts(self.config.stop_tts_msg)
        if self._next_timer:
            self._next_timer.cancel()
            self.log.info("定时器已取消")
        await self.force_stop_xiaoai()
        self.log.info("stop now")

    async def stop_after_minute(self, **kwargs):
        if self._stop_timer:
            self._stop_timer.cancel()
            self.log.info("关机定时器已取消")
        minute = int(kwargs.get("arg1", 0))

        async def _do_stop():
            await asyncio.sleep(minute * 60)
            try:
                await self.stop(arg1="notts")
            except Exception as e:
                self.log.warning(f"执行出错 {str(e)}\n{traceback.format_exc()}")

        self._stop_timer = asyncio.ensure_future(_do_stop())
        await self.do_tts(f"收到,{minute}分钟后将关机")

    async def set_volume(self, **kwargs):
        value = kwargs.get("arg1", 0)
        await self.do_set_volume(value)

    async def get_volume(self, **kwargs):
        playing_info = await self.mina_service.player_get_status(self.device_id)
        self.log.debug("get_volume. playing_info:%s", playing_info)
        self._volume = json.loads(playing_info.get("data", {}).get("info", "{}")).get(
            "volume", 0
        )
        self.log.info("get_volume. volume:%s", self._volume)

    def get_volume_ret(self):
        return self._volume

    # 搜索音乐
    def searchmusic(self, name):
        all_music_list = list(self._all_music.keys())
        search_list = fuzzyfinder(name, all_music_list)
        self.log.debug("searchmusic. name:%s search_list:%s", name, search_list)
        return search_list

    # 获取播放列表
    def get_music_list(self):
        return self._music_list

    # 获取当前的播放列表
    def get_cur_play_list(self):
        return self._cur_play_list

    # 正在播放中的音乐
    def playingmusic(self):
        self.log.debug("playingmusic. cur_music:%s", self.cur_music)
        return self.cur_music

    # 当前是否正在播放歌曲
    def isplaying(self):
        return self._playing

    # 获取当前配置
    def getconfig(self):
        return self.config

    # 获取设置文件
    def getsettingfile(self):
        if not os.path.exists(self.conf_path):
            os.makedirs(self.conf_path)
        filename = os.path.join(self.conf_path, "setting.json")
        return filename

    def try_init_setting(self):
        try:
            filename = self.getsettingfile()
            with open(filename) as f:
                data = json.loads(f.read())
                self.update_config_from_setting(data)
        except FileNotFoundError:
            self.log.info(f"The file {filename} does not exist.")
        except json.JSONDecodeError:
            self.log.warning(f"The file {filename} contains invalid JSON.")
        except Exception as e:
            self.log.error(f"Execption init setting {e}")

    # 保存配置并重新启动
    async def saveconfig(self, data):
        # 默认暂时配置保存到 music 目录下
        filename = self.getsettingfile()
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        self.update_config_from_setting(data)
        await self.call_main_thread_function(self.reinit)

    def update_config_from_setting(self, data):
        self.config.mi_did = data.get("mi_did")
        self.config.hardware = data.get("mi_hardware")
        self.config.search_prefix = data.get("xiaomusic_search")
        self.config.proxy = data.get("xiaomusic_proxy")
        self.config.music_list_url = data.get("xiaomusic_music_list_url")
        self.config.music_list_json = data.get("xiaomusic_music_list_json")

        self.search_prefix = self.config.search_prefix
        self.proxy = self.config.proxy
        self.log.debug("update_config_from_setting ok. data:%s", data)

    # 重新初始化
    async def reinit(self, **kwargs):
        await self.try_update_device_id()
        self._gen_all_music_list()
        self.log.info("reinit success")

    # 获取所有设备
    async def getalldevices(self, **kwargs):
        did_list = []
        hardware_list = []
        hardware_data = await self.mina_service.device_list()
        for h in hardware_data:
            did = h.get("miotDID", "")
            if did != "":
                did_list.append(did)
            hardware = h.get("hardware", "")
            if h.get("hardware", "") != "":
                hardware_list.append(hardware)
        alldevices = {
            "did_list": did_list,
            "hardware_list": hardware_list,
        }
        return alldevices

    # 用于在web线程里调用
    # 获取所有设备
    async def call_main_thread_function(self, func, arg1=None):
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        def callback(ret):
            nonlocal future
            loop.call_soon_threadsafe(future.set_result, ret)

        self.queue.put((func, callback, arg1))
        self.last_record = None
        self.new_record_event.set()
        result = await future
        return result

    async def play_by_music_url(self, deviceId, url, _type=2):
        self.log.info(f"play_by_music_url url:{url}, type:{_type}")
        audio_type = ""
        if _type == 1:
            # If set to MUSIC, the light will be on
            audio_type = "MUSIC"
        audio_id = self.config.use_music_audio_id
        id = self.config.use_music_id
        music = {
            "payload": {
                "audio_type": audio_type,
                "audio_items": [
                    {
                        "item_id": {
                            "audio_id": audio_id,
                            "cp": {
                                "album_id": "-1",
                                "episode_index": 0,
                                "id": id,
                                "name": "xiaowei",
                            },
                        },
                        "stream": {"url": url},
                    }
                ],
                "list_params": {
                    "listId": "-1",
                    "loadmore_offset": 0,
                    "origin": "xiaowei",
                    "type": "MUSIC",
                },
            },
            "play_behavior": "REPLACE_ALL",
        }
        data = {"startaudioid": audio_id, "music": json.dumps(music)}
        self.log.info(json.dumps(data))
        return await self.mina_service.ubus_request(
            deviceId,
            "player_play_music",
            "mediaplayer",
            data,
        )

    async def debug_play_by_music_url(self, arg1=None):
        if arg1 is None:
            arg1 = {}
        data = arg1
        self.log.info(f"debug_play_by_music_url: {data}")
        return await self.mina_service.ubus_request(
            self.device_id,
            "player_play_music",
            "mediaplayer",
            data,
        )
