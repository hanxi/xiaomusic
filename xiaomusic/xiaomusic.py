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
from xiaomusic.online_music import OnlineMusicService
from xiaomusic.plugin import PluginManager
from xiaomusic.utils.network_utils import downloadfile
from xiaomusic.utils.system_utils import deepcopy_data_no_sensitive_info
from xiaomusic.utils.text_utils import chinese_to_number


class XiaoMusic:
    def __init__(self, config: Config):
        self.config = config

        # 初始化事件总线
        self.event_bus = EventBus()

        # 初始化认证管理器（延迟初始化部分属性）
        self.auth_manager = None

        # 初始化设备管理器（延迟初始化）
        self.device_manager = None

        self.running_task = []

        # 音乐库管理器（延迟初始化，在配置准备好之后）
        self.music_library = None

        # 命令处理器（延迟初始化，在配置准备好之后）
        self.command_handler = None

        # 配置管理器（延迟初始化）
        self.config_manager = None

        # 初始化配置
        self.init_config()

        # 初始化文件监控管理器
        self.file_watcher = None

        # 初始化在线音乐服务（延迟初始化，在 js_plugin_manager 之后）
        self.online_music_service = None

        # 初始化对话轮询器（延迟初始化，在配置和服务准备好之后）
        self.conversation_poller = None

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

        # 初始化配置管理器（在日志准备好之后）
        self.config_manager = ConfigManager(
            config=self.config,
            log=self.log,
        )

        # 尝试从设置里加载配置
        config_data = self.config_manager.try_init_setting()
        if config_data:
            self.update_config_from_setting(config_data)

        # 初始化音乐库管理器（在配置准备好之后）
        self.music_library = MusicLibrary(
            config=self.config,
            log=self.log,
            music_path_depth=self.music_path_depth,
            exclude_dirs=self.exclude_dirs,
            event_bus=self.event_bus,
        )

        # 启动时重新生成一次播放列表
        self.music_library.gen_all_music_list()

        # 初始化在线音乐服务（在 js_plugin_manager 准备好之后）
        self.online_music_service = OnlineMusicService(
            log=self.log,
            js_plugin_manager=self.js_plugin_manager,
            xiaomusic_instance=self,  # 传递xiaomusic实例
        )

        # 初始化设备管理器（在配置准备好之后）
        self.device_manager = DeviceManager(
            config=self.config,
            log=self.log,
            xiaomusic=self,
        )

        # 初始化认证管理器（在配置和设备管理器准备好之后）
        self.auth_manager = AuthManager(
            config=self.config,
            log=self.log,
            device_manager=self.device_manager,
        )

        # 初始化插件
        self.plugin_manager = PluginManager(self)

        # 初始化对话轮询器（在 device_id_did 准备好之后）
        self.conversation_poller = ConversationPoller(
            config=self.config,
            log=self.log,
            auth_manager=self.auth_manager,
            device_manager=self.device_manager,
        )

        # 初始化命令处理器（在所有依赖准备好之后）
        self.command_handler = CommandHandler(
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

        if self.config.conf_path == self.config.music_path:
            self.log.warning("配置文件目录和音乐目录建议设置为不同的目录")

    def init_config(self):
        if not os.path.exists(self.config.music_path):
            os.makedirs(self.config.music_path)

        if not os.path.exists(self.config.download_path):
            os.makedirs(self.config.download_path)

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
                print(f"无法删除旧日志文件: {log_file} {e}")

        file_handler = RotatingFileHandler(
            self.config.log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=1,
            encoding="utf-8",
        )
        file_handler.stream.flush()
        file_handler.setFormatter(formatter)
        self.log.addHandler(file_handler)

        # 控制台日志处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.log.addHandler(console_handler)

    async def analytics_task_daily(self):
        while True:
            await self.analytics.send_daily_event()
            await asyncio.sleep(3600)

    def start_file_watch(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if not self.file_watcher:
            self.file_watcher = FileWatcherManager(
                config=self.config,
                log=self.log,
                on_change_callback=self._on_file_change,
            )
        self.file_watcher.start(loop)

    def _on_file_change(self):
        self.log.info("检测到目录音乐文件变化，正在刷新歌曲列表。")
        self.music_library.gen_all_music_list()
        # 更新每个设备的歌单
        self.update_all_playlist()

    def stop_file_watch(self):
        if self.file_watcher:
            self.file_watcher.stop()

    async def run_forever(self):
        self.log.info("run_forever start")
        self.music_library.try_gen_all_music_tag()  # 事件循环开始后调用一次
        self.crontab.start()
        await asyncio.create_task(self.analytics.send_startup_event())
        # 取配置 enable_file_watch 循环开始时调用一次，控制目录监控开关
        if self.config.enable_file_watch:
            self.start_file_watch()
        analytics_task = asyncio.create_task(self.analytics_task_daily())
        assert (
            analytics_task is not None
        )  # to keep the reference to task, do not remove this
        await self.auth_manager.init_all_data()
        # 启动对话循环，传递回调函数
        await self.conversation_poller.run_conversation_loop(
            self.do_check_cmd, self.reset_timer_when_answer
        )

    # 匹配命令
    async def do_check_cmd(self, did="", query="", ctrl_panel=True, **kwargs):
        """检查并执行命令（委托给 command_handler）"""
        return await self.command_handler.do_check_cmd(did, query, ctrl_panel, **kwargs)

    # 重置计时器
    async def reset_timer_when_answer(self, answer_length, did):
        await self.device_manager.devices[did].reset_timer_when_answer(answer_length)

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
        return await self.device_manager.devices[did].check_replay()

    def find_real_music_name(self, name, n):
        """模糊搜索音乐名称（委托给 music_library）"""
        return self.music_library.find_real_music_name(name, n)

    def did_exist(self, did):
        return did in self.device_manager.devices

    # 播放一个 url
    async def play_url(self, did="", arg1="", **kwargs):
        self.log.info(f"手动推送链接：{arg1}")
        url = arg1
        return await self.device_manager.devices[did].group_player_play(url)

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
        await self.device_manager.devices[did].set_play_type(play_type, dotts)

    # 设置为刷新列表
    async def gen_music_list(self, **kwargs):
        self.music_library.gen_all_music_list()
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
        filename = self.music_library.get_filename(name)
        if filename == "":
            self.log.info(f"${name} not exist")
            return
        try:
            os.remove(filename)
            self.log.info(f"del ${filename} success")
        except OSError:
            self.log.error(f"del ${filename} failed")
        # 重新生成音乐列表
        self.music_library.gen_all_music_list()
        self.update_all_playlist()

    # ===========================在线搜索函数================================

    def default_url(self):
        """委托给 online_music_service"""
        return self.online_music_service.default_url()

    # 在线获取歌曲列表（委托给 online_music_service）
    async def get_music_list_online(
        self, plugin="all", keyword="", page=1, limit=20, **kwargs
    ):
        """委托给 online_music_service"""
        return await self.online_music_service.get_music_list_online(
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
        return await self.online_music_service.get_music_list_mf(
            plugin, keyword, artist, page, limit, **kwargs
        )

    # 调用MusicFree插件获取歌词（委托给 online_music_service）
    async def get_media_lyric(self, music_item):
        """委托给 online_music_service"""
        return await self.online_music_service.get_media_lyric(music_item)

    # 在线搜索歌手，添加歌手歌单并播放
    async def search_singer_play(self, did, search_key, name):
        """委托给 online_music_service"""
        return await self.online_music_service.search_singer_play(did, search_key, name)

    # 追加歌手歌曲
    async def add_singer_song(self, list_name, name):
        """委托给 online_music_service"""
        return await self.online_music_service.add_singer_song(list_name, name)

    # 在线搜索搜索最符合的一首歌并播放
    async def search_top_one_play(self, did, search_key, name):
        """委托给 online_music_service"""
        return await self.online_music_service.search_top_one_play(
            did, search_key, name
        )

    # 在线播放：在线搜索、播放
    async def online_play(self, did="", arg1="", **kwargs):
        """委托给 online_music_service"""
        return await self.online_music_service.online_play(did, arg1, **kwargs)

    # 播放歌手：在线搜索歌手并存为列表播放
    async def singer_play(self, did="", arg1="", **kwargs):
        """委托给 online_music_service"""
        return await self.online_music_service.singer_play(did, arg1, **kwargs)

    # 处理推送的歌单并播放
    async def push_music_list_play(self, did, song_list, list_name):
        """委托给 online_music_service"""
        return await self.online_music_service.push_music_list_play(
            did, song_list, list_name
        )

    # ===========================================================

    def _find_real_music_list_name(self, list_name):
        """模糊搜索播放列表名称（委托给 music_library）"""
        return self.music_library.find_real_music_list_name(list_name)

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
        if list_name not in self.music_library.music_list:
            await self.do_tts(did, f"播放列表{list_name}不存在")
            return

        # 调用设备播放音乐列表的方法
        await self.device_manager.devices[did].play_music_list(list_name, music_name)

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
        if list_name not in self.music_library.music_list:
            await self.do_tts(did, f"播放列表{list_name}不存在")
            return

        index = chinese_to_number(chinese_index)
        play_list = self.music_library.music_list[list_name]
        if 0 <= index - 1 < len(play_list):
            music_name = play_list[index - 1]
            self.log.info(f"即将播放 ${arg1} 里的第 ${index} 个: ${music_name}")
            await self.device_manager.devices[did].play_music_list(
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
        return await self.device_manager.devices[did].play(
            name, search_key, exact, update_cur_list
        )

    # 本地播放
    async def playlocal(self, did="", arg1="", **kwargs):
        return await self.device_manager.devices[did].playlocal(
            arg1, update_cur_list=True
        )

    # 本地搜索播放
    async def search_playlocal(self, did="", arg1="", **kwargs):
        return await self.device_manager.devices[did].playlocal(
            arg1, exact=False, update_cur_list=False
        )

    async def play_next(self, did="", **kwargs):
        return await self.device_manager.devices[did].play_next()

    async def play_prev(self, did="", **kwargs):
        return await self.device_manager.devices[did].play_prev()

    # 停止
    async def stop(self, did="", arg1="", **kwargs):
        return await self.device_manager.devices[did].stop(arg1=arg1)

    # 定时关机
    async def stop_after_minute(self, did="", arg1=0, **kwargs):
        try:
            # 尝试阿拉伯数字转换中文数字
            minute = int(arg1)
        except (KeyError, ValueError):
            # 如果阿拉伯数字转换失败，尝试中文数字
            minute = chinese_to_number(str(arg1))
        return await self.device_manager.devices[did].stop_after_minute(minute)

    # 添加歌曲到收藏列表
    async def add_to_favorites(self, did="", arg1="", **kwargs):
        name = arg1 if arg1 else self.playingmusic(did)
        self.log.info(f"add_to_favorites {name}")
        if not name:
            self.log.warning("当前没有在播放歌曲，添加歌曲到收藏列表失败")
            return

        self.music_library.play_list_add_music("收藏", [name])

    # 从收藏列表中移除
    async def del_from_favorites(self, did="", arg1="", **kwargs):
        name = arg1 if arg1 else self.playingmusic(did)
        self.log.info(f"del_from_favorites {name}")
        if not name:
            self.log.warning("当前没有在播放歌曲，从收藏列表中移除失败")
            return

        self.music_library.play_list_del_music("收藏", [name])

    # 更新每个设备的歌单
    def update_all_playlist(self):
        """更新每个设备的歌单"""
        for device in self.device_manager.devices.values():
            device.update_playlist()

    # 获取音量
    async def get_volume(self, did="", **kwargs):
        return await self.device_manager.devices[did].get_volume()

    # 设置音量
    async def set_volume(self, did="", arg1=0, **kwargs):
        if did not in self.device_manager.devices:
            self.log.info(f"设备 did:{did} 不存在, 不能设置音量")
            return
        volume = int(arg1)
        return await self.device_manager.devices[did].set_volume(volume)

    # 搜索音乐
    def searchmusic(self, name):
        """搜索音乐（委托给 music_library）"""
        return self.music_library.searchmusic(name)

    # 获取播放列表
    def get_music_list(self):
        """获取播放列表（委托给 music_library）"""
        return self.music_library.get_music_list()

    # 获取当前的播放列表
    def get_cur_play_list(self, did):
        return self.device_manager.devices[did].get_cur_play_list()

    # 正在播放中的音乐
    def playingmusic(self, did):
        cur_music = self.device_manager.devices[did].get_cur_music()
        self.log.debug(f"playingmusic. cur_music:{cur_music}")
        return cur_music

    def get_offset_duration(self, did):
        return self.device_manager.devices[did].get_offset_duration()

    # 当前是否正在播放歌曲
    def isplaying(self, did):
        return self.device_manager.devices[did].is_playing

    # 获取当前配置
    def getconfig(self):
        """获取当前配置（委托给 config_manager）"""
        return self.config_manager.get_config()

    # 保存配置并重新启动
    async def saveconfig(self, data):
        """保存配置并重新启动"""
        # 更新配置
        self.update_config_from_setting(data)
        # 配置文件落地
        self.save_cur_config()
        # 重新初始化
        await self.reinit()

    # 把当前配置落地
    def save_cur_config(self):
        """把当前配置落地（委托给 config_manager）"""
        self.config_manager.save_cur_config(self.device_manager.devices)

    def update_config_from_setting(self, data):
        """从设置更新配置"""
        # 委托给 config_manager 更新配置
        self.config_manager.update_config(data)

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
        await self.auth_manager.init_all_data()
        self.music_library.gen_all_music_list()
        self.update_all_playlist()

        debug_config = deepcopy_data_no_sensitive_info(self.config)
        self.log.info(f"reinit success. data:{debug_config}")

    # 获取所有设备
    async def getalldevices(self, **kwargs):
        device_list = []
        try:
            device_list = await self.auth_manager.mina_service.device_list()
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
        return await self.auth_manager.mina_service.ubus_request(
            device_id,
            "player_play_music",
            "mediaplayer",
            data,
        )

    async def exec(self, did="", arg1=None, **kwargs):
        self.auth_manager._cur_did = did
        code = arg1 if arg1 else 'code1("hello")'
        await self.plugin_manager.execute_plugin(code)

    # 此接口用于插件中获取当前设备
    def get_cur_did(self):
        return self.auth_manager._cur_did

    async def do_tts(self, did, value):
        return await self.device_manager.devices[did].do_tts(value)
