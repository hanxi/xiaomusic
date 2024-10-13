#!/usr/bin/env python3
import asyncio
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
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout
from miservice import MiAccount, MiIOService, MiNAService, miio_command

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
    PLAY_TYPE_ALL,
    PLAY_TYPE_ONE,
    PLAY_TYPE_RND,
    PLAY_TYPE_TTS,
    SUPPORT_MUSIC_TYPE,
)
from xiaomusic.crontab import Crontab
from xiaomusic.plugin import PluginManager
from xiaomusic.utils import (
    Metadata,
    chinese_to_number,
    custom_sort_key,
    deepcopy_data_no_sensitive_info,
    extract_audio_metadata,
    find_best_match,
    fuzzyfinder,
    get_local_music_duration,
    get_web_music_duration,
    list2str,
    parse_cookie_string,
    parse_str_to_dict,
    traverse_music_directory,
    try_add_access_control_param,
)


class XiaoMusic:
    def __init__(self, config: Config):
        self.config = config

        self.mi_token_home = Path.home() / ".mi.token"
        self.last_timestamp = {}  # key为 did. timestamp last call mi speaker
        self.last_record = None
        self.cookie_jar = None
        self.mina_service = None
        self.miio_service = None
        self.polling_event = asyncio.Event()
        self.new_record_event = asyncio.Event()

        self.all_music = {}
        self._all_radio = {}  # 电台列表
        self.music_list = {}  # 播放列表 key 为目录名, value 为 play_list
        self.devices = {}  # key 为 did
        self.running_task = []
        self.all_music_tags = {}  # 歌曲额外信息
        self._tag_generation_task = False
        self._extra_index_search = {}

        # 初始化配置
        self.init_config()

        # 初始化日志
        self.setup_logger()

        # 计划任务
        self.crontab = Crontab(self.log)

        # 尝试从设置里加载配置
        self.try_init_setting()

        # 启动时重新生成一次播放列表
        self._gen_all_music_list()

        # 初始化插件
        self.plugin_manager = PluginManager(self)

        # 更新设备列表
        self.update_devices()

        # 启动统计
        self.analytics = Analytics(self.log)

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
        if not self.hostname.startswith(("http://", "https://")):
            self.hostname = f"http://{self.hostname}"  # 默认 http
        self.port = self.config.port
        self.public_port = self.config.public_port
        if self.public_port == 0:
            self.public_port = self.port

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
                    if hardware in GET_ASK_BY_MINA or self.config.get_ask_by_mina:
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
        self.miio_service = MiIOService(account)

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

    async def get_latest_ask_by_mina(self, device_id):
        try:
            did = self.get_did(device_id)
            response = await self.mina_service.ubus_request(
                device_id, "nlp_result_get", "mibrain", {}
            )
            self.log.debug(
                f"get_latest_ask_by_mina device_id:{device_id} did:{did} response:{response}"
            )
            if d := response.get("data", {}).get("info", {}):
                result = json.loads(d).get("result", [{}])
                if result and len(result) > 0 and result[0].get("nlp"):
                    answers = (
                        json.loads(result[0]["nlp"])
                        .get("response", {})
                        .get("answer", [{}])
                    )
                    if answers:
                        query = answers[0].get("intention", {}).get("query", "").strip()
                        timestamp = result[0]["timestamp"] * 1000
                        answer = answers[0].get("content", {}).get("to_speak")
                        last_record = {
                            "time": timestamp,
                            "did": did,
                            "query": query,
                            "answer": answer,
                        }
                        self._check_last_query(last_record)
        except Exception as e:
            self.log.exception(f"get_latest_ask_by_mina {e}")
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
        self.log.debug(f"获取到最后一条对话记录：{query} {timestamp}")

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
            duration, url = await get_web_music_duration(
                url, self.config.ffmpeg_location
            )
            sec = math.ceil(duration)
            self.log.info(f"网络歌曲 {name} : {origin_url} {url} 的时长 {sec} 秒")
        else:
            filename = self.get_filename(name)
            self.log.info(f"get_music_sec_url. name:{name} filename:{filename}")
            duration = await get_local_music_duration(
                filename, self.config.ffmpeg_location
            )
            sec = math.ceil(duration)
            self.log.info(f"本地歌曲 {name} : {filename} {url} 的时长 {sec} 秒")

        if sec <= 0:
            self.log.warning(f"获取歌曲时长失败 {name} {url}")
        return sec, url

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

    def get_music_url(self, name):
        if self.is_web_music(name):
            url = self.all_music[name]
            self.log.info(f"get_music_url web music. name:{name}, url:{url}")
            return url

        filename = self.get_filename(name)

        # 构造音乐文件的URL
        if filename.startswith(self.config.music_path):
            filename = filename[len(self.config.music_path) :]
        filename = filename.replace("\\", "/")
        if filename.startswith("/"):
            filename = filename[1:]

        self.log.info(f"get_music_url local music. name:{name}, filename:{filename}")

        encoded_name = urllib.parse.quote(filename)
        return try_add_access_control_param(
            self.config,
            f"{self.hostname}:{self.public_port}/music/{encoded_name}",
        )

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
        for name, file_or_url in only_items.items():
            await asyncio.sleep(0.001)
            if name not in all_music_tags:
                try:
                    if self.is_web_music(name):
                        # TODO: 网络歌曲获取歌曲额外信息
                        pass
                    elif os.path.exists(file_or_url):
                        all_music_tags[name] = extract_audio_metadata(
                            file_or_url, self.config.picture_cache_path
                        )
                    else:
                        self.log.info(f"{name}/{file_or_url} 无法更新 tag")
                except BaseException as e:
                    self.log.exception(f"{e} {file_or_url} error {type(file_or_url)}!")
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

        self.music_list = OrderedDict({"临时搜索列表": []})
        # 全部，所有，自定义歌单（收藏）
        self.music_list["全部"] = list(self.all_music.keys())
        self.music_list["所有歌曲"] = [
            name for name in self.all_music.keys() if name not in self._all_radio
        ]
        self._append_custom_play_list()

        # 网络歌单
        try:
            # NOTE: 函数内会更新 self.all_music, self._music_list；重建 self._all_radio
            self._append_music_list()
        except Exception as e:
            self.log.exception(f"Execption {e}")

        # 文件夹歌单
        for dir_name, musics in all_music_by_dir.items():
            self.music_list[dir_name] = list(musics.keys())
            # self.log.debug("dir_name:%s, list:%s", dir_name, self.music_list[dir_name])

        # 歌单排序
        for _, play_list in self.music_list.items():
            play_list.sort(key=custom_sort_key)

        # 更新每个设备的歌单
        for device in self.devices.values():
            device.update_playlist()

        # 重建索引
        self._extra_index_search = {}
        for k, v in self.all_music.items():
            # 如果不是 url，则增加索引
            if not (v.startswith("http") or v.startswith("https")):
                self._extra_index_search[v] = k

        # all_music 更新，重建 tag
        self.try_gen_all_music_tag()

    def _append_custom_play_list(self):
        if not self.config.custom_play_list_json:
            return

        try:
            custom_play_list = json.loads(self.config.custom_play_list_json)
            self.music_list["收藏"] = list(custom_play_list["收藏"])
        except Exception as e:
            self.log.exception(f"Execption {e}")

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

    async def analytics_task_daily(self):
        while True:
            await self.analytics.send_daily_event()
            await asyncio.sleep(3600)

    async def run_forever(self):
        self.try_gen_all_music_tag()  # 事件循环开始后调用一次
        self.crontab.start()
        await self.analytics.send_startup_event()
        analytics_task = asyncio.create_task(self.analytics_task_daily())
        assert (
            analytics_task is not None
        )  # to keep the reference to task, do not remove this
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
            return (opvalue, oparg)
        self.log.info(f"未匹配到指令 {query} {ctrl_panel}")
        return (None, None)

    def find_real_music_name(self, name, n=100):
        if not self.config.enable_fuzzy_match:
            self.log.debug("没开启模糊匹配")
            return name

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
        self.log.info("gen_music_list ok")

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

        list_name = self._find_real_music_list_name(list_name)
        if list_name not in self.music_list:
            await self.do_tts(did, f"播放列表{list_name}不存在")
            return

        music_name = ""
        if len(parts) > 1:
            music_name = parts[1]
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
        if name == "":
            name = search_key

        return await self.devices[did].play(name, search_key)

    # 本地播放
    async def playlocal(self, did="", arg1="", **kwargs):
        return await self.devices[did].playlocal(arg1)

    async def play_next(self, did="", **kwargs):
        return await self.devices[did].play_next()

    async def play_prev(self, did="", **kwargs):
        return await self.devices[did].play_prev()

    # 停止
    async def stop(self, did="", arg1="", **kwargs):
        return await self.devices[did].stop(arg1=arg1)

    # 定时关机
    async def stop_after_minute(self, did="", arg1=0, **kwargs):
        minute = int(arg1)
        return await self.devices[did].stop_after_minute(minute)

    # 添加歌曲到收藏列表
    async def add_to_favorites(self, did="", arg1="", **kwargs):
        name = arg1 if arg1 else self.playingmusic(did)
        if not name:
            return

        favorites = self.music_list.get("收藏", [])
        if name in favorites:
            return

        favorites.append(name)
        self.save_favorites(favorites)

    # 从收藏列表中移除
    async def del_from_favorites(self, did="", arg1="", **kwargs):
        name = arg1 if arg1 else self.playingmusic(did)
        if not name:
            return

        favorites = self.music_list.get("收藏", [])
        if name not in favorites:
            return

        favorites.remove(name)
        self.save_favorites(favorites)

    def save_favorites(self, favorites):
        self.music_list["收藏"] = favorites
        custom_play_list = {}
        if self.config.custom_play_list_json:
            custom_play_list = json.loads(self.config.custom_play_list_json)
        custom_play_list["收藏"] = favorites
        self.config.custom_play_list_json = json.dumps(
            custom_play_list, ensure_ascii=False
        )
        self.save_cur_config()

        # 更新每个设备的歌单
        for device in self.devices.values():
            device.update_playlist()

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
        # 自动赋值相同字段的配置
        self.config.update_config(data)

        self.init_config()
        debug_config = deepcopy_data_no_sensitive_info(self.config)
        self.log.info(f"update_config_from_setting ok. data:{debug_config}")

        joined_keywords = "/".join(self.config.key_match_order)
        self.log.info(f"语音控制已启动, 用【{joined_keywords}】开头来控制")
        self.log.debug(f"key_word_dict: {self.config.key_word_dict}")

        # 重新加载计划任务
        self.crontab.reload_config(self)

    # 重新初始化
    async def reinit(self, **kwargs):
        for handler in self.log.handlers:
            handler.close()
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
        self._next_timer = None
        self._timeout = 0
        self._playing = False
        # 播放进度
        self._start_time = 0
        self._duration = 0
        self._paused_time = 0

        self._play_list = []

        # 关机定时器
        self._stop_timer = None
        self._last_cmd = None
        self.update_playlist()

    @property
    def did(self):
        return self.xiaomusic.device_id_did[self.device_id]

    def get_cur_music(self):
        return self.device.cur_music

    def get_offset_duration(self):
        if not self.isplaying():
            return -1, -1
        offset = time.time() - self._start_time - self._paused_time
        duration = self._duration
        return offset, duration

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
                self._play_list = sorted(self._play_list)
                self.log.info(
                    f"没打乱 {list_name} {list2str(self._play_list, self.config.verbose)}"
                )
        else:
            self.log.info(
                f"更新 {list_name} {list2str(self._play_list, self.config.verbose)}"
            )

    # 播放歌曲
    async def play(self, name="", search_key=""):
        self._last_cmd = "play"
        return await self._play(name=name, search_key=search_key, update_cur=True)

    async def _play(self, name="", search_key="", exact=False, update_cur=False):
        if search_key == "" and name == "":
            if self.check_play_next():
                await self._play_next()
                return
            else:
                name = self.get_cur_music()
        self.log.info(f"play. search_key:{search_key} name:{name}")

        # 本地歌曲不存在时下载
        if exact:
            names = self.xiaomusic.find_real_music_name(name, n=1)
        else:
            names = self.xiaomusic.find_real_music_name(name)
        if len(names) > 0:
            if update_cur and len(names) > 1:  # 大于一首歌才更新
                self._play_list = names
                self.device.cur_playlist = "临时搜索列表"
                self.update_playlist()
            elif update_cur:  # 只有一首歌，append
                self._play_list = self._play_list + names
                self.device.cur_playlist = "临时搜索列表"
                self.update_playlist(reorder=False)
            name = names[0]
            self.log.debug(
                f"当前播放列表为：{list2str(self._play_list, self.config.verbose)}"
            )
        elif not self.xiaomusic.is_music_exist(name):
            if self.config.disable_download:
                await self.do_tts(f"本地不存在歌曲{name}")
                return
            await self.download(search_key, name)
            self.log.info(f"正在下载中 {search_key} {name}")
            await self._download_proc.wait()
            # 把文件插入到播放列表里
            await self.add_download_music(name)
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
            or name == ""
            or (
                (name not in self._play_list) and self.device.play_type != PLAY_TYPE_ONE
            )
        ):
            name = self.get_next_music()
        self.log.info(f"_play_next. name:{name}, cur_music:{self.get_cur_music()}")
        if name == "":
            await self.do_tts("本地没有歌曲")
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
    async def playlocal(self, name):
        self._last_cmd = "playlocal"
        if name == "":
            if self.check_play_next():
                await self._play_next()
                return
            else:
                name = self.get_cur_music()

        self.log.info(f"playlocal. name:{name}")

        # 本地歌曲不存在时下载
        names = self.xiaomusic.find_real_music_name(name)
        if len(names) > 0:
            if len(names) > 1:  # 大于一首歌才更新
                self._play_list = names
                self.device.cur_playlist = "临时搜索列表"
                self.update_playlist()
            else:  # 只有一首歌，append
                self._play_list = self._play_list + names
                self.device.cur_playlist = "临时搜索列表"
                self.update_playlist(reorder=False)
            name = names[0]
            self.log.debug(
                f"当前播放列表为：{list2str(self._play_list, self.config.verbose)}"
            )
        elif not self.xiaomusic.is_music_exist(name):
            await self.do_tts(f"本地不存在歌曲{name}")
            return
        await self._playmusic(name)

    async def _playmusic(self, name):
        # 取消组内所有的下一首歌曲的定时器
        self.cancel_group_next_timer()

        self._playing = True
        self.device.cur_music = name

        self.log.info(f"cur_music {self.get_cur_music()}")
        sec, url = await self.xiaomusic.get_music_sec_url(name)
        await self.group_force_stop_xiaoai()
        self.log.info(f"播放 {url}")
        results = await self.group_player_play(url, name)
        if all(ele is None for ele in results):
            self.log.info(f"播放 {name} 失败")
            await asyncio.sleep(1)
            if self.isplaying() and self._last_cmd != "stop":
                await self._play_next()
            return

        self.log.info(f"【{name}】已经开始播放了")
        await self.xiaomusic.analytics.send_play_event(name, sec)

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

        if self.config.enable_yt_dlp_cookies:
            sbp_args += ("--cookies", f"{self.config.yt_dlp_cookies_path}")

        cmd = " ".join(sbp_args)
        self.log.info(f"download cmd: {cmd}")
        self._download_proc = await asyncio.create_subprocess_exec(*sbp_args)
        await self.do_tts(f"正在下载歌曲{search_key}")

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
            if not self.config.miio_tts_command:
                self.log.debug("Call MiNAService tts.")
                await self.xiaomusic.mina_service.text_to_speech(self.device_id, value)
            else:
                self.log.debug("Call MiIOService tts.")
                value = value.replace(" ", ",")  # 不能有空格
                await miio_command(
                    self.xiaomusic.miio_service,
                    self.did,
                    f"{self.config.miio_tts_command} {value}",
                )
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
            elif self.config.use_music_api:
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
        audio_id = 1582971365183456177
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
        self.update_playlist()

    async def play_music_list(self, list_name, music_name):
        self._last_cmd = "play_music_list"
        self.device.cur_playlist = list_name
        self.update_playlist()
        self.log.info(f"开始播放列表{list_name}")
        await self._play(music_name, exact=True)

    async def stop(self, arg1=""):
        self._last_cmd = "stop"
        self._playing = False
        if arg1 != "notts":
            await self.do_tts(self.config.stop_tts_msg)
        await asyncio.sleep(3)  # 等它说完
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
