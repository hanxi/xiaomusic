#!/usr/bin/env python3
import asyncio
import base64
import copy
import json
import logging
import math
import os
import random
import re
import time
import urllib.parse
from collections import OrderedDict
from dataclasses import asdict
from logging.handlers import RotatingFileHandler

from aiohttp import ClientSession, ClientTimeout
from miservice import MiAccount, MiIOService, MiNAService, miio_command
from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from xiaomusic import __version__
from xiaomusic.analytics import Analytics
from xiaomusic.config import (
    KEY_WORD_ARG_BEFORE_DICT,
    Config,
    Device,
)
from xiaomusic.const import (
    COOKIE_TEMPLATE,
    GET_ASK_BY_MINA,
    LATEST_ASK_API,
    NEED_USE_PLAY_MUSIC_API,
    PLAY_TYPE_ALL,
    PLAY_TYPE_ONE,
    PLAY_TYPE_RND,
    PLAY_TYPE_SEQ,
    PLAY_TYPE_SIN,
    SUPPORT_MUSIC_TYPE,
    TTS_COMMAND,
)
from xiaomusic.crontab import Crontab
from xiaomusic.plugin import PluginManager
from xiaomusic.utils import (
    Metadata,
    MusicUrlCache,
    chinese_to_number,
    chmodfile,
    custom_sort_key,
    deepcopy_data_no_sensitive_info,
    extract_audio_metadata,
    find_best_match,
    fuzzyfinder,
    get_local_music_duration,
    get_web_music_duration,
    list2str,
    not_in_dirs,
    parse_cookie_string,
    parse_str_to_dict,
    save_picture_by_base64,
    set_music_tag_to_file,
    thdplay,
    traverse_music_directory,
    try_add_access_control_param,
)


class XiaoMusic:
    def __init__(self, config: Config):
        self.config = config

        self.mi_token_home = os.path.join(self.config.conf_path, ".mi.token")
        self.session = None
        self.last_timestamp = {}  # key为 did. timestamp last call mi speaker
        self.last_record = None
        self.cookie_jar = None
        self.mina_service = None
        self.miio_service = None
        self.login_acount = None
        self.login_password = None
        self.polling_event = asyncio.Event()
        self.new_record_event = asyncio.Event()
        self.url_cache = MusicUrlCache()

        self.all_music = {}
        self._all_radio = {}  # 电台列表
        self._web_music_api = {}  # 需要通过api获取播放链接的列表
        self.music_list = {}  # 播放列表 key 为目录名, value 为 play_list
        self.default_music_list_names = []  # 非自定义个歌单
        self.devices = {}  # key 为 did
        self._cur_did = None  # 当前设备did
        self.running_task = []
        self.all_music_tags = {}  # 歌曲额外信息
        self._tag_generation_task = False
        self._extra_index_search = {}
        self.custom_play_list = None

        # 初始化配置
        self.init_config()

        # 初始化日志
        self.setup_logger()

        # 计划任务
        self.crontab = Crontab(self.log)

        # 初始化 JS 插件管理器
        try:
            from xiaomusic.js_plugin_manager import JSPluginManager

            self.js_plugin_manager = JSPluginManager(self)
            self.log.info("JS Plugin Manager initialized successfully")
        except Exception as e:
            self.log.error(f"Failed to initialize JS Plugin Manager: {e}")
            self.js_plugin_manager = None

        # 初始化 JS 插件适配器
        try:
            from xiaomusic.js_adapter import JSAdapter

            self.js_adapter = JSAdapter(self)
            self.log.info("JS Adapter initialized successfully")
        except Exception as e:
            self.log.error(f"Failed to initialize JS Adapter: {e}")

        # 尝试从设置里加载配置
        self.try_init_setting()

        # 启动时重新生成一次播放列表
        self._gen_all_music_list()

        # 初始化插件
        self.plugin_manager = PluginManager(self)

        # 更新设备列表
        self.update_devices()

        # 启动统计
        self.analytics = Analytics(self.log, self.config)

        debug_config = deepcopy_data_no_sensitive_info(self.config)
        self.log.info(f"Startup OK. {debug_config}")

        if self.config.conf_path == self.music_path:
            self.log.warning("配置文件目录和音乐目录建议设置为不同的目录")

    # 私有方法：调用插件方法的通用封装
    async def __call_plugin_method(
        self,
        plugin_name: str,
        method_name: str,
        music_item: dict,
        result_key: str,
        required_field: str = None,
        **kwargs,
    ):
        """
        通用方法：调用 JS 插件的方法并返回结果

        Args:
            plugin_name: 插件名称
            method_name: 插件方法名（如 get_media_source 或 get_lyric）
            music_item: 音乐项数据
            result_key: 返回结果中的字段名（如 'url' 或 'rawLrc'）
            required_field: 必须存在的字段（用于校验）
            **kwargs: 传递给插件方法的额外参数

        Returns:
            dict: 包含 success 和对应字段的字典
        """
        if not music_item:
            return {"success": False, "error": "Music item required"}

        # 检查插件管理器是否可用
        if not self.js_plugin_manager:
            return {"success": False, "error": "JS Plugin Manager not available"}

        enabled_plugins = self.js_plugin_manager.get_enabled_plugins()
        if plugin_name not in enabled_plugins:
            return {"success": False, "error": f"Plugin {plugin_name} not enabled"}

        try:
            # 调用插件方法，传递额外参数
            result = getattr(self.js_plugin_manager, method_name)(
                plugin_name, music_item, **kwargs
            )
            if (
                not result
                or not result.get(result_key)
                or result.get(result_key) == "None"
            ):
                return {"success": False, "error": f"Failed to get {result_key}"}

            # 如果指定了必填字段，则额外校验
            if required_field and not result.get(required_field):
                return {
                    "success": False,
                    "error": f"Missing required field: {required_field}",
                }
            # 追加属性后返回
            result["success"] = True
            return result

        except Exception as e:
            self.log.error(f"Plugin {plugin_name} {method_name} failed: {e}")
            return {"success": False, "error": str(e)}

    def init_config(self):
        self.music_path = self.config.music_path
        self.download_path = self.config.download_path
        if not self.download_path:
            self.download_path = self.music_path

        if not os.path.exists(self.download_path):
            os.makedirs(self.download_path)

        self.hostname = self.config.hostname
        if not self.hostname.startswith(("http://", "https://")):
            self.hostname = f"http://{self.hostname}"  # 默认 http
        self.port = self.config.port
        self.public_port = self.config.public_port
        if self.public_port == 0:
            self.public_port = self.port
        # 自动3thplay生成播放 post url
        self.thdtarget = f"{self.hostname}:{self.public_port}/thdaction"  # "HTTP://192.168.1.10:58090/thdaction"

        self.active_cmd = self.config.active_cmd.split(",")
        self.exclude_dirs = set(self.config.exclude_dirs.split(","))
        self.music_path_depth = self.config.music_path_depth
        self.continue_play = self.config.continue_play

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
        date_format = "[%Y-%m-%d %H:%M:%S]"
        formatter = logging.Formatter(fmt=log_format, datefmt=date_format)
        logging.basicConfig(
            format=log_format,
            datefmt=date_format,
        )

        log_file = self.config.log_file
        log_path = os.path.dirname(log_file)
        if log_path and not os.path.exists(log_path):
            os.makedirs(log_path)
        if os.path.exists(log_file):
            try:
                os.remove(log_file)
            except Exception as e:
                self.log.warning(f"无法删除旧日志文件: {log_file} {e}")
        handler = RotatingFileHandler(
            self.config.log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=1,
            encoding="utf-8",
        )
        handler.stream.flush()
        handler.setFormatter(formatter)
        self.log = logging.getLogger("xiaomusic")
        self.log.addHandler(handler)
        self.log.setLevel(logging.DEBUG if self.config.verbose else logging.INFO)

    async def poll_latest_ask(self):
        async with ClientSession() as session:
            while True:
                if not self.config.enable_pull_ask:
                    self.log.debug("Listening new message disabled")
                    await asyncio.sleep(5)
                    continue

                self.log.debug(
                    f"Listening new message, timestamp: {self.last_timestamp}"
                )
                session._cookie_jar = self.cookie_jar

                # 拉取所有音箱的对话记录
                tasks = []
                for device_id in self.device_id_did:
                    # 首次用当前时间初始化
                    did = self.get_did(device_id)
                    if did not in self.last_timestamp:
                        self.last_timestamp[did] = int(time.time() * 1000)

                    hardware = self.get_hardward(device_id)
                    if (hardware in GET_ASK_BY_MINA) or self.config.get_ask_by_mina:
                        tasks.append(self.get_latest_ask_by_mina(device_id))
                    else:
                        tasks.append(
                            self.get_latest_ask_from_xiaoai(session, device_id)
                        )
                await asyncio.gather(*tasks)

                start = time.perf_counter()
                await self.polling_event.wait()
                if self.config.pull_ask_sec <= 1:
                    if (d := time.perf_counter() - start) < 1:
                        await asyncio.sleep(1 - d)
                else:
                    sleep_sec = 0
                    while True:
                        await asyncio.sleep(1)
                        sleep_sec = sleep_sec + 1
                        if sleep_sec >= self.config.pull_ask_sec:
                            break

    async def init_all_data(self, session):
        self.mi_token_home = os.path.join(self.config.conf_path, ".mi.token")
        is_need_login = await self.need_login()
        if is_need_login:
            self.log.info("try login")
            await self.login_miboy(session)
        else:
            self.log.info("already logined")
        await self.try_update_device_id()
        cookie_jar = self.get_cookie()
        if cookie_jar:
            session.cookie_jar.update_cookies(cookie_jar)
        self.cookie_jar = session.cookie_jar

    async def need_login(self):
        if self.mina_service is None:
            return True
        if self.mina_service is None:
            return True
        if self.login_acount != self.config.account:
            return True
        if self.login_password != self.config.password:
            return True

        try:
            await self.mina_service.device_list()
        except Exception as e:
            self.log.warning(f"可能登录失败. {e}")
            return True
        return False

    async def login_miboy(self, session):
        try:
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
            self.login_acount = self.config.account
            self.login_password = self.config.password
            self.log.info(f"登录完成. {self.login_acount}")
        except Exception as e:
            self.mina_service = None
            self.miio_service = None
            self.log.warning(f"可能登录失败. {e}")

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
                    # 将did存一下 方便其他地方调用
                    self._cur_did = did
                    device.device_id = device_id
                    device.hardware = hardware
                    device.name = name
                    devices[did] = device
            self.config.devices = devices
            self.log.info(f"选中的设备: {devices}")
        except Exception as e:
            self.log.warning(f"可能登录失败. {e}")

    def get_cookie(self):
        if self.config.cookie:
            cookie_jar = parse_cookie_string(self.config.cookie)
            return cookie_jar

        if not os.path.exists(self.mi_token_home):
            self.log.warning(f"{self.mi_token_home} file not exist")
            return None

        with open(self.mi_token_home, encoding="utf-8") as f:
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

                # 检查响应状态码
                if r.status != 200:
                    self.log.warning(f"Request failed with status {r.status}")
                    # fix #362
                    if i == 2 and r.status == 401:
                        await self.init_all_data(self.session)
                    continue

            except asyncio.CancelledError:
                self.log.warning("Task was cancelled.")
                return None

            except Exception as e:
                self.log.warning(f"Execption {e}")
                continue

            try:
                data = await r.json()
            except Exception as e:
                self.log.warning(f"Execption {e}")
                if i == 2:
                    # tricky way to fix #282 #272 # if it is the third time we re init all data
                    self.log.info("Maybe outof date trying to re init it")
                    await self.init_all_data(self.session)
            else:
                return self._get_last_query(device_id, data)
        self.log.warning("get_latest_ask_from_xiaoai. All retries failed.")

    async def get_latest_ask_by_mina(self, device_id):
        try:
            did = self.get_did(device_id)
            messages = await self.mina_service.get_latest_ask(device_id)
            self.log.debug(
                f"get_latest_ask_by_mina device_id:{device_id} did:{did} messages:{messages}"
            )
            for message in messages:
                query = message.response.answer[0].question
                answer = message.response.answer[0].content
                last_record = {
                    "time": message.timestamp_ms,
                    "did": did,
                    "query": query,
                    "answer": answer,
                }
                self._check_last_query(last_record)
        except Exception as e:
            self.log.warning(f"get_latest_ask_by_mina {e}")
        return

    def _get_last_query(self, device_id, data):
        did = self.get_did(device_id)
        self.log.debug(f"_get_last_query device_id:{device_id} did:{did} data:{data}")
        if d := data.get("data"):
            records = json.loads(d).get("records")
            if not records:
                return
            last_record = records[0]
            last_record["did"] = did
            answers = last_record.get("answers", [{}])
            if answers:
                answer = answers[0].get("tts", {}).get("text", "").strip()
                last_record["answer"] = answer
            self._check_last_query(last_record)

    def _check_last_query(self, last_record):
        did = last_record["did"]
        timestamp = last_record.get("time")
        query = last_record.get("query", "").strip()
        self.log.debug(f"{did} 获取到最后一条对话记录：{query} {timestamp}")

        if timestamp > self.last_timestamp[did]:
            self.last_timestamp[did] = timestamp
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

    # 是否是需要通过api获取播放链接的网络歌曲
    def is_need_use_play_music_api(self, name):
        return name in self._web_music_api

    def get_music_tags(self, name):
        tags = copy.copy(self.all_music_tags.get(name, asdict(Metadata())))
        picture = tags["picture"]
        if picture:
            if picture.startswith(self.config.picture_cache_path):
                picture = picture[len(self.config.picture_cache_path) :]
            picture = picture.replace("\\", "/")
            if picture.startswith("/"):
                picture = picture[1:]
            encoded_name = urllib.parse.quote(picture)
            tags["picture"] = try_add_access_control_param(
                self.config,
                f"{self.hostname}:{self.public_port}/picture/{encoded_name}",
            )
        return tags

    # 修改标签信息
    def set_music_tag(self, name, info):
        if self._tag_generation_task:
            self.log.info("tag 更新中，请等待")
            return "Tag generation task running"
        tags = copy.copy(self.all_music_tags.get(name, asdict(Metadata())))
        tags["title"] = info.title
        tags["artist"] = info.artist
        tags["album"] = info.album
        tags["year"] = info.year
        tags["genre"] = info.genre
        tags["lyrics"] = info.lyrics
        file_path = self.all_music[name]
        if info.picture:
            tags["picture"] = save_picture_by_base64(
                info.picture, self.config.picture_cache_path, file_path
            )
        if self.config.enable_save_tag and (not self.is_web_music(name)):
            set_music_tag_to_file(file_path, Metadata(tags))
        self.all_music_tags[name] = tags
        self.try_save_tag_cache()
        return "OK"

    async def get_music_sec_url(self, name, true_url):
        """获取歌曲播放时长和播放地址

        Args:
            name: 歌曲名称
            true_url: 真实播放URL
        Returns:
            tuple: (播放时长(秒), 播放地址)
        """

        # 获取播放时长
        if true_url is not None:
            url = true_url
            sec = await self._get_online_music_duration(name, true_url)
            self.log.info(f"在线歌曲时长获取：：{name} ；sec：：{sec}")
        else:
            url, origin_url = await self.get_music_url(name)
            self.log.info(
                f"get_music_sec_url. name:{name} url:{url} origin_url:{origin_url}"
            )

            # 电台直接返回
            if self.is_web_radio_music(name):
                self.log.info("电台不会有播放时长")
                return 0, url
            if self.is_web_music(name):
                sec = await self._get_web_music_duration(name, url, origin_url)
            else:
                sec = await self._get_local_music_duration(name, url)

        if sec <= 0:
            self.log.warning(f"获取歌曲时长失败 {name} {url}")
        return sec, url

    async def _get_web_music_duration(self, name, url, origin_url):
        """获取网络音乐时长"""
        if not origin_url:
            origin_url = url if url else self.all_music[name]

        if self.config.web_music_proxy:
            # 代理模式使用原始地址获取时长
            duration, _ = await get_web_music_duration(origin_url, self.config)
        else:
            duration, url = await get_web_music_duration(origin_url, self.config)

        sec = math.ceil(duration)
        self.log.info(f"网络歌曲 {name} : {origin_url} {url} 的时长 {sec} 秒")
        return sec

    async def _get_local_music_duration(self, name, url):
        """获取本地音乐时长"""
        filename = self.get_filename(name)
        self.log.info(f"get_music_sec_url. name:{name} filename:{filename}")
        duration = await get_local_music_duration(filename, self.config)
        sec = math.ceil(duration)
        self.log.info(f"本地歌曲 {name} : {filename} {url} 的时长 {sec} 秒")
        return sec

    async def _get_online_music_duration(self, name, url):
        """获取在线音乐时长"""
        self.log.info(f"get_music_sec_url. name:{name}")
        duration = await get_local_music_duration(url, self.config)
        sec = math.ceil(duration)
        self.log.info(f"在线歌曲 {name} : {url} 的时长 {sec} 秒")
        return sec

    async def get_music_url(self, name):
        """获取音乐播放地址

        Args:
            name: 歌曲名称
        Returns:
            tuple: (播放地址, 原始地址) - 网络音乐时可能有原始地址
        """
        if self.is_web_music(name):
            return await self._get_web_music_url(name)
        return self._get_local_music_url(name), None

    async def _get_web_music_url(self, name):
        """获取网络音乐播放地址"""
        url = self.all_music[name]
        self.log.info(f"get_music_url web music. name:{name}, url:{url}")

        # 需要通过API获取真实播放地址
        if self.is_need_use_play_music_api(name):
            url = await self._get_url_from_api(name, url)
            if not url:
                return "", None

        # 是否需要代理
        if self.config.web_music_proxy:
            proxy_url = self._get_proxy_url(url)
            return proxy_url, url

        return url, None

    async def _get_url_from_api(self, name, url):
        """通过API获取真实播放地址"""
        headers = self._web_music_api[name].get("headers", {})
        url = await self.url_cache.get(url, headers, self.config)
        if not url:
            self.log.error(f"get_music_url use api fail. name:{name}, url:{url}")
        return url

    def _get_proxy_url(self, origin_url):
        """获取代理URL"""
        urlb64 = base64.b64encode(origin_url.encode("utf-8")).decode("utf-8")
        proxy_url = f"{self.hostname}:{self.public_port}/proxy?urlb64={urlb64}"
        self.log.info(f"Using proxy url: {proxy_url}")
        return proxy_url

    def _get_local_music_url(self, name):
        """获取本地音乐播放地址"""
        filename = self.get_filename(name)

        # 处理文件路径
        if filename.startswith(self.config.music_path):
            filename = filename[len(self.config.music_path) :]
        filename = filename.replace("\\", "/")
        if filename.startswith("/"):
            filename = filename[1:]

        self.log.info(
            f"_get_local_music_url local music. name:{name}, filename:{filename}"
        )

        # 构造URL
        encoded_name = urllib.parse.quote(filename)
        url = f"{self.hostname}:{self.public_port}/music/{encoded_name}"
        return try_add_access_control_param(self.config, url)

    # 给前端调用
    def refresh_music_tag(self):
        if not self.ensure_single_thread_for_tag():
            return
        filename = self.config.tag_cache_path
        if filename is not None:
            # 清空 cache
            with open(filename, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            self.log.info("刷新：已清空 tag cache")
        else:
            self.log.info("刷新：tag cache 未启用")
        # TODO: 优化性能？
        # TODO 如何安全的清空 picture_cache_path
        self.all_music_tags = {}  # 需要清空内存残留
        self.try_gen_all_music_tag()
        self.log.info("刷新：已启动重建 tag cache")

    def try_load_from_tag_cache(self) -> dict:
        filename = self.config.tag_cache_path
        tag_cache = {}
        try:
            if filename is not None:
                if os.path.exists(filename):
                    with open(filename, encoding="utf-8") as f:
                        tag_cache = json.load(f)
                    self.log.info(f"已从【{filename}】加载 tag cache")
                else:
                    self.log.info(f"【{filename}】tag cache 已启用，但文件不存在")
            else:
                self.log.info("加载：tag cache 未启用")
        except Exception as e:
            self.log.exception(f"Execption {e}")
        return tag_cache

    def try_save_tag_cache(self):
        filename = self.config.tag_cache_path
        if filename is not None:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(self.all_music_tags, f, ensure_ascii=False, indent=2)
            self.log.info(f"保存：tag cache 已保存到【{filename}】")
        else:
            self.log.info("保存：tag cache 未启用")

    def ensure_single_thread_for_tag(self):
        if self._tag_generation_task:
            self.log.info("tag 更新中，请等待")
        return not self._tag_generation_task

    def try_gen_all_music_tag(self, only_items: dict = None):
        if self.ensure_single_thread_for_tag():
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._gen_all_music_tag(only_items))
                self.log.info("启动后台构建 tag cache")
            else:
                self.log.info("协程时间循环未启动")

    async def _gen_all_music_tag(self, only_items: dict = None):
        self._tag_generation_task = True
        if only_items is None:
            only_items = self.all_music  # 默认更新全部

        all_music_tags = self.try_load_from_tag_cache()
        all_music_tags.update(self.all_music_tags)  # 保证最新

        ignore_tag_absolute_dirs = self.config.get_ignore_tag_dirs()
        self.log.info(f"ignore_tag_absolute_dirs: {ignore_tag_absolute_dirs}")
        for name, file_or_url in only_items.items():
            start = time.perf_counter()
            if name not in all_music_tags:
                try:
                    if self.is_web_music(name):
                        # TODO: 网络歌曲获取歌曲额外信息
                        pass
                    elif os.path.exists(file_or_url) and not_in_dirs(
                        file_or_url, ignore_tag_absolute_dirs
                    ):
                        all_music_tags[name] = extract_audio_metadata(
                            file_or_url, self.config.picture_cache_path
                        )
                    else:
                        self.log.info(f"{name}/{file_or_url} 无法更新 tag")
                except BaseException as e:
                    self.log.exception(f"{e} {file_or_url} error {type(file_or_url)}!")
            if (time.perf_counter() - start) < 1:
                await asyncio.sleep(0.001)
            else:
                # 处理一首歌超过1秒，则等1秒，解决挂载网盘卡死的问题
                await asyncio.sleep(1)
        # 全部更新结束后，一次性赋值
        self.all_music_tags = all_music_tags
        # 刷新 tag cache
        self.try_save_tag_cache()
        self._tag_generation_task = False
        self.log.info("tag 更新完成")

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

        self.music_list = OrderedDict(
            {
                "临时搜索列表": [],
                "所有歌曲": [],
                "所有电台": [],
                "收藏": [],
                "全部": [],  # 包含所有歌曲和所有电台
                "下载": [],  # 下载目录下的
                "其他": [],  # 主目录下的
                "最近新增": [],  # 按文件时间排序
            }
        )
        # 最近新增(不包含网络歌单)
        self.music_list["最近新增"] = sorted(
            self.all_music.keys(),
            key=lambda x: os.path.getmtime(self.all_music[x]),
            reverse=True,
        )[: self.config.recently_added_playlist_len]

        # 网络歌单
        try:
            # NOTE: 函数内会更新 self.all_music, self._music_list；重建 self._all_radio
            self._append_music_list()
        except Exception as e:
            self.log.exception(f"Execption {e}")

        # 全部，所有，自定义歌单（收藏）
        self.music_list["全部"] = list(self.all_music.keys())
        self.music_list["所有歌曲"] = [
            name for name in self.all_music.keys() if name not in self._all_radio
        ]

        # 文件夹歌单
        for dir_name, musics in all_music_by_dir.items():
            self.music_list[dir_name] = list(musics.keys())
            # self.log.debug("dir_name:%s, list:%s", dir_name, self.music_list[dir_name])

        # 歌单排序
        for _, play_list in self.music_list.items():
            play_list.sort(key=custom_sort_key)

        # 非自定义个歌单
        self.default_music_list_names = list(self.music_list.keys())

        # 刷新自定义歌单
        self.refresh_custom_play_list()

        # 更新每个设备的歌单
        self.update_all_playlist()

        # 重建索引
        self._extra_index_search = {}
        for k, v in self.all_music.items():
            # 如果不是 url，则增加索引
            if not (v.startswith("http") or v.startswith("https")):
                self._extra_index_search[v] = k

        # all_music 更新，重建 tag
        self.try_gen_all_music_tag()

    def refresh_custom_play_list(self):
        try:
            # 删除旧的自定义个歌单
            for k in list(self.music_list.keys()):
                if k not in self.default_music_list_names:
                    del self.music_list[k]
            # 合并新的自定义个歌单
            custom_play_list = self.get_custom_play_list()
            for k, v in custom_play_list.items():
                self.music_list[k] = list(v)
        except Exception as e:
            self.log.exception(f"Execption {e}")

    # 给歌单里补充网络歌单
    def _append_music_list(self):
        if not self.config.music_list_json:
            return

        self._all_radio = {}
        self._web_music_api = {}
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
                    if music.get("api"):
                        self._web_music_api[name] = music
                self.log.debug(one_music_list)
                # 歌曲名字相同会覆盖
                self.music_list[list_name] = one_music_list
            if self._all_radio:
                self.music_list["所有电台"] = list(self._all_radio.keys())
            # self.log.debug(self.all_music)
            # self.log.debug(self.music_list)
        except Exception as e:
            self.log.exception(f"Execption {e}")

    async def analytics_task_daily(self):
        while True:
            await self.analytics.send_daily_event()
            await asyncio.sleep(3600)

    def start_file_watch(self):
        if not self.config.enable_file_watch:
            self.log.info("目录监控功能已关闭")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        # 延时配置项 file_watch_debounce
        self._file_watch_handler = XiaoMusicPathWatch(
            callback=self._on_file_change,
            debounce_delay=self.config.file_watch_debounce,
            loop=loop,
        )
        # 创建监控 music_path 目录对象
        self._observer = Observer()
        self._observer.schedule(
            self._file_watch_handler, self.music_path, recursive=True
        )
        self._observer.start()
        self.log.info(f"已启动对 {self.music_path} 的目录监控。")

    def _on_file_change(self):
        self.log.info("检测到目录音乐文件变化，正在刷新歌曲列表。")
        self._gen_all_music_list()

    def stop_file_watch(self):
        if hasattr(self, "_observer"):
            self._observer.stop()
            self._observer.join()
            self.log.info("已停止目录监控。")

    async def run_forever(self):
        self.log.info("run_forever start")
        self.try_gen_all_music_tag()  # 事件循环开始后调用一次
        self.crontab.start()
        asyncio.create_task(self.analytics.send_startup_event())
        # 取配置 enable_file_watch 循环开始时调用一次，控制目录监控开关
        if self.config.enable_file_watch:
            self.start_file_watch()
        analytics_task = asyncio.create_task(self.analytics_task_daily())
        assert (
            analytics_task is not None
        )  # to keep the reference to task, do not remove this
        async with ClientSession() as session:
            self.session = session
            self.log.info(f"run_forever session:{self.session}")
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
                answer = new_record.get("answer")
                answers = new_record.get("answers", [{}])
                if answers:
                    answer = answers[0].get("tts", {}).get("text", "").strip()
                    await self.reset_timer_when_answer(len(answer), did)
                    self.log.debug(f"query:{query} did:{did} answer:{answer}")

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

    # 重置计时器
    async def reset_timer_when_answer(self, answer_length, did):
        await self.devices[did].reset_timer_when_answer(answer_length)

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

    async def is_task_finish(self):
        if len(self.running_task) == 0:
            return True
        task = self.running_task[0]
        if task and task.done():
            return True
        return False

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
            # 自定义口令
            if opvalue.startswith("exec#"):
                code = opvalue.split("#", 1)[1]
                return ("exec", code)
            return (opvalue, oparg)
        self.log.info(f"未匹配到指令 {query} {ctrl_panel}")
        return (None, None)

    def find_real_music_name(self, name, n):
        if not self.config.enable_fuzzy_match:
            self.log.debug("没开启模糊匹配")
            return []

        all_music_list = list(self.all_music.keys())
        real_names = find_best_match(
            name,
            all_music_list,
            cutoff=self.config.fuzzy_match_cutoff,
            n=n,
            extra_search_index=self._extra_index_search,
        )
        if real_names:
            if n > 1 and name not in real_names:
                # 模糊匹配模式，扩大范围再找，最后保留随机 n 个
                real_names = find_best_match(
                    name,
                    all_music_list,
                    cutoff=self.config.fuzzy_match_cutoff,
                    n=n * 2,
                    extra_search_index=self._extra_index_search,
                )
                random.shuffle(real_names)
                real_names = real_names[:n]
            elif name in real_names:
                # 可以精确匹配，限制只返回一个（保证网页端播放可用）
                real_names = [name]
            self.log.info(f"根据【{name}】找到歌曲【{real_names}】")
            return real_names
        self.log.info(f"没找到歌曲【{name}】")
        return []

    def did_exist(self, did):
        return did in self.devices

    # 播放一个 url
    async def play_url(self, did="", arg1="", **kwargs):
        self.log.info(f"手动播放链接：{arg1}")
        url = arg1
        return await self.devices[did].group_player_play(url)

    # 设置为单曲循环
    async def set_play_type_one(self, did="", **kwargs):
        await self.set_play_type(did, PLAY_TYPE_ONE)

    # 设置为全部循环
    async def set_play_type_all(self, did="", **kwargs):
        await self.set_play_type(did, PLAY_TYPE_ALL)

    # 设置为随机播放
    async def set_play_type_rnd(self, did="", **kwargs):
        await self.set_play_type(did, PLAY_TYPE_RND)

    # 设置为单曲播放
    async def set_play_type_sin(self, did="", **kwargs):
        await self.set_play_type(did, PLAY_TYPE_SIN)

    # 设置为顺序播放
    async def set_play_type_seq(self, did="", **kwargs):
        await self.set_play_type(did, PLAY_TYPE_SEQ)

    async def set_play_type(self, did="", play_type=PLAY_TYPE_RND, dotts=True):
        await self.devices[did].set_play_type(play_type, dotts)

    # 设置为刷新列表
    async def gen_music_list(self, **kwargs):
        self._gen_all_music_list()
        self.log.info("gen_music_list ok")

    # 删除歌曲
    async def cmd_del_music(self, did="", arg1="", **kwargs):
        if not self.config.enable_cmd_del_music:
            await self.do_tts(did, "语音删除歌曲功能未开启")
            return
        self.log.info(f"cmd_del_music {arg1}")
        name = arg1
        if len(name) == 0:
            name = self.playingmusic(did)
        await self.del_music(name)

    async def del_music(self, name):
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

    # ===========================MusicFree插件函数================================

    # 在线获取歌曲列表
    async def get_music_list_online(
        self, plugin="all", keyword="", page=1, limit=20, **kwargs
    ):
        self.log.info("在线获取歌曲列表!")
        """
        在线获取歌曲列表

        Args:
            plugin: 插件名称，"OpenAPI"表示 通过开放接口获取，其他为插件在线搜索
            keyword: 搜索关键词
            page: 页码
            limit: 每页数量
            **kwargs: 其他参数
        Returns:
            dict: 搜索结果
        """
        openapi_info = self.js_plugin_manager.get_openapi_info()
        if (
            openapi_info.get("enabled", False)
            and openapi_info.get("search_url", "") != ""
        ):
            # 开放接口获取
            return await self.js_plugin_manager.openapi_search(
                openapi_info.get("search_url"), keyword
            )
        else:
            if not self.js_plugin_manager:
                return {"success": False, "error": "JS Plugin Manager not available"}
            # 插件在线搜索
            return await self.get_music_list_mf(plugin, keyword, page, limit)

    @staticmethod
    async def get_real_url_of_openapi(url: str, timeout: int = 10) -> dict:
        """
        通过服务端代理获取开放接口真实的音乐播放URL，避免CORS问题
        Args:
            url (str): 原始音乐URL
            timeout (int): 请求超时时间(秒)

        Returns:
            dict: 包含success、realUrl、statusCode等信息的字典
        """
        from urllib.parse import urlparse

        import aiohttp

        try:
            # 验证URL格式
            parsed_url = urlparse(url)
            if not parsed_url.scheme or not parsed_url.netloc:
                return {"success": False, "url": url, "error": "Invalid URL format"}
            # 创建aiohttp客户端会话
            async with aiohttp.ClientSession() as session:
                # 发送HEAD请求跟随重定向
                async with session.head(
                    url,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    # 获取最终重定向后的URL
                    final_url = str(response.url)

                    return {
                        "success": True,
                        "url": final_url,
                        "statusCode": response.status,
                    }
        except Exception as e:
            return {"success": False, "url": url, "error": f"Error occurred: {str(e)}"}

    # 调用MusicFree插件获取歌曲列表
    async def get_music_list_mf(
        self, plugin="all", keyword="", page=1, limit=20, **kwargs
    ):
        self.log.info("通过MusicFree插件搜索音乐列表!")
        """
        通过MusicFree插件搜索音乐列表

        Args:
            plugin: 插件名称，"all"表示所有插件
            keyword: 搜索关键词
            page: 页码
            limit: 每页数量
            **kwargs: 其他参数

        Returns:
            dict: 搜索结果
        """
        # 检查JS插件管理器是否可用
        if not self.js_plugin_manager:
            return {"success": False, "error": "JS插件管理器不可用"}
        # 如果关键词包含 '-'，则提取歌手名、歌名
        if "-" in keyword:
            parts = keyword.split("-")
            keyword = parts[0]
            artist = parts[1]
        else:
            artist = ""
        try:
            if plugin == "all":
                # 搜索所有启用的插件
                return await self._search_all_plugins(keyword, artist, page, limit)
            else:
                # 搜索指定插件
                return await self._search_specific_plugin(
                    plugin, keyword, artist, page, limit
                )
        except Exception as e:
            self.log.error(f"搜索音乐时发生错误: {e}")
            return {"success": False, "error": str(e)}

    async def _search_all_plugins(self, keyword, artist, page, limit):
        """搜索所有启用的插件"""
        enabled_plugins = self.js_plugin_manager.get_enabled_plugins()
        if not enabled_plugins:
            return {"success": False, "error": "没有可用的接口和插件，请先进行配置！"}

        results = []
        sources = {}

        # 计算每个插件的限制数量
        plugin_count = len(enabled_plugins)
        item_limit = max(1, limit // plugin_count) if plugin_count > 0 else limit

        # 并行搜索所有插件
        search_tasks = [
            self._search_plugin_task(plugin_name, keyword, page, item_limit)
            for plugin_name in enabled_plugins
        ]

        plugin_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        # 处理搜索结果
        for i, result in enumerate(plugin_results):
            plugin_name = list(enabled_plugins)[i]

            # 检查是否为异常对象
            if isinstance(result, Exception):
                self.log.error(f"插件 {plugin_name} 搜索失败: {result}")
                continue

            # 检查是否为有效的搜索结果（修改这里的判断逻辑）
            if result and isinstance(result, dict):
                # 检查是否有错误信息
                if "error" in result:
                    self.log.error(
                        f"插件 {plugin_name} 搜索失败: {result.get('error', '未知错误')}"
                    )
                    continue

                # 处理成功的搜索结果
                data_list = result.get("data", [])
                if data_list:
                    results.extend(data_list)
                    sources[plugin_name] = len(data_list)
                # 如果没有data字段但有其他数据，也认为是成功的结果
                elif result:  # 非空字典
                    results.append(result)
                    sources[plugin_name] = 1

        # 统一排序并提取前limit条数据
        if results:
            unified_result = {"data": results}
            optimized_result = self.js_plugin_manager.optimize_search_results(
                unified_result,
                search_keyword=keyword,
                limit=limit,
                search_artist=artist,
            )
            results = optimized_result.get("data", [])

        return {
            "success": True,
            "data": results,
            "total": len(results),
            "sources": sources,
            "page": page,
            "limit": limit,
        }

    async def _search_specific_plugin(self, plugin, keyword, artist, page, limit):
        """搜索指定插件"""
        try:
            results = self.js_plugin_manager.search(plugin, keyword, page, limit)

            # 额外检查 resources 字段
            data_list = results.get("data", [])
            if data_list:
                # 优化搜索结果排序
                results = self.js_plugin_manager.optimize_search_results(
                    results, search_keyword=keyword, limit=limit, search_artist=artist
                )

            return {
                "success": True,
                "data": results.get("data", []),
                "total": results.get("total", 0),
                "page": page,
                "limit": limit,
            }
        except Exception as e:
            self.log.error(f"插件 {plugin} 搜索失败: {e}")
            return {"success": False, "error": str(e)}

    async def _search_plugin_task(self, plugin_name, keyword, page, limit):
        """单个插件搜索任务"""
        try:
            return self.js_plugin_manager.search(plugin_name, keyword, page, limit)
        except Exception as e:
            # 直接抛出异常，让 asyncio.gather 处理
            raise e

    # 调用MusicFree插件获取真实播放url
    async def get_media_source_url(self, music_item, quality: str = "standard"):
        """获取音乐项的媒体源URL
        Args:
            music_item : MusicFree插件定义的 IMusicItem
            quality: 音质参数
        Returns:
            dict: 包含成功状态和URL信息的字典
        """
        # kwargs可追加
        kwargs = {"quality": quality}
        return await self.__call_plugin_method(
            plugin_name=music_item.get("platform"),
            method_name="get_media_source",
            music_item=music_item,
            result_key="url",
            required_field="url",
            **kwargs,
        )

    # 调用MusicFree插件获取歌词
    async def get_media_lyric(self, music_item):
        """获取音乐项的歌词 Lyric
        Args:
            music_item : MusicFree插件定义的 IMusicItem
        Returns:
            dict: 包含成功状态和URL信息的字典
        """
        return await self.__call_plugin_method(
            plugin_name=music_item.get("platform"),
            method_name="get_lyric",
            music_item=music_item,
            result_key="rawLrc",
            required_field="rawLrc",
        )

    # 调用在线搜索歌曲，并优化返回
    async def search_music_online(self, search_key, name):
        """调用MusicFree插件搜索歌曲

        Args:
            search_key (str): 搜索关键词
            name (str): 歌曲名
        Returns:
            dict: 包含成功状态和URL信息的字典
        """

        try:
            # 获取歌曲列表
            result = await self.get_music_list_online(keyword=name, limit=10)
            self.log.info(f"在线搜索歌曲列表: {result}")

            if result.get("success") and result.get("total") > 0:
                # 打印输出 result.data
                self.log.info(f"歌曲列表: {result.get('data')}")
                # 根据搜素关键字，智能搜索出最符合的一条music_item
                music_item = await self._search_top_one(
                    result.get("data"), search_key, name
                )
                # 验证 music_item 是否为字典类型
                if not isinstance(music_item, dict):
                    self.log.error(
                        f"music_item should be a dict, but got {type(music_item)}: {music_item}"
                    )
                    return {"success": False, "error": "Invalid music item format"}

                # 如果是OpenAPI，则需要转换播放链接
                openapi_info = self.js_plugin_manager.get_openapi_info()
                if openapi_info.get("enabled", False):
                    return await self.get_real_url_of_openapi(music_item.get("url"))
                else:
                    media_source = await self.get_media_source_url(music_item)
                    if media_source.get("success"):
                        return {"success": True, "url": media_source.get("url")}
                    else:
                        return {"success": False, "error": media_source.get("error")}
            else:
                return {"success": False, "error": "未找到歌曲"}

        except Exception as e:
            # 记录错误日志
            self.log.error(f"searchKey {search_key} get media source failed: {e}")
            return {"success": False, "error": str(e)}

    async def _search_top_one(self, music_items, search_key, name):
        """智能搜索出最符合的一条music_item"""
        try:
            # 如果没有音乐项目，返回None
            if not music_items:
                return None

            self.log.info(f"搜索关键字: {search_key}；歌名：{name}")
            # 如果只有一个项目，直接返回
            if len(music_items) == 1:
                return music_items[0]

            # 计算每个项目的匹配分数
            def calculate_match_score(item):
                """计算匹配分数"""
                title = item.get("title", "").lower() if item.get("title") else ""
                artist = item.get("artist", "").lower() if item.get("artist") else ""
                keyword = search_key.lower()

                if not keyword:
                    return 0

                score = 0
                # 歌曲名匹配权重
                if keyword in title:
                    # 完全匹配得最高分
                    if title == keyword:
                        score += 90
                    # 开头匹配
                    elif title.startswith(keyword):
                        score += 70
                    # 结尾匹配
                    elif title.endswith(keyword):
                        score += 50
                    # 包含匹配
                    else:
                        score += 30
                # 部分字符匹配
                elif any(char in title for char in keyword.split()):
                    score += 10
                # 艺术家名匹配权重
                if keyword in artist:
                    # 完全匹配
                    if artist == keyword:
                        score += 9
                    # 开头匹配
                    elif artist.startswith(keyword):
                        score += 7
                    # 结尾匹配
                    elif artist.endswith(keyword):
                        score += 5
                    # 包含匹配
                    else:
                        score += 3
                # 部分字符匹配
                elif any(char in artist for char in keyword.split()):
                    score += 1
                return score

            # 按匹配分数排序，返回分数最高的项目
            sorted_items = sorted(music_items, key=calculate_match_score, reverse=True)
            return sorted_items[0]

        except Exception as e:
            self.log.error(f"_search_top_one error: {e}")
            # 出现异常时返回第一个项目
            return music_items[0] if music_items else None

    # ===========================================================

    def _find_real_music_list_name(self, list_name):
        if not self.config.enable_fuzzy_match:
            self.log.debug("没开启模糊匹配")
            return list_name

        # 模糊搜一个播放列表（只需要一个，不需要 extra index）
        real_name = find_best_match(
            list_name,
            self.music_list,
            cutoff=self.config.fuzzy_match_cutoff,
            n=1,
        )[0]
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

        music_name = ""
        if len(parts) > 1:
            music_name = parts[1]
        return await self.do_play_music_list(did, list_name, music_name)

    async def do_play_music_list(self, did, list_name, music_name=""):
        # 查找并获取真实的音乐列表名称
        list_name = self._find_real_music_list_name(list_name)
        # 检查音乐列表是否存在，如果不存在则进行语音提示并返回
        if list_name not in self.music_list:
            await self.do_tts(did, f"播放列表{list_name}不存在")
            return

        # 调用设备播放音乐列表的方法
        await self.devices[did].play_music_list(list_name, music_name)

    # 播放一个播放列表里第几个
    async def play_music_list_index(self, did="", arg1="", **kwargs):
        patternarg = r"^([零一二三四五六七八九十百千万亿]+)个(.*)"
        # 匹配参数
        matcharg = re.match(patternarg, arg1)
        if not matcharg:
            return await self.play_music_list(did, arg1)

        chinese_index = matcharg.groups()[0]
        list_name = matcharg.groups()[1]
        list_name = self._find_real_music_list_name(list_name)
        if list_name not in self.music_list:
            await self.do_tts(did, f"播放列表{list_name}不存在")
            return

        index = chinese_to_number(chinese_index)
        play_list = self.music_list[list_name]
        if 0 <= index - 1 < len(play_list):
            music_name = play_list[index - 1]
            self.log.info(f"即将播放 ${arg1} 里的第 ${index} 个: ${music_name}")
            await self.devices[did].play_music_list(list_name, music_name)
            return
        await self.do_tts(did, f"播放列表{list_name}中找不到第${index}个")

    # 播放
    async def play(self, did="", arg1="", **kwargs):
        parts = arg1.split("|")
        search_key = parts[0]
        name = parts[1] if len(parts) > 1 else search_key
        if not name:
            name = search_key

        # 语音播放会根据歌曲匹配更新当前播放列表
        return await self.do_play(
            did, name, search_key, exact=True, update_cur_list=True
        )

    # 搜索播放：会产生临时播放列表
    async def search_play(self, did="", arg1="", **kwargs):
        parts = arg1.split("|")
        search_key = parts[0]
        name = parts[1] if len(parts) > 1 else search_key
        if not name:
            name = search_key

        # 语音搜索播放会更新当前播放列表为临时播放列表
        return await self.do_play(
            did, name, search_key, exact=False, update_cur_list=False
        )

    # 在线播放：在线搜索、播放
    async def online_play(self, did="", arg1="", **kwargs):
        # 先推送默认【搜索中】音频，搜索到播放url后推送给小爱
        config = self.config
        if config and hasattr(config, "hostname") and hasattr(config, "public_port"):
            proxy_base = f"{config.hostname}:{config.public_port}"
        else:
            proxy_base = "http://192.168.31.241:8090"
        search_audio = proxy_base + "/static/search.mp3"
        proxy_base + "/static/silence.mp3"
        await self.play_url(self.get_cur_did(), search_audio)

        # TODO 添加一个定时器，4秒后触发

        # 获取搜索关键词
        parts = arg1.split("|")
        search_key = parts[0]
        name = parts[1] if len(parts) > 1 else search_key
        if not name:
            name = search_key
        self.log.info(f"搜索关键字{search_key},搜索歌名{name}")
        result = await self.search_music_online(search_key, name)
        # 搜索成功，则直接推送url播放
        if result.get("success", False):
            url = result.get("url", "")
            # 播放歌曲
            await self.devices[did].play_music(name, true_url=url)

    # 后台搜索播放
    async def do_play(
        self, did, name, search_key="", exact=False, update_cur_list=False
    ):
        return await self.devices[did].play(name, search_key, exact, update_cur_list)

    # 本地播放
    async def playlocal(self, did="", arg1="", **kwargs):
        return await self.devices[did].playlocal(arg1, update_cur_list=True)

    # 本地搜索播放
    async def search_playlocal(self, did="", arg1="", **kwargs):
        return await self.devices[did].playlocal(
            arg1, exact=False, update_cur_list=False
        )

    async def play_next(self, did="", **kwargs):
        return await self.devices[did].play_next()

    async def play_prev(self, did="", **kwargs):
        return await self.devices[did].play_prev()

    # 停止
    async def stop(self, did="", arg1="", **kwargs):
        return await self.devices[did].stop(arg1=arg1)

    # 定时关机
    async def stop_after_minute(self, did="", arg1=0, **kwargs):
        try:
            # 尝试阿拉伯数字转换中文数字
            minute = int(arg1)
        except (KeyError, ValueError):
            # 如果阿拉伯数字转换失败，尝试中文数字
            minute = chinese_to_number(str(arg1))
        return await self.devices[did].stop_after_minute(minute)

    # 添加歌曲到收藏列表
    async def add_to_favorites(self, did="", arg1="", **kwargs):
        name = arg1 if arg1 else self.playingmusic(did)
        self.log.info(f"add_to_favorites {name}")
        if not name:
            self.log.warning("当前没有在播放歌曲，添加歌曲到收藏列表失败")
            return

        self.play_list_add_music("收藏", [name])

    # 从收藏列表中移除
    async def del_from_favorites(self, did="", arg1="", **kwargs):
        name = arg1 if arg1 else self.playingmusic(did)
        self.log.info(f"del_from_favorites {name}")
        if not name:
            self.log.warning("当前没有在播放歌曲，从收藏列表中移除失败")
            return

        self.play_list_del_music("收藏", [name])

    # 更新每个设备的歌单
    def update_all_playlist(self):
        for device in self.devices.values():
            device.update_playlist()

    def get_custom_play_list(self):
        if self.custom_play_list is None:
            self.custom_play_list = {}
            if self.config.custom_play_list_json:
                self.custom_play_list = json.loads(self.config.custom_play_list_json)
        return self.custom_play_list

    def save_custom_play_list(self):
        custom_play_list = self.get_custom_play_list()
        self.refresh_custom_play_list()
        self.config.custom_play_list_json = json.dumps(
            custom_play_list, ensure_ascii=False
        )
        self.save_cur_config()

    # 新增歌单
    def play_list_add(self, name):
        custom_play_list = self.get_custom_play_list()
        if name in custom_play_list:
            return False
        custom_play_list[name] = []
        self.save_custom_play_list()
        return True

    # 移除歌单
    def play_list_del(self, name):
        custom_play_list = self.get_custom_play_list()
        if name not in custom_play_list:
            return False
        custom_play_list.pop(name)
        self.save_custom_play_list()
        return True

    # 修改歌单名字
    def play_list_update_name(self, oldname, newname):
        custom_play_list = self.get_custom_play_list()
        if oldname not in custom_play_list:
            self.log.info(f"旧歌单名字不存在 {oldname}")
            return False
        if newname in custom_play_list:
            self.log.info(f"新歌单名字已存在 {newname}")
            return False
        play_list = custom_play_list[oldname]
        custom_play_list.pop(oldname)
        custom_play_list[newname] = play_list
        self.save_custom_play_list()
        return True

    # 获取所有自定义歌单
    def get_play_list_names(self):
        custom_play_list = self.get_custom_play_list()
        return list(custom_play_list.keys())

    # 获取歌单中所有歌曲
    def play_list_musics(self, name):
        custom_play_list = self.get_custom_play_list()
        if name not in custom_play_list:
            return "歌单不存在", []
        play_list = custom_play_list[name]
        return "OK", play_list

    # 歌单更新歌曲
    def play_list_update_music(self, name, music_list):
        custom_play_list = self.get_custom_play_list()
        if name not in custom_play_list:
            # 歌单不存在则新建
            if not self.play_list_add(name):
                return False
        play_list = []
        for music_name in music_list:
            if (music_name in self.all_music) and (music_name not in play_list):
                play_list.append(music_name)
        # 直接覆盖
        custom_play_list[name] = play_list
        self.save_custom_play_list()
        return True

    # 歌单新增歌曲
    def play_list_add_music(self, name, music_list):
        custom_play_list = self.get_custom_play_list()
        if name not in custom_play_list:
            # 歌单不存在则新建
            if not self.play_list_add(name):
                return False
        play_list = custom_play_list[name]
        for music_name in music_list:
            if (music_name in self.all_music) and (music_name not in play_list):
                play_list.append(music_name)
        self.save_custom_play_list()
        return True

    # 歌单移除歌曲
    def play_list_del_music(self, name, music_list):
        custom_play_list = self.get_custom_play_list()
        if name not in custom_play_list:
            return False
        play_list = custom_play_list[name]
        for music_name in music_list:
            if music_name in play_list:
                play_list.remove(music_name)
        self.save_custom_play_list()
        return True

    # 获取音量
    async def get_volume(self, did="", **kwargs):
        return await self.devices[did].get_volume()

    # 3thdplay.html 的音量设置消息发送 需要配置文件加入自定义指令
    #  "user_key_word_dict": {
    # "音量": "set_myvolume",
    # "继续": "stop",
    # "大点音": "exec#setmyvolume(\"up\")",
    # "小点音": "exec#setmyvolume(\"down\")",

    async def set_myvolume(self, did="", arg1=0, **kwargs):
        if did not in self.devices:
            self.log.info(f"设备 did:{did} 不存在, 不能设置音量")
            return
        if arg1 == "up":
            await thdplay("up", "", self.thdtarget)

        elif arg1 == "down":
            await thdplay("down", "", self.thdtarget)
        else:
            volume = chinese_to_number(arg1)
            await thdplay("volume", str(volume), self.thdtarget)

    # 设置音量
    async def set_volume(self, did="", arg1=0, **kwargs):
        if did not in self.devices:
            self.log.info(f"设备 did:{did} 不存在, 不能设置音量")
            return
        volume = int(arg1)
        await thdplay("volume", str(volume), self.thdtarget)
        return await self.devices[did].set_volume(volume)

    # 搜索音乐
    def searchmusic(self, name):
        all_music_list = list(self.all_music.keys())
        search_list = fuzzyfinder(name, all_music_list, self._extra_index_search)
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
        cur_music = self.devices[did].get_cur_music()
        self.log.debug(f"playingmusic. cur_music:{cur_music}")
        return cur_music

    def get_offset_duration(self, did):
        return self.devices[did].get_offset_duration()

    # 当前是否正在播放歌曲
    def isplaying(self, did):
        return self.devices[did].isplaying()

    # 获取当前配置
    def getconfig(self):
        return self.config

    def try_init_setting(self):
        try:
            filename = self.config.getsettingfile()
            with open(filename, encoding="utf-8") as f:
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
        for did in self.config.devices.keys():
            deviceobj = self.devices.get(did)
            if deviceobj is not None:
                self.config.devices[did] = deviceobj.device
        data = asdict(self.config)
        self.do_saveconfig(data)
        self.log.info("save_cur_config ok")

    def update_config_from_setting(self, data):
        # 保存之前的 enable_file_watch 配置
        pre_efw = self.config.enable_file_watch
        # 自动赋值相同字段的配置
        self.config.update_config(data)

        self.init_config()
        debug_config = deepcopy_data_no_sensitive_info(self.config)
        self.log.info(f"update_config_from_setting ok. data:{debug_config}")

        joined_keywords = "/".join(self.config.key_match_order)
        self.log.info(f"语音控制已启动, 用【{joined_keywords}】开头来控制")
        self.log.debug(f"key_word_dict: {self.config.key_word_dict}")

        # 检查 enable_file_watch 配置是否发生变化
        now_efw = self.config.enable_file_watch
        if pre_efw != now_efw:
            self.log.info("配置更新：{}目录监控".format("开启" if now_efw else "关闭"))
            if now_efw:
                self.start_file_watch()
            else:
                self.stop_file_watch()

        # 重新加载计划任务
        self.crontab.reload_config(self)

    # 重新初始化
    async def reinit(self):
        for handler in self.log.handlers:
            handler.close()
        self.setup_logger()
        if self.session:
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
            self.log.warning(f"Execption {e}")
            # 重新初始化
            await self.xiaomusic.reinit()
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
        self._next_timer = None
        self._playing = False
        # 播放进度
        self._start_time = 0
        self._duration = 0
        self._paused_time = 0
        self._play_failed_cnt = 0

        self._play_list = []

        # 关机定时器
        self._stop_timer = None
        self._last_cmd = None
        self.update_playlist()

    @property
    def did(self):
        return self.device.did

    @property
    def hardware(self):
        return self.device.hardware

    def get_cur_music(self):
        return self.device.cur_music

    def get_offset_duration(self):
        duration = self._duration
        if not self.isplaying():
            return 0, duration
        offset = time.time() - self._start_time - self._paused_time
        return offset, duration

    async def play_music(self, name, true_url=None):
        return await self._playmusic(name, true_url=true_url)

    # 初始化播放列表
    def update_playlist(self, reorder=True):
        # 没有重置 list 且非初始化
        if self.device.cur_playlist == "临时搜索列表" and len(self._play_list) > 0:
            # 更新总播放列表，为了UI显示
            self.xiaomusic.music_list["临时搜索列表"] = copy.copy(self._play_list)
        elif (
            self.device.cur_playlist == "临时搜索列表" and len(self._play_list) == 0
        ) or (self.device.cur_playlist not in self.xiaomusic.music_list):
            self.device.cur_playlist = "全部"
        else:
            pass  # 指定了已知的播放列表名称

        list_name = self.device.cur_playlist
        self._play_list = copy.copy(self.xiaomusic.music_list[list_name])

        if reorder:
            if self.device.play_type == PLAY_TYPE_RND:
                random.shuffle(self._play_list)
                self.log.info(
                    f"随机打乱 {list_name} {list2str(self._play_list, self.config.verbose)}"
                )
            else:
                self._play_list.sort(key=custom_sort_key)
                self.log.info(
                    f"没打乱 {list_name} {list2str(self._play_list, self.config.verbose)}"
                )
        else:
            self.log.info(
                f"更新 {list_name} {list2str(self._play_list, self.config.verbose)}"
            )

    # 播放歌曲
    async def play(self, name="", search_key="", exact=True, update_cur_list=False):
        self._last_cmd = "play"
        return await self._play(
            name=name,
            search_key=search_key,
            exact=exact,
            update_cur_list=update_cur_list,
        )

    async def _play(self, name="", search_key="", exact=True, update_cur_list=False):
        if search_key == "" and name == "":
            if self.check_play_next():
                await self._play_next()
                return
            else:
                name = self.get_cur_music()
        self.log.info(f"play. search_key:{search_key} name:{name}: exact:{exact}")

        # 本地歌曲不存在时下载
        if exact:
            names = self.xiaomusic.find_real_music_name(name, n=1)
        else:
            names = self.xiaomusic.find_real_music_name(
                name, n=self.config.search_music_count
            )
        if len(names) > 0:
            if not exact:
                if len(names) > 1:  # 大于一首歌才更新
                    self._play_list = names
                    self.device.cur_playlist = "临时搜索列表"
                    self.update_playlist()
                else:  # 只有一首歌，append
                    self._play_list = self._play_list + names
                    self.device.cur_playlist = "临时搜索列表"
                    self.update_playlist(reorder=False)
            name = names[0]
            if update_cur_list and (name not in self._play_list):
                # 根据当前歌曲匹配歌曲列表
                self.device.cur_playlist = self.find_cur_playlist(name)
                self.update_playlist()
            self.log.debug(
                f"当前播放列表为：{list2str(self._play_list, self.config.verbose)}"
            )
        elif not self.xiaomusic.is_music_exist(name):
            if self.config.disable_download:
                await self.do_tts(f"本地不存在歌曲{name}")
                return
            else:
                # 如果插件播放失败，则执行下载流程
                await self.download(search_key, name)
                # 把文件插入到播放列表里
                await self.add_download_music(name)
                await self._playmusic(name)
        else:
            # 本地存在歌曲，直接播放
            await self._playmusic(name)

    # 下一首
    async def play_next(self):
        return await self._play_next()

    async def _play_next(self):
        self.log.info("开始播放下一首")
        name = self.get_cur_music()
        if (
            self.device.play_type == PLAY_TYPE_ALL
            or self.device.play_type == PLAY_TYPE_RND
            or self.device.play_type == PLAY_TYPE_SEQ
            or name == ""
            or (
                (name not in self._play_list) and self.device.play_type != PLAY_TYPE_ONE
            )
        ):
            name = self.get_next_music()
        self.log.info(f"_play_next. name:{name}, cur_music:{self.get_cur_music()}")
        if name == "":
            # await self.do_tts("本地没有歌曲")
            return
        await self._play(name, exact=True)

    # 上一首
    async def play_prev(self):
        return await self._play_prev()

    async def _play_prev(self):
        self.log.info("开始播放上一首")
        name = self.get_cur_music()
        if (
            self.device.play_type == PLAY_TYPE_ALL
            or self.device.play_type == PLAY_TYPE_RND
            or name == ""
            or (name not in self._play_list)
        ):
            name = self.get_prev_music()
        self.log.info(f"_play_prev. name:{name}, cur_music:{self.get_cur_music()}")
        if name == "":
            await self.do_tts("本地没有歌曲")
            return
        await self._play(name, exact=True)

    # 播放本地歌曲
    async def playlocal(self, name, exact=True, update_cur_list=False):
        self._last_cmd = "playlocal"
        if name == "":
            if self.check_play_next():
                await self._play_next()
                return
            else:
                name = self.get_cur_music()

        self.log.info(f"playlocal. name:{name}")

        # 本地歌曲不存在时下载
        if exact:
            names = self.xiaomusic.find_real_music_name(name, n=1)
        else:
            names = self.xiaomusic.find_real_music_name(
                name, n=self.config.search_music_count
            )
        if len(names) > 0:
            if not exact:
                if len(names) > 1:  # 大于一首歌才更新
                    self._play_list = names
                    self.device.cur_playlist = "临时搜索列表"
                    self.update_playlist()
                else:  # 只有一首歌，append
                    self._play_list = self._play_list + names
                    self.device.cur_playlist = "临时搜索列表"
                    self.update_playlist(reorder=False)
            name = names[0]
            if update_cur_list:
                # 根据当前歌曲匹配歌曲列表
                self.device.cur_playlist = self.find_cur_playlist(name)
                self.update_playlist()
            self.log.debug(
                f"当前播放列表为：{list2str(self._play_list, self.config.verbose)}"
            )
        elif not self.xiaomusic.is_music_exist(name):
            await self.do_tts(f"本地不存在歌曲{name}")
            return
        await self._playmusic(name)

    async def _playmusic(self, name, true_url=None):
        # 取消组内所有的下一首歌曲的定时器
        self.cancel_group_next_timer()

        self._playing = True
        self.device.cur_music = name
        self.device.playlist2music[self.device.cur_playlist] = name

        self.log.info(f"cur_music {self.get_cur_music()}")
        sec, url = await self.xiaomusic.get_music_sec_url(name, true_url)
        await self.group_force_stop_xiaoai()
        self.log.info(f"播放 {url}")
        # 有3方设备打开 /static/3thplay.html 通过socketio连接返回true 忽律小爱音箱的播放
        online = await thdplay("play", url, self.xiaomusic.thdtarget)
        self.log.error(f"IS online {online}")

        if not online:
            results = await self.group_player_play(url, name)
            if all(ele is None for ele in results):
                self.log.info(f"播放 {name} 失败. 失败次数: {self._play_failed_cnt}")
                await asyncio.sleep(1)
                if (
                    self.isplaying()
                    and self._last_cmd != "stop"
                    and self._play_failed_cnt < 10
                ):
                    self._play_failed_cnt = self._play_failed_cnt + 1
                    await self._play_next()
                return
        # 重置播放失败次数
        self._play_failed_cnt = 0

        self.log.info(f"【{name}】已经开始播放了")
        await self.xiaomusic.analytics.send_play_event(name, sec, self.hardware)

        # 设置下一首歌曲的播放定时器
        if sec <= 1:
            self.log.info(f"【{name}】不会设置下一首歌的定时器")
            return
        sec = sec + self.config.delay_sec
        self._start_time = time.time()
        self._duration = sec
        self._paused_time = 0
        await self.set_next_music_timeout(sec)
        self.xiaomusic.save_cur_config()

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
        self.log.info(f"do_tts ok. cur_music:{self.get_cur_music()}")
        await self.check_replay()

    async def force_stop_xiaoai(self, device_id):
        try:
            ret = await self.xiaomusic.mina_service.player_pause(device_id)
            self.log.info(
                f"force_stop_xiaoai player_pause device_id:{device_id} ret:{ret}"
            )
            await self.stop_if_xiaoai_is_playing(device_id)
        except Exception as e:
            self.log.warning(f"Execption {e}")

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
            "--audio-quality",
            "0",
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

        if self.config.enable_yt_dlp_cookies:
            sbp_args += ("--cookies", f"{self.config.yt_dlp_cookies_path}")

        if self.config.loudnorm:
            sbp_args += ("--postprocessor-args", f"-af {self.config.loudnorm}")

        cmd = " ".join(sbp_args)
        self.log.info(f"download cmd: {cmd}")
        self._download_proc = await asyncio.create_subprocess_exec(*sbp_args)
        await self.do_tts(f"正在下载歌曲{search_key}")
        self.log.info(f"正在下载中 {search_key} {name}")
        await self._download_proc.wait()
        # 下载完成后，修改文件权限
        file_path = os.path.join(self.download_path, f"{name}.mp3")
        chmodfile(file_path)

    # 继续播放被打断的歌曲
    async def check_replay(self):
        if self.isplaying() and not self.isdownloading():
            if not self.config.continue_play:
                # 重新播放歌曲
                self.log.info("现在重新播放歌曲")
                await self._play()
            else:
                self.log.info(
                    f"继续播放歌曲. self.config.continue_play:{self.config.continue_play}"
                )
        else:
            self.log.info(
                f"不会继续播放歌曲. isplaying:{self.isplaying()} isdownloading:{self.isdownloading()}"
            )

    # 当前是否正在播放歌曲
    def isplaying(self):
        return self._playing

    # 把下载的音乐加入播放列表
    async def add_download_music(self, name):
        filepath = os.path.join(self.download_path, f"{name}.mp3")
        self.xiaomusic.all_music[name] = filepath
        # 应该很快，阻塞运行
        await self.xiaomusic._gen_all_music_tag({name: filepath})
        if name not in self._play_list:
            self._play_list.append(name)
            self.log.info(f"add_download_music add_music {name}")
            self.log.debug(self._play_list)

    def get_music(self, direction="next"):
        play_list_len = len(self._play_list)
        if play_list_len == 0:
            self.log.warning("当前播放列表没有歌曲")
            return ""
        index = 0
        try:
            index = self._play_list.index(self.get_cur_music())
        except ValueError:
            pass

        if play_list_len == 1:
            new_index = index  # 当只有一首歌曲时保持当前索引不变
        else:
            if direction == "next":
                new_index = index + 1
                if (
                    self.device.play_type == PLAY_TYPE_SEQ
                    and new_index >= play_list_len
                ):
                    self.log.info("顺序播放结束")
                    return ""
                if new_index >= play_list_len:
                    new_index = 0
            elif direction == "prev":
                new_index = index - 1
                if new_index < 0:
                    new_index = play_list_len - 1
            else:
                self.log.error("无效的方向参数")
                return ""

        name = self._play_list[new_index]
        if not self.xiaomusic.is_music_exist(name):
            self._play_list.pop(new_index)
            self.log.info(f"pop not exist music: {name}")
            return self.get_music(direction)
        return name

    # 获取下一首
    def get_next_music(self):
        return self.get_music(direction="next")

    # 获取上一首
    def get_prev_music(self):
        return self.get_music(direction="prev")

    # 判断是否播放下一首歌曲
    def check_play_next(self):
        # 当前歌曲不在当前播放列表
        if self.get_cur_music() not in self._play_list:
            self.log.info(f"当前歌曲 {self.get_cur_music()} 不在当前播放列表")
            return True

        # 当前没我在播放的歌曲
        if self.get_cur_music() == "":
            self.log.info("当前没我在播放的歌曲")
            return True
        else:
            # 当前播放的歌曲不存在了
            if not self.xiaomusic.is_music_exist(self.get_cur_music()):
                self.log.info(f"当前播放的歌曲 {self.get_cur_music()} 不存在了")
                return True
        return False

    async def text_to_speech(self, value):
        try:
            # 有 tts command 优先使用 tts command 说话
            if self.hardware in TTS_COMMAND:
                tts_cmd = TTS_COMMAND[self.hardware]
                self.log.info("Call MiIOService tts.")
                value = value.replace(" ", ",")  # 不能有空格
                await miio_command(
                    self.xiaomusic.miio_service,
                    self.did,
                    f"{tts_cmd} {value}",
                )
            else:
                self.log.debug("Call MiNAService tts.")
                await self.xiaomusic.mina_service.text_to_speech(self.device_id, value)
        except Exception as e:
            self.log.exception(f"Execption {e}")

    # 同一组设备播放
    async def group_player_play(self, url, name=""):
        device_id_list = self.xiaomusic.get_group_device_id_list(self.group_name)
        tasks = [
            self.play_one_url(device_id, url, name) for device_id in device_id_list
        ]
        results = await asyncio.gather(*tasks)
        self.log.info(f"group_player_play {url} {device_id_list} {results}")
        return results

    async def play_one_url(self, device_id, url, name):
        ret = None
        try:
            audio_id = await self._get_audio_id(name)
            if self.config.continue_play:
                ret = await self.xiaomusic.mina_service.play_by_music_url(
                    device_id, url, _type=1, audio_id=audio_id
                )
                self.log.info(
                    f"play_one_url continue_play device_id:{device_id} ret:{ret} url:{url} audio_id:{audio_id}"
                )
            elif self.config.use_music_api or (
                self.hardware in NEED_USE_PLAY_MUSIC_API
            ):
                ret = await self.xiaomusic.mina_service.play_by_music_url(
                    device_id, url, audio_id=audio_id
                )
                self.log.info(
                    f"play_one_url play_by_music_url device_id:{device_id} ret:{ret} url:{url} audio_id:{audio_id}"
                )
            else:
                ret = await self.xiaomusic.mina_service.play_by_url(device_id, url)
                self.log.info(
                    f"play_one_url play_by_url device_id:{device_id} ret:{ret} url:{url}"
                )
        except Exception as e:
            self.log.exception(f"Execption {e}")
        return ret

    async def _get_audio_id(self, name):
        audio_id = self.config.use_music_audio_id or "1582971365183456177"
        if not (self.config.use_music_api or self.config.continue_play):
            return str(audio_id)
        try:
            params = {
                "query": name,
                "queryType": 1,
                "offset": 0,
                "count": 6,
                "timestamp": int(time.time_ns() / 1000),
            }
            response = await self.xiaomusic.mina_service.mina_request(
                "/music/search", params
            )
            for song in response["data"]["songList"]:
                if song["originName"] == "QQ音乐":
                    audio_id = song["audioID"]
                    break
            # 没找到QQ音乐的歌曲，取第一个
            if audio_id == 1582971365183456177:
                audio_id = response["data"]["songList"][0]["audioID"]
            self.log.debug(f"_get_audio_id. name: {name} songId:{audio_id}")
        except Exception as e:
            self.log.error(f"_get_audio_id {e}")
        return str(audio_id)

    # 重置计时器
    async def reset_timer_when_answer(self, answer_length):
        if not (self.isplaying() and self.config.continue_play):
            return
        pause_time = answer_length / 5 + 1
        offset, duration = self.get_offset_duration()
        self._paused_time += pause_time
        new_time = duration - offset + pause_time
        await self.set_next_music_timeout(new_time)
        self.log.info(
            f"reset_timer 延长定时器. answer_length:{answer_length} pause_time:{pause_time}"
        )

    # 设置下一首歌曲的播放定时器
    async def set_next_music_timeout(self, sec):
        self.cancel_next_timer()

        async def _do_next():
            await asyncio.sleep(sec)
            try:
                self.log.info("定时器时间到了")
                if self._next_timer:
                    self._next_timer = None
                    if self.device.play_type == PLAY_TYPE_SIN:
                        self.log.info("单曲播放不继续播放下一首")
                        await self.stop(arg1="notts")
                    else:
                        await self._play_next()
                else:
                    self.log.info("定时器时间到了但是不见了")

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
        volume = 0
        try:
            playing_info = await self.xiaomusic.mina_service.player_get_status(
                self.device_id
            )
            self.log.info(f"get_volume. playing_info:{playing_info}")
            volume = json.loads(playing_info.get("data", {}).get("info", "{}")).get(
                "volume", 0
            )
        except Exception as e:
            self.log.warning(f"Execption {e}")
        volume = int(volume)
        self.log.info("get_volume. volume:%d", volume)
        return volume

    async def set_play_type(self, play_type, dotts=True):
        self.device.play_type = play_type
        self.xiaomusic.save_cur_config()
        if dotts:
            tts = self.config.get_play_type_tts(play_type)
            await self.do_tts(tts)
        self.update_playlist()

    async def play_music_list(self, list_name, music_name):
        self._last_cmd = "play_music_list"
        self.device.cur_playlist = list_name
        self.update_playlist()
        if not music_name:
            music_name = self.device.playlist2music[list_name]
        self.log.info(f"开始播放列表{list_name} {music_name}")
        await self._play(music_name, exact=True)

    async def stop(self, arg1=""):
        self._last_cmd = "stop"
        self._playing = False
        if arg1 != "notts":
            await self.do_tts(self.config.stop_tts_msg)
        await asyncio.sleep(3)  # 等它说完
        # 取消组内所有的下一首歌曲的定时器
        await thdplay("stop", "", self.xiaomusic.thdtarget)
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
        self.log.info("cancel_next_timer")
        if self._next_timer:
            self._next_timer.cancel()
            self.log.info(f"下一曲定时器已取消 {self.device_id}")
            self._next_timer = None
        else:
            self.log.info("下一曲定时器不见了")

    def cancel_group_next_timer(self):
        devices = self.xiaomusic.get_group_devices(self.group_name)
        self.log.info(f"cancel_group_next_timer {devices}")
        for device in devices.values():
            device.cancel_next_timer()

    def get_cur_play_list(self):
        return self.device.cur_playlist

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

    # 根据当前歌曲匹配歌曲列表
    def find_cur_playlist(self, name):
        # 匹配顺序：
        # 1. 收藏
        # 2. 最近新增
        # 3. 排除（全部,所有歌曲,所有电台,临时搜索列表）
        # 4. 所有歌曲
        # 5. 所有电台
        # 6. 全部
        if name in self.xiaomusic.music_list.get("收藏", []):
            return "收藏"
        if name in self.xiaomusic.music_list.get("最近新增", []):
            return "最近新增"
        for list_name, play_list in self.xiaomusic.music_list.items():
            if (list_name not in ["全部", "所有歌曲", "所有电台", "临时搜索列表"]) and (
                name in play_list
            ):
                return list_name
        if name in self.xiaomusic.music_list.get("所有歌曲", []):
            return "所有歌曲"
        if name in self.xiaomusic.music_list.get("所有电台", []):
            return "所有电台"
        return "全部"


# 目录监控类，使用延迟防抖，仅监控音乐文件
class XiaoMusicPathWatch(FileSystemEventHandler):
    def __init__(self, callback, debounce_delay, loop):
        self.callback = callback
        self.debounce_delay = debounce_delay
        self.loop = loop
        self._debounce_handle = None

    def on_any_event(self, event):
        # 只处理文件的创建、删除和移动事件
        if not isinstance(event, FileCreatedEvent | FileDeletedEvent | FileMovedEvent):
            return

        if event.is_directory:
            return  # 忽略目录事件

        # 处理文件事件
        src_ext = os.path.splitext(event.src_path)[1].lower()
        # 处理移动事件的目标路径
        if hasattr(event, "dest_path"):
            dest_ext = os.path.splitext(event.dest_path)[1].lower()
            if dest_ext in SUPPORT_MUSIC_TYPE:
                self.schedule_callback()
                return

        if src_ext in SUPPORT_MUSIC_TYPE:
            self.schedule_callback()

    def schedule_callback(self):
        def _execute_callback():
            self._debounce_handle = None
            self.callback()

        if self._debounce_handle:
            self._debounce_handle.cancel()
        self._debounce_handle = self.loop.call_later(
            self.debounce_delay, _execute_callback
        )

    # ===================================================================
