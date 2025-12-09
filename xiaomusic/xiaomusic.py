#!/usr/bin/env python3
import asyncio
import logging
import os
import re
from logging.handlers import RotatingFileHandler

from xiaomusic import __version__
from xiaomusic.analytics import Analytics
from xiaomusic.auth import AuthManager
from xiaomusic.command_handler import CommandHandler
from xiaomusic.config import Config
from xiaomusic.config_manager import ConfigManager
from xiaomusic.const import (
    PLAY_TYPE_ALL,
    PLAY_TYPE_ONE,
    PLAY_TYPE_RND,
    PLAY_TYPE_SEQ,
    PLAY_TYPE_SIN,
)
from xiaomusic.conversation import ConversationPoller
from xiaomusic.crontab import Crontab
from xiaomusic.device_manager import DeviceManager
from xiaomusic.events import CONFIG_CHANGED, DEVICE_CONFIG_CHANGED, EventBus
from xiaomusic.file_watcher import FileWatcherManager
from xiaomusic.music_library import MusicLibrary
from xiaomusic.music_url import MusicUrlHandler
from xiaomusic.online_music import OnlineMusicService
from xiaomusic.plugin import PluginManager
from xiaomusic.utils.network_utils import downloadfile
from xiaomusic.utils.system_utils import deepcopy_data_no_sensitive_info
from xiaomusic.utils.text_utils import chinese_to_number


class XiaoMusic:
    def __init__(self, config: Config):
        self.config = config

        self.last_cmd = ""  # <--- 【新增这行】初始化变量

        # 初始化事件总线
        self.event_bus = EventBus()

        # 初始化认证管理器（延迟初始化部分属性）
        self._auth_manager = None

        # 初始化设备管理器（延迟初始化）
        self._device_manager = None

        self.running_task = []

        # 音乐库管理器（延迟初始化，在配置准备好之后）
        self._music_library = None

        # 命令处理器（延迟初始化，在配置准备好之后）
        self._command_handler = None

        # 配置管理器（延迟初始化）
        self._config_manager = None

        # 初始化配置
        self.init_config()

        # 初始化文件监控管理器
        self._file_watcher = None

        # 初始化音乐URL处理器（延迟初始化，在 init_config 之后）
        self._music_url_handler = None

        # 初始化在线音乐服务（延迟初始化，在 js_plugin_manager 之后）
        self._online_music_service = None

        # 初始化对话轮询器（延迟初始化，在配置和服务准备好之后）
        self._conversation_poller = None

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

        # 初始化配置管理器（在日志准备好之后）
        self._config_manager = ConfigManager(
            config=self.config,
            log=self.log,
        )

        # 尝试从设置里加载配置
        config_data = self._config_manager.try_init_setting()
        if config_data:
            self.update_config_from_setting(config_data)

        # 初始化音乐库管理器（在配置准备好之后）
        self._music_library = MusicLibrary(
            config=self.config,
            log=self.log,
            music_path=self.music_path,
            download_path=self.download_path,
            hostname=self.hostname,
            public_port=self.public_port,
            music_path_depth=self.music_path_depth,
            exclude_dirs=self.exclude_dirs,
            event_bus=self.event_bus,
        )

        # 启动时重新生成一次播放列表
        self._music_library.gen_all_music_list()

        # 初始化音乐URL处理器（在配置和音乐列表准备好之后）
        self._music_url_handler = MusicUrlHandler(
            config=self.config,
            log=self.log,
            hostname=self.hostname,
            public_port=self.public_port,
            music_library=self._music_library,
        )

        # 初始化在线音乐服务（在 js_plugin_manager 准备好之后）
        self._online_music_service = OnlineMusicService(
            log=self.log,
            js_plugin_manager=self.js_plugin_manager,
            xiaomusic_instance=self,  # 传递xiaomusic实例
        )

        # 初始化设备管理器（在配置准备好之后）
        self._device_manager = DeviceManager(
            config=self.config,
            log=self.log,
            xiaomusic=self,
        )

        # 初始化认证管理器（在配置和设备管理器准备好之后）
        self._auth_manager = AuthManager(
            config=self.config,
            log=self.log,
            device_manager=self._device_manager,
        )

        # 初始化插件
        self.plugin_manager = PluginManager(self)

        # 初始化对话轮询器（在 device_id_did 准备好之后）
        self._conversation_poller = ConversationPoller(
            config=self.config,
            log=self.log,
            auth_manager=self._auth_manager,
            device_manager=self._device_manager,
        )

        # 初始化命令处理器（在所有依赖准备好之后）
        self._command_handler = CommandHandler(
            config=self.config,
            log=self.log,
            xiaomusic_instance=self,
        )

        # 启动统计
        self.analytics = Analytics(self.log, self.config)

        # 订阅配置变更事件
        self.event_bus.subscribe(CONFIG_CHANGED, self.save_cur_config)
        self.event_bus.subscribe(DEVICE_CONFIG_CHANGED, self.save_cur_config)

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

    def setup_logger(self):
        log_format = f"%(asctime)s [{__version__}] [%(levelname)s] %(filename)s:%(lineno)d: %(message)s"
        date_format = "[%Y-%m-%d %H:%M:%S]"
        formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

        self.log = logging.getLogger("xiaomusic")
        self.log.handlers.clear()  # 清除已有的 handlers
        self.log.setLevel(logging.DEBUG if self.config.verbose else logging.INFO)

        # 文件日志处理器
        log_file = self.config.log_file
        log_path = os.path.dirname(log_file)
        if log_path and not os.path.exists(log_path):
            os.makedirs(log_path)
        if os.path.exists(log_file):
            try:
                os.remove(log_file)
            except Exception as e:
<<<<<<< HEAD
                print(f"无法删除旧日志文件: {log_file} {e}")

        file_handler = RotatingFileHandler(
=======
                # 在 self.log 初始化之前，使用基础的日志功能
                logging.warning(f"无法删除旧日志文件: {log_file} {e}")
        handler = RotatingFileHandler(
>>>>>>> 18578c4 (增加musicfree插件集成功能)
            self.config.log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=1,
            encoding="utf-8",
        )
<<<<<<< HEAD
        file_handler.stream.flush()
        file_handler.setFormatter(formatter)
        self.log.addHandler(file_handler)

        # 控制台日志处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.log.addHandler(console_handler)
=======
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

    async def get_music_sec_url(self, name):
        """获取歌曲播放时长和播放地址

        Args:
            name: 歌曲名称
        Returns:
            tuple: (播放时长(秒), 播放地址)
        """
        url, origin_url = await self.get_music_url(name)
        self.log.info(
            f"get_music_sec_url. name:{name} url:{url} origin_url:{origin_url}"
        )

        # 电台直接返回
        if self.is_web_radio_music(name):
            self.log.info("电台不会有播放时长")
            return 0, url

        # 获取播放时长
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

    async def get_music_url(self, name):
        """获取音乐播放地址

        Args:
            name: 歌曲名称
        Returns:
            tuple: (播放地址, 原始地址) - 网络音乐时可能有原始地址
        """
        if self.is_online_music(name):
            return await self._get_online_music_url(name)
        elif self.is_web_music(name):
            return await self._get_web_music_url(name)
        return self._get_local_music_url(name), None

    def is_online_music(self, name):
        """判断是否为在线音乐"""
        music_info = self.all_music.get(name, {})
        return music_info.get('source') == 'online'

    async def _get_online_music_url(self, name):
        """获取在线音乐播放地址"""
        music_info = self.all_music.get(name, {})
        if not music_info or music_info.get('source') != 'online':
            return "", None
        
        try:
            plugin_name = music_info.get('plugin_name')
            original_data = music_info.get('original_data', {})
            
            # 使用适配器转换音乐项
            from .js_adapter import JSAdapter
            if not hasattr(self, 'js_adapter'):
                self.js_adapter = JSAdapter(self)
            
            plugin_music_item = self.js_adapter.convert_music_item_for_plugin(music_info)
            
            # 通过插件获取播放链接
            media_source = self.js_plugin_manager.get_media_source(plugin_name, plugin_music_item)
            
            # 使用适配器格式化媒体源结果
            formatted_source = self.js_adapter.format_media_source_result(media_source, music_info)
            
            if not formatted_source or not formatted_source.get('url'):
                self.log.error(f"Failed to get media source for {name}")
                return "", None
            
            url = formatted_source['url']
            origin_url = url
            
            # 是否需要代理
            if self.config.web_music_proxy:
                proxy_url = self._get_proxy_url(url)
                return proxy_url, origin_url
            
            return url, origin_url
            
        except Exception as e:
            self.log.error(f"Error getting online music URL for {name}: {e}")
            import traceback
            self.log.error(f"Full traceback: {traceback.format_exc()}")
            return "", None

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
>>>>>>> 18578c4 (增加musicfree插件集成功能)

    async def analytics_task_daily(self):
        while True:
            await self.analytics.send_daily_event()
            await asyncio.sleep(3600)

    def start_file_watch(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if not self._file_watcher:
            self._file_watcher = FileWatcherManager(
                config=self.config,
                log=self.log,
                music_path=self.music_path,
                on_change_callback=self._on_file_change,
            )
        self._file_watcher.start(loop)

    def _on_file_change(self):
        self.log.info("检测到目录音乐文件变化，正在刷新歌曲列表。")
        self._music_library.gen_all_music_list()
        # 更新每个设备的歌单
        self.update_all_playlist()

    def stop_file_watch(self):
        if self._file_watcher:
            self._file_watcher.stop()

    async def run_forever(self):
        self.log.info("run_forever start")
        self._music_library.try_gen_all_music_tag()  # 事件循环开始后调用一次
        self.crontab.start()
        await asyncio.create_task(self.analytics.send_startup_event())
        # 取配置 enable_file_watch 循环开始时调用一次，控制目录监控开关
        if self.config.enable_file_watch:
            self.start_file_watch()
        analytics_task = asyncio.create_task(self.analytics_task_daily())
        assert (
            analytics_task is not None
        )  # to keep the reference to task, do not remove this
        await self._auth_manager.init_all_data()
        # 启动对话循环，传递回调函数
        await self._conversation_poller.run_conversation_loop(
            self.do_check_cmd, self.reset_timer_when_answer
        )

    # 匹配命令
    async def do_check_cmd(self, did="", query="", ctrl_panel=True, **kwargs):
        """检查并执行命令（委托给 command_handler）"""
        return await self._command_handler.do_check_cmd(
            did, query, ctrl_panel, **kwargs
        )

    # 重置计时器
    async def reset_timer_when_answer(self, answer_length, did):
        await self._device_manager.devices[did].reset_timer_when_answer(answer_length)

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

    def shutdown(self):
        """关闭 xiaomusic 服务"""
        # 关闭 JS 插件管理器
        if hasattr(self, 'js_plugin_manager') and self.js_plugin_manager:
            self.js_plugin_manager.shutdown()
            
        # 关闭其他资源
        if hasattr(self, 'session') and self.session:
            asyncio.run(self.session.close())

    async def is_task_finish(self):
        if len(self.running_task) == 0:
            return True
        task = self.running_task[0]
        if task and task.done():
            return True
        return False

    async def check_replay(self, did):
        return await self._device_manager.devices[did].check_replay()

    def find_real_music_name(self, name, n):
        """模糊搜索音乐名称（委托给 music_library）"""
        return self._music_library.find_real_music_name(name, n)

    def did_exist(self, did):
        return did in self._device_manager.devices

    # 播放一个 url
    async def play_url(self, did="", arg1="", **kwargs):
        self.log.info(f"手动推送链接：{arg1}")
        url = arg1
        return await self._device_manager.devices[did].group_player_play(url)

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
        await self._device_manager.devices[did].set_play_type(play_type, dotts)

    # 设置为刷新列表
    async def gen_music_list(self, **kwargs):
        self._music_library.gen_all_music_list()
        self.update_all_playlist()
        self.log.info("gen_music_list ok")

    # 更新网络歌单
    async def refresh_web_music_list(self, **kwargs):
        url = self.config.music_list_url
        if url:
            self.log.debug(f"refresh_web_music_list begin url:{url}")
            content = await downloadfile(url)
            self.config.music_list_json = content
            # 配置文件落地
            self.save_cur_config()
            self.log.debug(f"refresh_web_music_list url:{url} content:{content}")
        self.log.info(f"refresh_web_music_list ok {url}")

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
        filename = self._music_library.get_filename(name)
        if filename == "":
            self.log.info(f"${name} not exist")
            return
        try:
            os.remove(filename)
            self.log.info(f"del ${filename} success")
        except OSError:
            self.log.error(f"del ${filename} failed")
        # 重新生成音乐列表
        self._music_library.gen_all_music_list()
        self.update_all_playlist()

    # ===========================在线搜索函数================================

    def default_url(self):
        """委托给 online_music_service"""
        return self._online_music_service.default_url()

    # 在线获取歌曲列表（委托给 online_music_service）
    async def get_music_list_online(
        self, plugin="all", keyword="", page=1, limit=20, **kwargs
    ):
        """委托给 online_music_service"""
        return await self._online_music_service.get_music_list_online(
            plugin, keyword, page, limit, **kwargs
        )

    @staticmethod
    async def get_real_url_of_openapi(url: str, timeout: int = 10) -> str:
        """委托给 OnlineMusicService 的静态方法"""
        return await OnlineMusicService.get_real_url_of_openapi(url, timeout)

    # 调用MusicFree插件获取歌曲列表（委托给 online_music_service）
    async def get_music_list_mf(
        self, plugin="all", keyword="", artist="", page=1, limit=20, **kwargs
    ):
        """委托给 online_music_service"""
        return await self._online_music_service.get_music_list_mf(
            plugin, keyword, artist, page, limit, **kwargs
        )

    # 调用MusicFree插件获取真实播放url（委托给 online_music_service）
    async def get_media_source_url(self, music_item, quality: str = "standard"):
        """委托给 online_music_service"""
        return await self._online_music_service.get_media_source_url(
            music_item, quality
        )

    # 调用MusicFree插件获取歌词（委托给 online_music_service）
    async def get_media_lyric(self, music_item):
        """委托给 online_music_service"""
        return await self._online_music_service.get_media_lyric(music_item)

    # 在线搜索歌手，添加歌手歌单并播放
    async def search_singer_play(self, did, search_key, name):
        """委托给 online_music_service"""
        return await self._online_music_service.search_singer_play(
            did, search_key, name
        )

    # 追加歌手歌曲
    async def add_singer_song(self, list_name, name):
        """委托给 online_music_service"""
        return await self._online_music_service.add_singer_song(list_name, name)

    # 在线搜索搜索最符合的一首歌并播放
    async def search_top_one_play(self, did, search_key, name):
        """委托给 online_music_service"""
        return await self._online_music_service.search_top_one_play(
            did, search_key, name
        )

    # 在线播放：在线搜索、播放
    async def online_play(self, did="", arg1="", **kwargs):
        """委托给 online_music_service"""
        return await self._online_music_service.online_play(did, arg1, **kwargs)

    # 播放歌手：在线搜索歌手并存为列表播放
    async def singer_play(self, did="", arg1="", **kwargs):
        """委托给 online_music_service"""
        return await self._online_music_service.singer_play(did, arg1, **kwargs)

    # 处理推送的歌单并播放
    async def push_music_list_play(self, did, song_list, list_name):
        """委托给 online_music_service"""
        return await self._online_music_service.push_music_list_play(
            did, song_list, list_name
        )

    # ===========================================================

    def _find_real_music_list_name(self, list_name):
        """模糊搜索播放列表名称（委托给 music_library）"""
        return self._music_library.find_real_music_list_name(list_name)

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
        if list_name not in self._music_library.music_list:
            await self.do_tts(did, f"播放列表{list_name}不存在")
            return

        # 调用设备播放音乐列表的方法
        await self._device_manager.devices[did].play_music_list(list_name, music_name)

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
        if list_name not in self._music_library.music_list:
            await self.do_tts(did, f"播放列表{list_name}不存在")
            return

        index = chinese_to_number(chinese_index)
        play_list = self._music_library.music_list[list_name]
        if 0 <= index - 1 < len(play_list):
            music_name = play_list[index - 1]
            self.log.info(f"即将播放 ${arg1} 里的第 ${index} 个: ${music_name}")
            await self._device_manager.devices[did].play_music_list(
                list_name, music_name
            )
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

    # 后台搜索播放
    async def do_play(
        self, did, name, search_key="", exact=False, update_cur_list=False
    ):
        return await self._device_manager.devices[did].play(
            name, search_key, exact, update_cur_list
        )

    # 本地播放
    async def playlocal(self, did="", arg1="", **kwargs):
        return await self._device_manager.devices[did].playlocal(
            arg1, update_cur_list=True
        )

    # 本地搜索播放
    async def search_playlocal(self, did="", arg1="", **kwargs):
        return await self._device_manager.devices[did].playlocal(
            arg1, exact=False, update_cur_list=False
        )

    async def play_next(self, did="", **kwargs):
        return await self._device_manager.devices[did].play_next()

    async def play_prev(self, did="", **kwargs):
        return await self._device_manager.devices[did].play_prev()

    # 停止
    async def stop(self, did="", arg1="", **kwargs):
        return await self._device_manager.devices[did].stop(arg1=arg1)

    # 定时关机
    async def stop_after_minute(self, did="", arg1=0, **kwargs):
        try:
            # 尝试阿拉伯数字转换中文数字
            minute = int(arg1)
        except (KeyError, ValueError):
            # 如果阿拉伯数字转换失败，尝试中文数字
            minute = chinese_to_number(str(arg1))
        return await self._device_manager.devices[did].stop_after_minute(minute)

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
        """更新每个设备的歌单"""
        for device in self._device_manager.devices.values():
            device.update_playlist()

    # 获取音量
    async def get_volume(self, did="", **kwargs):
        return await self._device_manager.devices[did].get_volume()

    # 设置音量
    async def set_volume(self, did="", arg1=0, **kwargs):
        if did not in self._device_manager.devices:
            self.log.info(f"设备 did:{did} 不存在, 不能设置音量")
            return
        volume = int(arg1)
        return await self._device_manager.devices[did].set_volume(volume)

    # 搜索音乐
    def searchmusic(self, name):
<<<<<<< HEAD
        """搜索音乐（委托给 music_library）"""
        return self._music_library.searchmusic(name)
=======
        """扩展搜索音乐功能，集成在线音乐源"""
        self.log.info(f"Starting search for: {name}")
        all_music_list = list(self.all_music.keys())
        self.log.info(f"Local music count: {len(all_music_list)}")
        
        # 1. 现有本地音乐搜索
        search_list = fuzzyfinder(name, all_music_list, self._extra_index_search)
        self.log.info(f"Local search results count: {len(search_list)}")
        
        # 2. 【新增】JS 插件在线搜索
        if hasattr(self, 'js_plugin_manager') and self.js_plugin_manager:
            try:
                online_results = self._search_online_music(name)
                self.log.info(f"Online search results count: {len(online_results)}")
                # 合并结果，优先级：JS插件 > 本地
                search_list = online_results + search_list
                self.log.info(f"Total search results count: {len(search_list)}")
            except Exception as e:
                self.log.error(f"Online music search failed: {e}")
        else:
            self.log.warning("JS Plugin Manager not available")
        
        self.log.debug(f"searchmusic. name:{name} search_list:{search_list}")
        return search_list
>>>>>>> 18578c4 (增加musicfree插件集成功能)

    def _search_online_music(self, name):
        """搜索在线音乐"""
        self.log.info(f"Starting online music search for: {name}")
        online_results = []
        
        enabled_plugins = self.js_plugin_manager.get_enabled_plugins()
        self.log.info(f"Enabled plugins: {enabled_plugins}")
        
        # 并行搜索所有启用的插件
        for plugin_name in enabled_plugins:
            try:
                self.log.info(f"Searching in plugin: {plugin_name}")
                plugin_results = self.js_plugin_manager.search(plugin_name, name)
                formatted_results = self._format_online_results(plugin_results.get('data', []), plugin_name)
                self.log.info(f"Plugin {plugin_name} returned {len(formatted_results)} results")
                online_results.extend(formatted_results)
            except Exception as e:
                self.log.error(f"Plugin {plugin_name} search failed: {e}")
                import traceback
                self.log.error(f"Full traceback: {traceback.format_exc()}")
        
        self.log.info(f"Total online results: {len(online_results)}")
        return online_results

    def _format_online_results(self, results, plugin_name):
        """格式化在线搜索结果为 xiaomusic 格式"""
        return self.js_adapter.format_search_results(results, plugin_name)

    # 获取播放列表
    def get_music_list(self):
        """获取播放列表（委托给 music_library）"""
        return self._music_library.get_music_list()

    # 获取当前的播放列表
    def get_cur_play_list(self, did):
        return self._device_manager.devices[did].get_cur_play_list()

    # 正在播放中的音乐
    def playingmusic(self, did):
        cur_music = self._device_manager.devices[did].get_cur_music()
        self.log.debug(f"playingmusic. cur_music:{cur_music}")
        return cur_music

    def get_offset_duration(self, did):
        return self._device_manager.devices[did].get_offset_duration()

    # 当前是否正在播放歌曲
    def isplaying(self, did):
        return self._device_manager.devices[did].isplaying()

    # 获取当前配置
    def getconfig(self):
        """获取当前配置（委托给 config_manager）"""
        return self._config_manager.get_config()

    # 保存配置并重新启动
    async def saveconfig(self, data):
        """保存配置并重新启动"""
        # 更新配置
        self.update_config_from_setting(data)
        self._auth_manager.save_token(data.get("cookie"))
        # 配置文件落地
        self.save_cur_config()
        # 重新初始化
        await self.reinit()

    # 把当前配置落地
    def save_cur_config(self):
        """把当前配置落地（委托给 config_manager）"""
        self._config_manager.save_cur_config(self._device_manager.devices)

    def update_config_from_setting(self, data):
        """从设置更新配置"""
        # 委托给 config_manager 更新配置
        self._config_manager.update_config(data)

        # 重新初始化配置相关的属性
        self.init_config()

        debug_config = deepcopy_data_no_sensitive_info(self.config)
        self.log.info(f"update_config_from_setting ok. data:{debug_config}")

        joined_keywords = "/".join(self.config.key_match_order)
        self.log.info(f"语音控制已启动, 用【{joined_keywords}】开头来控制")
        self.log.debug(f"key_word_dict: {self.config.key_word_dict}")

        # 根据新配置控制文件监控
        if self.config.enable_file_watch:
            self.log.info("配置更新：开启目录监控")
            self.start_file_watch()
        else:
            self.log.info("配置更新：关闭目录监控")
            self.stop_file_watch()

        # 重新加载计划任务
        self.crontab.reload_config(self)

    # 重新初始化
    async def reinit(self):
        for handler in self.log.handlers:
            handler.close()
        self.setup_logger()
        await self._auth_manager.init_all_data()
        self._music_library.gen_all_music_list()
        self.update_all_playlist()

        debug_config = deepcopy_data_no_sensitive_info(self.config)
        self.log.info(f"reinit success. data:{debug_config}")

    # 获取所有设备
    async def getalldevices(self, **kwargs):
        device_list = []
        try:
            device_list = await self._auth_manager.mina_service.device_list()
        except Exception as e:
            self.log.warning(f"Execption {e}")
            # 重新初始化
            await self.reinit()
        return device_list

    async def debug_play_by_music_url(self, arg1=None):
        if arg1 is None:
            arg1 = {}
        data = arg1
        device_id = self.config.get_one_device_id()
        self.log.info(f"debug_play_by_music_url: {data} {device_id}")
        return await self._auth_manager.mina_service.ubus_request(
            device_id,
            "player_play_music",
            "mediaplayer",
            data,
        )

    async def exec(self, did="", arg1=None, **kwargs):
        self._auth_manager._cur_did = did
        code = arg1 if arg1 else 'code1("hello")'
        await self.plugin_manager.execute_plugin(code)

    # 此接口用于插件中获取当前设备
    def get_cur_did(self):
        return self._auth_manager._cur_did

    async def do_tts(self, did, value):
        return await self._device_manager.devices[did].do_tts(value)
