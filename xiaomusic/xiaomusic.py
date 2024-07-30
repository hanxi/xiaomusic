#!/usr/bin/env python3
import asyncio
import json
import logging
import math
import os
import random
import re
import time
import urllib.parse
from dataclasses import asdict
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout
from miservice import MiAccount, MiNAService

from xiaomusic import __version__
from xiaomusic.config import (
    KEY_WORD_ARG_BEFORE_DICT,
    Config,
    Device,
)
from xiaomusic.const import (
    COOKIE_TEMPLATE,
    LATEST_ASK_API,
    PLAY_TYPE_ALL,
    PLAY_TYPE_ONE,
    PLAY_TYPE_RND,
    PLAY_TYPE_TTS,
    SUPPORT_MUSIC_TYPE,
)
from xiaomusic.plugin import PluginManager
from xiaomusic.utils import (
    custom_sort_key,
    deepcopy_data_no_sensitive_info,
    find_best_match,
    fuzzyfinder,
    get_local_music_duration,
    get_web_music_duration,
    is_mp3,
    parse_cookie_string,
    parse_str_to_dict,
    remove_id3_tags,
    traverse_music_directory,
)


class XiaoMusic:
    def __init__(self, config: Config):
        self.config = config

        self.mi_token_home = Path.home() / ".mi.token"
        self.last_timestamp = {}  # key为 did. timestamp last call mi speaker
        self.last_record = None
        self.cookie_jar = None
        self.mina_service = None
        self.polling_event = asyncio.Event()
        self.new_record_event = asyncio.Event()

        self.all_music = {}
        self._all_radio = {}  # 电台列表
        self.music_list = {}  # 播放列表 key 为目录名, value 为 play_list
        self.devices = {}  # key 为 did
        self.running_task = []

        # 初始化配置
        self.init_config()

        # 初始化日志
        self.setup_logger()

        # 尝试从设置里加载配置
        self.try_init_setting()

        # 启动时重新生成一次播放列表
        self._gen_all_music_list()

        # 初始化插件
        self.plugin_manager = PluginManager(self)

        # 更新设备列表
        self.update_devices()

        debug_config = deepcopy_data_no_sensitive_info(self.config)
        self.log.info(f"Startup OK. {debug_config}")

        if self.config.conf_path == self.music_path:
            self.log.warning("配置文件目录和音乐目录建议设置为不同的目录")

    def init_config(self):
        self.music_path = self.config.music_path
        self.download_path = self.config.download_path
        if not self.download_path:
            self.download_path = self.music_path

        if not os.path.exists(self.download_path):
            os.makedirs(self.download_path)

        self.hostname = self.config.hostname
        self.port = self.config.port
        self.public_port = self.config.public_port
        if self.public_port == 0:
            self.public_port = self.port

        self.active_cmd = self.config.active_cmd.split(",")
        self.exclude_dirs = set(self.config.exclude_dirs.split(","))
        self.music_path_depth = self.config.music_path_depth
        self.remove_id3tag = self.config.remove_id3tag

    def update_devices(self):
        self.device_id_did = {}  # key 为 device_id
        self.groups = {}  # key 为 group_name, value 为 device_id_list
        XiaoMusicDevice.dict_clear(self.devices)  # 需要清理旧的定时器
        did2group = parse_str_to_dict(self.config.group_list, d1=",", d2=":")
        for did, device in self.config.devices.items():
            group_name = did2group.get(did)
            if not group_name:
                group_name = device.name
            if group_name not in self.groups:
                self.groups[group_name] = []
            self.groups[group_name].append(device.device_id)
            self.device_id_did[device.device_id] = did
            self.devices[did] = XiaoMusicDevice(self, device, group_name)

    def setup_logger(self):
        log_format = f"%(asctime)s [{__version__}] [%(levelname)s] %(filename)s:%(lineno)d: %(message)s"
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
        handler.stream.flush()
        handler.setFormatter(formatter)
        self.log = logging.getLogger("xiaomusic")
        self.log.addHandler(handler)
        self.log.setLevel(logging.DEBUG if self.config.verbose else logging.INFO)

    async def poll_latest_ask(self):
        async with ClientSession() as session:
            while True:
                # self.log.debug(
                #    f"Listening new message, timestamp: {self.last_timestamp}"
                # )
                session._cookie_jar = self.cookie_jar

                # 拉取所有音箱的对话记录
                tasks = [
                    self.get_latest_ask_from_xiaoai(session, device_id)
                    for device_id in self.device_id_did
                ]
                await asyncio.gather(*tasks)

                start = time.perf_counter()
                # self.log.debug(f"Polling_event, timestamp: {self.last_timestamp}")
                await self.polling_event.wait()
                if (d := time.perf_counter() - start) < 1:
                    # sleep to avoid too many request
                    # self.log.debug(f"Sleep {d}, timestamp: {self.last_timestamp}")
                    await asyncio.sleep(1 - d)

    async def init_all_data(self, session):
        await self.login_miboy(session)
        await self.try_update_device_id()
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

    async def try_update_device_id(self):
        try:
            mi_dids = self.config.mi_did.split(",")
            hardware_data = await self.mina_service.device_list()
            devices = {}
            for h in hardware_data:
                device_id = h.get("deviceID", "")
                hardware = h.get("hardware", "")
                did = h.get("miotDID", "")
                name = h.get("alias", "")
                if not name:
                    name = h.get("name", "未知名字")
                if device_id and hardware and did and (did in mi_dids):
                    device = self.config.devices.get(did, Device())
                    device.did = did
                    device.device_id = device_id
                    device.hardware = hardware
                    device.name = name
                    devices[did] = device
            self.config.devices = devices
            self.log.info(f"选中的设备: {devices}")
        except Exception as e:
            self.log.exception(f"Execption {e}")

    def get_cookie(self):
        if self.config.cookie:
            cookie_jar = parse_cookie_string(self.config.cookie)
            return cookie_jar

        if not os.path.exists(self.mi_token_home):
            self.log.error(f"{self.mi_token_home} file not exist")
            return None

        with open(self.mi_token_home) as f:
            user_data = json.loads(f.read())
        user_id = user_data.get("userId")
        service_token = user_data.get("micoapi")[1]
        device_id = self.get_one_device_id()
        cookie_string = COOKIE_TEMPLATE.format(
            device_id=device_id, service_token=service_token, user_id=user_id
        )
        return parse_cookie_string(cookie_string)

    def get_one_device_id(self):
        device_id = next(iter(self.device_id_did), "")
        return device_id

    def get_did(self, device_id):
        return self.device_id_did.get(device_id, "")

    def get_hardward(self, device_id):
        device = self.get_device_by_device_id(device_id)
        if not device:
            return ""
        return device.hardware

    def get_group_device_id_list(self, group_name):
        return self.groups[group_name]

    def get_group_devices(self, group_name):
        device_id_list = self.groups[group_name]
        devices = {}
        for device_id in device_id_list:
            did = self.device_id_did.get(device_id, "")
            if did:
                devices[did] = self.devices[did]
        return devices

    def get_device_by_device_id(self, device_id):
        did = self.device_id_did.get(device_id)
        if not did:
            return None
        return self.config.devices.get(did)

    async def get_latest_ask_from_xiaoai(self, session, device_id):
        cookies = {"deviceId": device_id}
        retries = 3
        for i in range(retries):
            try:
                timeout = ClientTimeout(total=15)
                hardware = self.get_hardward(device_id)
                url = LATEST_ASK_API.format(
                    hardware=hardware,
                    timestamp=str(int(time.time() * 1000)),
                )
                # self.log.debug(f"url:{url} device_id:{device_id} hardware:{hardware}")
                r = await session.get(url, timeout=timeout, cookies=cookies)
            except Exception as e:
                self.log.exception(f"Execption {e}")
                continue
            try:
                data = await r.json()
            except Exception as e:
                self.log.exception(f"Execption {e}")
                if i == 2:
                    # tricky way to fix #282 #272 # if it is the third time we re init all data
                    self.log.info("Maybe outof date trying to re init it")
                    await self.init_all_data(self.session)
            else:
                return self._get_last_query(device_id, data)

    def _get_last_query(self, device_id, data):
        did = self.get_did(device_id)
        self.log.debug(f"_get_last_query device_id:{device_id} did:{did} data:{data}")
        if d := data.get("data"):
            records = json.loads(d).get("records")
            if not records:
                return
            last_record = records[0]
            timestamp = last_record.get("time")
            # 首次用当前时间初始化
            if did not in self.last_timestamp:
                self.last_timestamp[did] = int(time.time() * 1000)
            if timestamp > self.last_timestamp[did]:
                self.last_timestamp[did] = timestamp
                last_record["did"] = did
                self.last_record = last_record
                self.new_record_event.set()

    def get_filename(self, name):
        if name not in self.all_music:
            self.log.info(f"get_filename not in. name:{name}")
            return ""
        filename = self.all_music[name]
        self.log.info(f"try get_filename. filename:{filename}")
        if os.path.exists(filename):
            return filename
        return ""

    # 判断本地音乐是否存在，网络歌曲不判断
    def is_music_exist(self, name):
        if name not in self.all_music:
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
        if name not in self.all_music:
            return False
        url = self.all_music[name]
        return url.startswith(("http://", "https://"))

    # 获取歌曲播放时长，播放地址
    async def get_music_sec_url(self, name):
        sec = 0
        url = self.get_music_url(name)
        self.log.info(f"get_music_sec_url. name:{name} url:{url}")
        if self.is_web_radio_music(name):
            self.log.info("电台不会有播放时长")
            return 0, url

        if self.is_web_music(name):
            origin_url = url
            duration, url = await get_web_music_duration(url)
            sec = math.ceil(duration)
            self.log.info(f"网络歌曲 {name} : {origin_url} {url} 的时长 {sec} 秒")
        else:
            filename = self.get_filename(name)
            self.log.info(f"get_music_sec_url. name:{name} filename:{filename}")
            duration = await get_local_music_duration(filename)
            sec = math.ceil(duration)
            self.log.info(f"本地歌曲 {name} : {filename} {url} 的时长 {sec} 秒")

        if sec <= 0:
            self.log.warning(f"获取歌曲时长失败 {name} {url}")
        return sec, url

    def get_music_url(self, name):
        if self.is_web_music(name):
            url = self.all_music[name]
            self.log.info(f"get_music_url web music. name:{name}, url:{url}")
            return url

        filename = self.get_filename(name)
        # 移除MP3 ID3 v2标签和填充，减少播放前延迟
        if self.remove_id3tag and is_mp3(filename):
            self.log.info(f"remove_id3tag:{self.remove_id3tag}, is_mp3:True ")
            change = remove_id3_tags(filename)
            if change:
                self.log.info("ID3 tag removed, orgin mp3 file saved as bak")
            else:
                self.log.info("No ID3 tag remove needed")

        filename = filename.replace("\\", "/")
        if filename.startswith(self.config.music_path):
            filename = filename[len(self.config.music_path) :]
        if filename.startswith("/"):
            filename = filename[1:]
        self.log.info(f"get_music_url local music. name:{name}, filename:{filename}")
        encoded_name = urllib.parse.quote(filename)
        return f"http://{self.hostname}:{self.public_port}/music/{encoded_name}"

    # 获取目录下所有歌曲,生成随机播放列表
    def _gen_all_music_list(self):
        self.all_music = {}
        all_music_by_dir = {}
        local_musics = traverse_music_directory(
            self.music_path,
            depth=self.music_path_depth,
            exclude_dirs=self.exclude_dirs,
            support_extension=SUPPORT_MUSIC_TYPE,
        )
        for dir_name, files in local_musics.items():
            if len(files) == 0:
                continue
            if dir_name == os.path.basename(self.music_path):
                dir_name = "其他"
            if self.music_path != self.download_path and dir_name == os.path.basename(
                self.download_path
            ):
                dir_name = "下载"
            if dir_name not in all_music_by_dir:
                all_music_by_dir[dir_name] = {}
            for file in files:
                # 歌曲名字相同会覆盖
                filename = os.path.basename(file)
                (name, _) = os.path.splitext(filename)
                self.all_music[name] = file
                all_music_by_dir[dir_name][name] = True
                self.log.debug(f"_gen_all_music_list {name}:{dir_name}:{file}")

        # self.log.debug(self.all_music)

        self.music_list = {}
        for dir_name, musics in all_music_by_dir.items():
            self.music_list[dir_name] = list(musics.keys())
            # self.log.debug("dir_name:%s, list:%s", dir_name, self.music_list[dir_name])

        try:
            self._append_music_list()
        except Exception as e:
            self.log.exception(f"Execption {e}")

        self.music_list["全部"] = list(self.all_music.keys())

        # 歌单排序
        for _, play_list in self.music_list.items():
            play_list.sort(key=custom_sort_key)

        # 更新每个设备的歌单
        for device in self.devices.values():
            device.update_playlist()

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
                    self.all_music[name] = url
                    one_music_list.append(name)

                    # 处理电台列表
                    if music_type == "radio":
                        self._all_radio[name] = url
                self.log.debug(one_music_list)
                # 歌曲名字相同会覆盖
                self.music_list[list_name] = one_music_list
            if self._all_radio:
                self.music_list["所有电台"] = list(self._all_radio.keys())
            # self.log.debug(self.all_music)
            # self.log.debug(self.music_list)
        except Exception as e:
            self.log.exception(f"Execption {e}")

    async def run_forever(self):
        async with ClientSession() as session:
            self.session = session
            await self.init_all_data(session)
            task = asyncio.create_task(self.poll_latest_ask())
            assert task is not None  # to keep the reference to task, do not remove this
            while True:
                self.polling_event.set()
                await self.new_record_event.wait()
                self.new_record_event.clear()
                new_record = self.last_record
                self.polling_event.clear()  # stop polling when processing the question
                query = new_record.get("query", "").strip()
                did = new_record.get("did", "").strip()
                await self.do_check_cmd(did, query, False)

    # 匹配命令
    async def do_check_cmd(self, did="", query="", ctrl_panel=True, **kwargs):
        self.log.info(f"收到消息:{query} 控制面板:{ctrl_panel} did:{did}")
        try:
            opvalue, oparg = self.match_cmd(did, query, ctrl_panel)
            if not opvalue:
                await asyncio.sleep(1)
                await self.check_replay(did)
                return

            func = getattr(self, opvalue)
            await func(did=did, arg1=oparg)
        except Exception as e:
            self.log.exception(f"Execption {e}")

    def append_running_task(self, task):
        self.running_task.append(task)

    async def cancel_all_tasks(self):
        if len(self.running_task) == 0:
            self.log.info("cancel_all_tasks no task")
            return
        for task in self.running_task:
            self.log.info(f"cancel_all_tasks {task}")
            task.cancel()
        await asyncio.gather(*self.running_task, return_exceptions=True)
        self.running_task = []

    async def check_replay(self, did):
        return await self.devices[did].check_replay()

    # 检查是否匹配到完全一样的指令
    def check_full_match_cmd(self, did, query, ctrl_panel):
        if query in self.config.key_match_order:
            opkey = query
            opvalue = self.config.key_word_dict.get(opkey)
            if ctrl_panel or self.isplaying(did):
                return opvalue
            else:
                if not self.active_cmd or opvalue in self.active_cmd:
                    return opvalue
        return None

    # 匹配命令
    def match_cmd(self, did, query, ctrl_panel):
        # 优先处理完全匹配
        opvalue = self.check_full_match_cmd(did, query, ctrl_panel)
        if opvalue:
            self.log.info(f"完全匹配指令. query:{query} opvalue:{opvalue}")
            # 自定义口令
            if opvalue.startswith("exec#"):
                code = opvalue.split("#", 1)[1]
                return ("exec", code)
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

            if (
                (not ctrl_panel)
                and (not self.isplaying(did))
                and self.active_cmd
                and (opvalue not in self.active_cmd)
                and (opkey not in self.active_cmd)
            ):
                self.log.info(f"不在激活命令中 {opvalue}")
                continue

            self.log.info(f"匹配到指令. opkey:{opkey} opvalue:{opvalue} oparg:{oparg}")
            return (opvalue, oparg)
        self.log.info(f"未匹配到指令 {query} {ctrl_panel}")
        return (None, None)

    def find_real_music_name(self, name):
        if not self.config.enable_fuzzy_match:
            self.log.debug("没开启模糊匹配")
            return name

        all_music_list = list(self.all_music.keys())
        real_name = find_best_match(
            name, all_music_list, cutoff=self.config.fuzzy_match_cutoff
        )
        if real_name:
            self.log.info(f"根据【{name}】找到歌曲【{real_name}】")
            return real_name
        self.log.info(f"没找到歌曲【{name}】")
        return name

    def did_exist(self, did):
        return did in self.devices

    # 播放一个 url
    async def play_url(self, did="", arg1="", **kwargs):
        url = arg1
        return await self.devices[did].group_player_play(url)

    # 设置为单曲循环
    async def set_play_type_one(self, did="", **kwargs):
        await self.devices[did].set_play_type(PLAY_TYPE_ONE)

    # 设置为全部循环
    async def set_play_type_all(self, did="", **kwargs):
        await self.devices[did].set_play_type(PLAY_TYPE_ALL)

    # 设置为随机播放
    async def set_random_play(self, did="", **kwargs):
        await self.devices[did].set_play_type(PLAY_TYPE_RND)

    # 设置为刷新列表
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
        # TODO: 这里可以优化性能
        self._gen_all_music_list()

    def _find_real_music_list_name(self, list_name):
        if not self.config.enable_fuzzy_match:
            self.log.debug("没开启模糊匹配")
            return list_name

        # 模糊搜一个播放列表
        real_name = find_best_match(
            list_name, self.music_list, cutoff=self.config.fuzzy_match_cutoff
        )
        if real_name:
            self.log.info(f"根据【{list_name}】找到播放列表【{real_name}】")
            list_name = real_name
        else:
            self.log.info(f"没找到播放列表【{list_name}】")
        return list_name

    # 播放一个播放列表
    async def play_music_list(self, did="", arg1="", **kwargs):
        parts = arg1.split("|")
        list_name = parts[0]

        list_name = self._find_real_music_list_name(list_name)
        if list_name not in self.music_list:
            await self.do_tts(did, f"播放列表{list_name}不存在")
            return

        music_name = ""
        if len(parts) > 1:
            music_name = parts[1]
        await self.devices[did].play_music_list(list_name, music_name)

    # 播放
    async def play(self, did="", arg1="", **kwargs):
        parts = arg1.split("|")
        search_key = parts[0]
        name = parts[1] if len(parts) > 1 else search_key
        if name == "":
            name = search_key

        return await self.devices[did].play(name, search_key)

    # 本地播放
    async def playlocal(self, did="", arg1="", **kwargs):
        return await self.devices[did].playlocal(arg1)

    async def play_next(self, did="", **kwargs):
        return await self.devices[did].play_next()

    # 停止
    async def stop(self, did="", arg1="", **kwargs):
        return await self.devices[did].stop(arg1=arg1)

    # 定时关机
    async def stop_after_minute(self, did="", arg1=0, **kwargs):
        minute = int(arg1)
        return await self.devices[did].stop_after_minute(minute)

    # 获取音量
    async def get_volume(self, did="", **kwargs):
        return await self.devices[did].get_volume()

    # 设置音量
    async def set_volume(self, did="", arg1=0, **kwargs):
        volume = int(arg1)
        return await self.devices[did].set_volume(volume)

    # 搜索音乐
    def searchmusic(self, name):
        all_music_list = list(self.all_music.keys())
        search_list = fuzzyfinder(name, all_music_list)
        self.log.debug(f"searchmusic. name:{name} search_list:{search_list}")
        return search_list

    # 获取播放列表
    def get_music_list(self):
        return self.music_list

    # 获取当前的播放列表
    def get_cur_play_list(self, did):
        return self.devices[did].get_cur_play_list()

    # 正在播放中的音乐
    def playingmusic(self, did):
        cur_music = self.devices[did].cur_music
        self.log.debug(f"playingmusic. cur_music:{cur_music}")
        return cur_music

    # 当前是否正在播放歌曲
    def isplaying(self, did):
        return self.devices[did].isplaying()

    # 获取当前配置
    def getconfig(self):
        return self.config

    def try_init_setting(self):
        try:
            filename = self.config.getsettingfile()
            with open(filename) as f:
                data = json.loads(f.read())
                self.update_config_from_setting(data)
        except FileNotFoundError:
            self.log.info(f"The file {filename} does not exist.")
        except json.JSONDecodeError:
            self.log.warning(f"The file {filename} contains invalid JSON.")
        except Exception as e:
            self.log.exception(f"Execption {e}")

    # 保存配置并重新启动
    async def saveconfig(self, data):
        # 更新配置
        self.update_config_from_setting(data)
        # 配置文件落地
        self.save_cur_config()
        # 重新初始化
        await self.reinit()

    # 配置文件落地
    def do_saveconfig(self, data):
        filename = self.config.getsettingfile()
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # 把当前配置落地
    def save_cur_config(self):
        data = asdict(self.config)
        self.do_saveconfig(data)
        self.log.info("save_cur_config ok")

    def update_config_from_setting(self, data):
        # 自动赋值相同字段的配置
        self.config.update_config(data)

        self.init_config()
        debug_config = deepcopy_data_no_sensitive_info(self.config)
        self.log.info(f"update_config_from_setting ok. data:{debug_config}")

        joined_keywords = "/".join(self.config.key_match_order)
        self.log.info(f"语音控制已启动, 用【{joined_keywords}】开头来控制")
        self.log.debug(f"key_word_dict: {self.config.key_word_dict}")

    # 重新初始化
    async def reinit(self, **kwargs):
        self.setup_logger()
        await self.init_all_data(self.session)
        self._gen_all_music_list()
        self.update_devices()

        debug_config = deepcopy_data_no_sensitive_info(self.config)
        self.log.info(f"reinit success. data:{debug_config}")

    # 获取所有设备
    async def getalldevices(self, **kwargs):
        device_list = []
        try:
            device_list = await self.mina_service.device_list()
        except Exception as e:
            self.log.exception(f"Execption {e}")
        return device_list

    async def debug_play_by_music_url(self, arg1=None):
        if arg1 is None:
            arg1 = {}
        data = arg1
        device_id = self.get_one_device_id()
        self.log.info(f"debug_play_by_music_url: {data} {device_id}")
        return await self.mina_service.ubus_request(
            device_id,
            "player_play_music",
            "mediaplayer",
            data,
        )

    async def exec(self, did="", arg1=None, **kwargs):
        self._cur_did = did
        code = arg1 if arg1 else 'code1("hello")'
        await self.plugin_manager.execute_plugin(code)

    # 此接口用于插件中获取当前设备
    def get_cur_did(self):
        return self._cur_did

    async def do_tts(self, did, value):
        return await self.devices[did].do_tts(value)


class XiaoMusicDevice:
    def __init__(self, xiaomusic: XiaoMusic, device: Device, group_name: str):
        self.group_name = group_name
        self.device = device
        self.config = xiaomusic.config
        self.device_id = device.device_id
        self.log = xiaomusic.log
        self.xiaomusic = xiaomusic
        self.download_path = xiaomusic.download_path
        self.ffmpeg_location = self.config.ffmpeg_location

        self._download_proc = None  # 下载对象
        self.cur_music = self.device.cur_music
        self._next_timer = None
        self._timeout = 0
        self._playing = False
        # 关机定时器
        self._stop_timer = None
        self._last_cmd = None
        self.update_playlist()

    # 初始化播放列表
    def update_playlist(self):
        self._cur_play_list = self.device.cur_playlist
        if self._cur_play_list not in self.xiaomusic.music_list:
            self._cur_play_list = "全部"
        self._play_list = self.xiaomusic.music_list.get(self._cur_play_list)

    # 播放歌曲
    async def play(self, name="", search_key=""):
        self._last_cmd = "play"
        return await self._play(name=name, search_key=search_key)

    async def _play(self, name="", search_key=""):
        if search_key == "" and name == "":
            if self.check_play_next():
                await self._play_next()
                return
            else:
                name = self.cur_music
        self.log.info(f"play. search_key:{search_key} name:{name}")

        # 本地歌曲不存在时下载
        name = self.xiaomusic.find_real_music_name(name)
        if not self.xiaomusic.is_music_exist(name):
            if self.config.disable_download:
                await self.do_tts(f"本地不存在歌曲{name}")
                return
            await self.download(search_key, name)
            self.log.info(f"正在下载中 {search_key} {name}")
            await self._download_proc.wait()
            # 把文件插入到播放列表里
            self.add_download_music(name)
        await self._playmusic(name)

    # 下一首
    async def play_next(self):
        return await self._play_next()

    async def _play_next(self):
        self.log.info("开始播放下一首")
        name = self.cur_music
        if (
            self.device.play_type == PLAY_TYPE_ALL
            or self.device.play_type == PLAY_TYPE_RND
            or name == ""
            or (name not in self._play_list)
        ):
            name = self.get_next_music()
        self.log.info(f"_play_next. name:{name}, cur_music:{self.cur_music}")
        if name == "":
            await self.do_tts("本地没有歌曲")
            return
        await self._play(name)

    # 播放本地歌曲
    async def playlocal(self, name):
        self._last_cmd = "playlocal"
        if name == "":
            if self.check_play_next():
                await self._play_next()
                return
            else:
                name = self.cur_music

        self.log.info(f"playlocal. name:{name}")

        # 本地歌曲不存在时下载
        name = self.xiaomusic.find_real_music_name(name)
        if not self.xiaomusic.is_music_exist(name):
            await self.do_tts(f"本地不存在歌曲{name}")
            return
        await self._playmusic(name)

    async def _playmusic(self, name):
        # 取消组内所有的下一首歌曲的定时器
        self.cancel_group_next_timer()

        self._playing = True
        self.cur_music = name
        self.log.info(f"cur_music {self.cur_music}")
        sec, url = await self.xiaomusic.get_music_sec_url(name)
        await self.group_force_stop_xiaoai()
        self.log.info(f"播放 {url}")
        results = await self.group_player_play(url)
        if all(ele is None for ele in results):
            self.log.info(f"播放 {name} 失败")
            await asyncio.sleep(1)
            if self.isplaying() and self._last_cmd != "stop":
               await self._play_next()
            return

        self.log.info(f"【{name}】已经开始播放了")

        # 设置下一首歌曲的播放定时器
        if sec <= 1:
            self.log.info(f"【{name}】不会设置下一首歌的定时器")
            return
        sec = sec + self.config.delay_sec
        await self.set_next_music_timeout(sec)

    async def do_tts(self, value):
        self.log.info(f"try do_tts value:{value}")
        if not value:
            self.log.info("do_tts no value")
            return

        # await self.group_force_stop_xiaoai()
        await self.text_to_speech(value)

        # 最大等8秒
        sec = min(8, int(len(value) / 3))
        await asyncio.sleep(sec)
        self.log.info(f"do_tts ok. cur_music:{self.cur_music}")
        await self.check_replay()

    async def force_stop_xiaoai(self, device_id):
        try:
            ret = await self.xiaomusic.mina_service.player_pause(device_id)
            self.log.info(
                f"force_stop_xiaoai player_pause device_id:{device_id} ret:{ret}"
            )
            await self.stop_if_xiaoai_is_playing(device_id)
        except Exception as e:
            self.log.exception(f"Execption {e}")

    async def get_if_xiaoai_is_playing(self):
        playing_info = await self.xiaomusic.mina_service.player_get_status(
            self.device_id
        )
        self.log.info(playing_info)
        # WTF xiaomi api
        is_playing = (
            json.loads(playing_info.get("data", {}).get("info", "{}")).get("status", -1)
            == 1
        )
        return is_playing

    async def stop_if_xiaoai_is_playing(self, device_id):
        is_playing = await self.get_if_xiaoai_is_playing()
        if is_playing or self.config.enable_force_stop:
            # stop it
            ret = await self.xiaomusic.mina_service.player_stop(device_id)
            self.log.info(
                f"stop_if_xiaoai_is_playing player_stop device_id:{device_id} enable_force_stop:{self.config.enable_force_stop} ret:{ret}"
            )

    # 是否在下载中
    def isdownloading(self):
        if not self._download_proc:
            return False

        if self._download_proc.returncode is not None:
            self.log.info(
                f"Process exited with returncode:{self._download_proc.returncode}"
            )
            return False

        self.log.info("Download Process is still running.")
        return True

    # 下载歌曲
    async def download(self, search_key, name):
        if self._download_proc:
            try:
                self._download_proc.kill()
            except ProcessLookupError:
                pass

        sbp_args = (
            "yt-dlp",
            f"{self.config.search_prefix}{search_key}",
            "-x",
            "--audio-format",
            "mp3",
            "--paths",
            self.download_path,
            "-o",
            f"{name}.mp3",
            "--ffmpeg-location",
            f"{self.ffmpeg_location}",
            "--no-playlist",
        )

        if self.config.proxy:
            sbp_args += ("--proxy", f"{self.config.proxy}")

        cmd = " ".join(sbp_args)
        self.log.info(f"download cmd: {cmd}")
        self._download_proc = await asyncio.create_subprocess_exec(*sbp_args)
        await self.do_tts(f"正在下载歌曲{search_key}")

    # 继续播放被打断的歌曲
    async def check_replay(self):
        if self.isplaying() and not self.isdownloading():
            # 继续播放歌曲
            self.log.info("现在继续播放歌曲")
            await self._play()
        else:
            self.log.info(
                f"不会继续播放歌曲. isplaying:{self.isplaying()} isdownloading:{self.isdownloading()}"
            )

    # 当前是否正在播放歌曲
    def isplaying(self):
        return self._playing

    # 把下载的音乐加入播放列表
    def add_download_music(self, name):
        self.xiaomusic.all_music[name] = os.path.join(self.download_path, f"{name}.mp3")
        if name not in self._play_list:
            self._play_list.append(name)
            self.log.info(f"add_download_music add_music {name}")
            self.log.debug(self._play_list)

    # 获取下一首
    def get_next_music(self):
        play_list_len = len(self._play_list)
        if play_list_len == 0:
            self.log.warning("当前播放列表没有歌曲")
            return ""
        index = 0
        try:
            index = self._play_list.index(self.cur_music)
        except ValueError:
            pass
        if play_list_len == 1:
            next_index = index  # 当只有一首歌曲时保持当前索引不变
        else:
            # 顺序往后找1个
            next_index = index + 1
            if next_index >= play_list_len:
                next_index = 0
            # 排除当前歌曲随机找1个
            if self.device.play_type == PLAY_TYPE_RND:
                indices = list(range(play_list_len))
                indices.remove(index)
                next_index = random.choice(indices)
        name = self._play_list[next_index]
        if not self.xiaomusic.is_music_exist(name):
            self._play_list.pop(next_index)
            self.log.info(f"pop not exist music:{name}")
            return self.get_next_music()
        return name

    # 判断是否播放下一首歌曲
    def check_play_next(self):
        # 当前歌曲不在当前播放列表
        if self.cur_music not in self._play_list:
            self.log.info(f"当前歌曲 {self.cur_music} 不在当前播放列表")
            return True

        # 当前没我在播放的歌曲
        if self.cur_music == "":
            self.log.info("当前没我在播放的歌曲")
            return True
        else:
            # 当前播放的歌曲不存在了
            if not self.xiaomusic.is_music_exist(self.cur_music):
                self.log.info(f"当前播放的歌曲 {self.cur_music} 不存在了")
                return True
        return False

    async def text_to_speech(self, value):
        try:
            await self.xiaomusic.mina_service.text_to_speech(self.device_id, value)
        except Exception as e:
            self.log.exception(f"Execption {e}")

    # 同一组设备播放
    async def group_player_play(self, url):
        device_id_list = self.xiaomusic.get_group_device_id_list(self.group_name)
        tasks = [self.play_one_url(device_id, url) for device_id in device_id_list]
        results = await asyncio.gather(*tasks)
        self.log.info(f"group_player_play {url} {device_id_list} {results}")
        return results

    async def play_one_url(self, device_id, url):
        ret = None
        try:
            if self.config.use_music_api:
                ret = await self.xiaomusic.mina_service.play_by_music_url(
                    device_id, url
                )
                self.log.info(
                    f"play_one_url play_by_music_url device_id:{device_id} ret:{ret} url:{url}"
                )
            else:
                ret = await self.xiaomusic.mina_service.play_by_url(device_id, url)
                self.log.info(
                    f"play_one_url play_by_url device_id:{device_id} ret:{ret} url:{url}"
                )
        except Exception as e:
            self.log.exception(f"Execption {e}")
        return ret

    # 设置下一首歌曲的播放定时器
    async def set_next_music_timeout(self, sec):
        self.cancel_next_timer()
        self._timeout = sec

        async def _do_next():
            await asyncio.sleep(self._timeout)
            try:
                self.log.info("定时器时间到了")
                self._next_timer = None
                await self._play_next()
            except Exception as e:
                self.log.error(f"Execption {e}")

        self._next_timer = asyncio.create_task(_do_next())
        self.log.info(f"{sec} 秒后将会播放下一首歌曲")

    async def set_volume(self, volume: int):
        self.log.info("set_volume. volume:%d", volume)
        try:
            await self.xiaomusic.mina_service.player_set_volume(self.device_id, volume)
        except Exception as e:
            self.log.exception(f"Execption {e}")

    async def get_volume(self):
        playing_info = await self.xiaomusic.mina_service.player_get_status(
            self.device_id
        )
        self.log.info(f"get_volume. playing_info:{playing_info}")
        volume = json.loads(playing_info.get("data", {}).get("info", "{}")).get(
            "volume", 0
        )
        volume = int(volume)
        self.log.info("get_volume. volume:%d", volume)
        return volume

    async def set_play_type(self, play_type):
        self.device.play_type = play_type
        self.xiaomusic.save_cur_config()
        tts = PLAY_TYPE_TTS[play_type]
        await self.do_tts(tts)

    async def play_music_list(self, list_name, music_name):
        self._last_cmd = "play_music_list"
        self._cur_play_list = list_name
        self._play_list = self.xiaomusic.music_list[list_name]
        self.log.info(f"开始播放列表{list_name}")
        await self._play(music_name)

    async def stop(self, arg1=""):
        self._last_cmd = "stop"
        self._playing = False
        if arg1 != "notts":
            await self.do_tts(self.config.stop_tts_msg)
        # 取消组内所有的下一首歌曲的定时器
        self.cancel_group_next_timer()
        await self.group_force_stop_xiaoai()
        self.log.info("stop now")

    async def group_force_stop_xiaoai(self):
        device_id_list = self.xiaomusic.get_group_device_id_list(self.group_name)
        self.log.info(f"group_force_stop_xiaoai {device_id_list}")
        tasks = [self.force_stop_xiaoai(device_id) for device_id in device_id_list]
        results = await asyncio.gather(*tasks)
        self.log.info(f"group_force_stop_xiaoai {device_id_list} {results}")
        return results

    async def stop_after_minute(self, minute: int):
        if self._stop_timer:
            self._stop_timer.cancel()
            self._stop_timer = None
            self.log.info("关机定时器已取消")

        async def _do_stop():
            await asyncio.sleep(minute * 60)
            try:
                await self.stop(arg1="notts")
            except Exception as e:
                self.log.exception(f"Execption {e}")

        self._stop_timer = asyncio.create_task(_do_stop())
        await self.do_tts(f"收到,{minute}分钟后将关机")

    def cancel_next_timer(self):
        if self._next_timer:
            self._next_timer.cancel()
            self.log.info(f"下一曲定时器已取消 {self.device_id}")
            self._next_timer = None

    def cancel_group_next_timer(self):
        devices = self.xiaomusic.get_group_devices(self.group_name)
        for device in devices.values():
            device.cancel_next_timer()

    def get_cur_play_list(self):
        return self._cur_play_list

    # 清空所有定时器
    def cancel_all_timer(self):
        self.log.info("in cancel_all_timer")
        if self._next_timer:
            self._next_timer.cancel()
            self._next_timer = None
            self.log.info("cancel_all_timer _next_timer.cancel")

        if self._stop_timer:
            self._stop_timer.cancel()
            self._stop_timer = None
            self.log.info("cancel_all_timer _stop_timer.cancel")

    @classmethod
    def dict_clear(cls, d):
        for key in list(d):
            val = d.pop(key)
            val.cancel_all_timer()
