#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import random
import re
import time
import urllib.parse
import traceback
import mutagen
import queue
from xiaomusic.httpserver import StartHTTPServer

from pathlib import Path

from aiohttp import ClientSession, ClientTimeout
from miservice import MiAccount, MiIOService, MiNAService, miio_command
from rich import print
from rich.logging import RichHandler

from xiaomusic.config import (
    COOKIE_TEMPLATE,
    LATEST_ASK_API,
    KEY_WORD_DICT,
    KEY_WORD_ARG_BEFORE_DICT,
    KEY_MATCH_ORDER,
    SUPPORT_MUSIC_TYPE,
    Config,
)
from xiaomusic.utils import (
    parse_cookie_string,
    fuzzyfinder,
)

from xiaomusic import (
    __version__,
)

EOF = object()

PLAY_TYPE_ONE = 0  # 单曲循环
PLAY_TYPE_ALL = 1  # 全部循环

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
        self.hostname = config.hostname
        self.port = config.port
        self.proxy = config.proxy
        self.search_prefix = config.search_prefix
        self.ffmpeg_location = config.ffmpeg_location
        self.active_cmd = config.active_cmd.split(",")

        # 下载对象
        self.download_proc = None
        # 单曲循环，全部循环
        self.play_type = PLAY_TYPE_ALL
        self.cur_music = ""
        self._next_timer = None
        self._timeout = 0
        self._volume = 0
        self._all_music = {}
        self._play_list = []
        self._playing = False

        # 关机定时器
        self._stop_timer = None

        # setup logger
        logging.basicConfig(
            format=f"[{__version__}]\t%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(rich_tracebacks=True)]
        )
        self.log = logging.getLogger("xiaomusic")
        self.log.setLevel(logging.DEBUG if config.verbose else logging.INFO)
        self.log.debug(config)

        # 尝试从设置里加载配置
        self.try_init_setting()

        # 启动时重新生成一次播放列表
        self.gen_all_music_list()

        # 启动时初始化获取声音
        self.set_last_record("get_volume#")

        self.log.debug("ffmpeg_location: %s", self.ffmpeg_location)

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
        session.cookie_jar.update_cookies(self.get_cookie())
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
        hardware_data = await self.mina_service.device_list()
        # fix multi xiaoai problems we check did first
        # why we use this way to fix?
        # some videos and articles already in the Internet
        # we do not want to change old way, so we check if miotDID in `env` first
        # to set device id

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
            raise Exception(
                f"we have no hardware: {self.config.hardware} please use `micli mina` to check"
            )

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
                raise Exception(
                    f"cannot find did for hardware: {self.config.hardware} "
                    "please set it via MI_DID env"
                )

    def get_cookie(self):
        if self.config.cookie:
            cookie_jar = parse_cookie_string(self.config.cookie)
            # set attr from cookie fix #134
            cookie_dict = cookie_jar.get_dict()
            self.device_id = cookie_dict["deviceId"]
            return cookie_jar
        else:
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
                r = await session.get(
                    LATEST_ASK_API.format(
                        hardware=self.config.hardware,
                        timestamp=str(int(time.time() * 1000)),
                    ),
                    timeout=timeout,
                )
            except Exception as e:
                self.log.warning(
                    "Execption when get latest ask from xiaoai: %s", str(e)
                )
                continue
            try:
                data = await r.json()
            except Exception:
                self.log.warning("get latest ask from xiaoai error, retry")
                if i == 2:
                    # tricky way to fix #282 #272 # if it is the third time we re init all data
                    self.log.info("Maybe outof date trying to re init it")
                    await self.init_all_data(self.session)
            else:
                return self._get_last_query(data)

    def _get_last_query(self, data):
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
        self.log.info("do_tts: %s", value)

        if self.config.mute_xiaoai:
            await self.force_stop_xiaoai()
        else:
            # waiting for xiaoai speaker done
            await asyncio.sleep(8)

        if not self.config.use_command:
            try:
                await self.mina_service.text_to_speech(self.device_id, value)
            except Exception:
                pass
        else:
            await miio_command(
                self.miio_service,
                self.config.mi_did,
                f"{self.config.tts_command} {value}",
            )

    async def do_set_volume(self, value):
        value = int(value)
        self._volume = value
        self.log.info(f"声音设置为{value}")
        if not self.config.use_command:
            try:
                self.log.debug("do_set_volume not use_command value:%d", value)
                await self.mina_service.player_set_volume(self.device_id, value)
            except Exception:
                pass
        else:
            self.log.debug("do_set_volume use_command value:%d", value)
            await miio_command(
                self.miio_service,
                self.config.mi_did,
                f"{self.config.volume_command}=#{value}",
            )

    async def force_stop_xiaoai(self):
        await self.mina_service.player_stop(self.device_id)

    # 是否在下载中
    def is_downloading(self):
        if not self.download_proc:
            return False
        if self.download_proc.returncode != None and self.download_proc.returncode < 0:
            return False
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

        self.download_proc = await asyncio.create_subprocess_exec(*sbp_args)
        await self.do_tts(f"正在下载歌曲{search_key}")

    # 本地是否存在歌曲
    def get_filename(self, name):
        if name not in self._all_music:
            self.log.debug("get_filename not in. name:%s", name)
            return ""
        filename = self._all_music[name]
        self.log.debug("try get_filename. filename:%s", filename)
        if os.path.exists(filename):
            return filename
        return ""

    # 获取歌曲播放地址
    def get_file_url(self, name):
        filename = self.get_filename(name)
        self.log.debug("get_file_url. name:%s, filename:%s", name, filename)
        encoded_name = urllib.parse.quote(filename)
        return f"http://{self.hostname}:{self.port}/{encoded_name}"

    # 递归获取目录下所有歌曲,生成随机播放列表
    def gen_all_music_list(self):
        self._all_music = {}
        for root, dirs, filenames in os.walk(self.music_path):
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
                if extension not in SUPPORT_MUSIC_TYPE:
                    continue

                # 歌曲名字相同会覆盖
                self._all_music[name] = os.path.join(root, filename)
        self._play_list = list(self._all_music.keys())
        random.shuffle(self._play_list)
        self.log.debug(self._all_music)

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
            self.log.warning(f"没有随机到歌曲")
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
        filename = self._play_list[next_index]
        return filename

    # 获取文件播放时长
    def get_file_duration(self, filename):
        # 获取音频文件对象
        audio = mutagen.File(filename)
        # 获取播放时长
        duration = audio.info.length
        return duration

    # 设置下一首歌曲的播放定时器
    def set_next_music_timeout(self):
        filename = self.get_filename(self.cur_music)
        sec = int(self.get_file_duration(filename))
        self.log.info(f"歌曲 {self.cur_music} : {filename} 的时长 {sec} 秒")
        if self._next_timer:
            self._next_timer.cancel()
            self.log.info(f"定时器已取消")
        self._timeout = sec

        async def _do_next():
            await asyncio.sleep(self._timeout)
            try:
                await self.play_next()
            except Exception as e:
                self.log.warning(f"执行出错 {str(e)}\n{traceback.format_exc()}")

        self._next_timer = asyncio.ensure_future(_do_next())
        self.log.info(f"{sec}秒后将会播放下一首")

    async def run_forever(self):
        StartHTTPServer(self.port, self.music_path, self)
        async with ClientSession() as session:
            self.session = session
            await self.init_all_data(session)
            task = asyncio.create_task(self.poll_latest_ask())
            assert task is not None  # to keep the reference to task, do not remove this
            filtered_keywords = [keyword for keyword in KEY_MATCH_ORDER if "#" not in keyword]
            joined_keywords = "/".join(filtered_keywords)
            self.log.info(
                f"Running xiaomusic now, 用`{joined_keywords}`开头来控制"
            )

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
                self.log.debug("收到消息:%s 控制面板:%s", query, ctrl_panel)

                # 匹配命令
                opvalue, oparg = self.match_cmd(query, ctrl_panel)
                if not opvalue:
                    await asyncio.sleep(1)
                    continue

                try:
                    func = getattr(self, opvalue)
                    await func(arg1=oparg)
                except Exception as e:
                    self.log.warning(f"执行出错 {str(e)}\n{traceback.format_exc()}")

    # 匹配命令
    def match_cmd(self, query, ctrl_panel):
        for opkey in KEY_MATCH_ORDER:
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
            opvalue = KEY_WORD_DICT[opkey]
            if not ctrl_panel and not self._playing:
                if self.active_cmd and opvalue not in self.active_cmd:
                    self.log.debug(f"不在激活命令中 {opvalue}")
                    continue
            if opkey in KEY_WORD_ARG_BEFORE_DICT:
                oparg = argpre
            self.log.info(
                "匹配到指令. opkey:%s opvalue:%s oparg:%s", opkey, opvalue, oparg
            )
            return (opvalue, oparg)
        if self._playing:
            self.log.info("未匹配到指令，自动停止")
            return ("stop", {})
        return (None, None)

    # 播放歌曲
    async def play(self, **kwargs):
        self._playing = True
        parts = kwargs["arg1"].split("|")
        search_key = parts[0]
        name = parts[1] if len(parts) > 1 else search_key
        if search_key == "" and name == "":
            await self.play_next()
            return
        if name == "":
            name = search_key
        self.log.debug("play. search_key:%s name:%s", search_key, name)
        filename = self.get_filename(name)

        if len(filename) <= 0:
            await self.download(search_key, name)
            self.log.info("正在下载中 %s", search_key + ":" + name)
            await self.download_proc.wait()
            # 把文件插入到播放列表里
            self.add_download_music(name)

        self.cur_music = name
        self.log.info("cur_music %s", self.cur_music)
        url = self.get_file_url(name)
        self.log.info("播放 %s", url)
        await self.force_stop_xiaoai()
        await self.mina_service.play_by_url(self.device_id, url)
        self.log.info("已经开始播放了")
        # 设置下一首歌曲的播放定时器
        self.set_next_music_timeout()

    # 下一首
    async def play_next(self, **kwargs):
        self.log.info("下一首")
        name = self.cur_music
        self.log.debug("play_next. name:%s, cur_music:%s", name, self.cur_music)
        if self.play_type == PLAY_TYPE_ALL or name == "":
            name = self.get_next_music()
        if name == "":
            await self.do_tts(f"本地没有歌曲")
            return
        await self.play(arg1=name)

    # 单曲循环
    async def set_play_type_one(self, **kwargs):
        self.play_type = PLAY_TYPE_ONE
        await self.do_tts(f"已经设置为单曲循环")

    # 全部循环
    async def set_play_type_all(self, **kwargs):
        self.play_type = PLAY_TYPE_ALL
        await self.do_tts(f"已经设置为全部循环")

    # 随机播放
    async def random_play(self, **kwargs):
        self.play_type = PLAY_TYPE_ALL
        await self.do_tts(f"已经设置为全部循环并随机播放")
        # 重新生成随机播放列表
        self.gen_all_music_list()
        await self.play_next()

    async def stop(self, **kwargs):
        self._playing = False
        if self._next_timer:
            self._next_timer.cancel()
            self.log.info(f"定时器已取消")
        await self.force_stop_xiaoai()

    async def stop_after_minute(self, **kwargs):
        if self._stop_timer:
            self._stop_timer.cancel()
            self.log.info(f"关机定时器已取消")
        minute = int(kwargs["arg1"])

        async def _do_stop():
            await asyncio.sleep(minute * 60)
            try:
                await self.stop()
            except Exception as e:
                self.log.warning(f"执行出错 {str(e)}\n{traceback.format_exc()}")

        self._stop_timer = asyncio.ensure_future(_do_stop())
        self.log.info(f"{minute}分钟后将关机")

    async def set_volume(self, **kwargs):
        value = kwargs["arg1"]
        await self.do_set_volume(value)

    async def get_volume(self, **kwargs):
        playing_info = await self.mina_service.player_get_status(self.device_id)
        self.log.debug("get_volume. playing_info:%s", playing_info)
        self._volume = json.loads(playing_info.get("data", {}).get("info", "{}")).get("volume", 5)
        self.log.info("get_volume. volume:%s", self._volume)

    def get_volume_ret(self):
        return self._volume

    # 搜索音乐
    def searchmusic(self, name):
        search_list = fuzzyfinder(name, self._play_list)
        self.log.debug("searchmusic. name:%s search_list:%s", name, search_list)
        return search_list

    # 正在播放中的音乐
    def playingmusic(self):
        self.log.debug("playingmusic. cur_music:%s", self.cur_music)
        return self.cur_music

    # 获取当前配置
    def getconfig(self):
        return self.config

    def try_init_setting(self):
        try:
            filename = os.path.join(self.music_path, "setting.json")
            with open(filename) as f:
                data = json.loads(f.read())
                self.update_config_from_setting(data)
        except FileNotFoundError:
            self.log.info(f"The file {filename} does not exist.")
        except json.JSONDecodeError:
            self.log.warning(f"The file {filename} contains invalid JSON.")

    # 保存配置并重新启动
    async def saveconfig(self, data):
        # 默认暂时配置保存到 music 目录下
        filename = os.path.join(self.music_path, "setting.json")
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        self.update_config_from_setting(data)
        await self.call_main_thread_function(self.reinit)

    def update_config_from_setting(self, data):
        self.config.mi_did = data["mi_did"]
        self.config.hardware = data["mi_hardware"]
        self.config.search_prefix = data["xiaomusic_search"]
        self.config.proxy = data["xiaomusic_proxy"]

        self.search_prefix = self.config.search_prefix
        self.proxy = self.config.proxy
        self.log.info("update_config_from_setting ok. data:%s", data)

    # 重新初始化
    async def reinit(self, **kwargs):
        await self.try_update_device_id()
        self.log.info("reinit success")

    # 获取所有设备
    async def getalldevices(self, **kwargs):
        arg1 = kwargs["arg1"]
        self.log.debug("getalldevices. arg1:%s", arg1)
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

