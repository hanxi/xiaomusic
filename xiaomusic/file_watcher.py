"""文件监控模块

提供音乐目录的文件变化监控功能，支持防抖延迟处理。
"""

import os

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from xiaomusic.const import SUPPORT_MUSIC_TYPE


class XiaoMusicPathWatch(FileSystemEventHandler):
    """音乐目录监控类

    使用延迟防抖机制，仅监控音乐文件的创建、删除和移动事件。

    Attributes:
        callback: 文件变化时的回调函数
        debounce_delay: 防抖延迟时间（秒）
        loop: asyncio 事件循环
    """

    def __init__(self, callback, debounce_delay, loop):
        """初始化文件监控器

        Args:
            callback: 文件变化时的回调函数
            debounce_delay: 防抖延迟时间（秒）
            loop: asyncio 事件循环对象
        """
        self.callback = callback
        self.debounce_delay = debounce_delay
        self.loop = loop
        self._debounce_handle = None

    def on_any_event(self, event):
        """处理文件系统事件

        只处理音乐文件的创建、删除和移动事件，忽略目录事件。

        Args:
            event: 文件系统事件对象
        """
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
        """调度回调函数执行

        使用防抖机制，在延迟时间内如果有新的事件，会取消之前的调度。
        """

        def _execute_callback():
            self._debounce_handle = None
            self.callback()

        if self._debounce_handle:
            self._debounce_handle.cancel()
        self._debounce_handle = self.loop.call_later(
            self.debounce_delay, _execute_callback
        )


class FileWatcherManager:
    """文件监控管理器

    负责启动和停止文件监控服务。
    """

    def __init__(self, config, log, on_change_callback):
        """初始化文件监控管理器

        Args:
            config: 配置对象
            log: 日志对象
            on_change_callback: 文件变化时的回调函数
        """
        self.config = config
        self.log = log
        self.on_change_callback = on_change_callback
        self._observer = None
        self._file_watch_handler = None

    def start(self, loop):
        """启动文件监控（支持重入）

        如果监控器已在运行，会先停止再重新启动。

        Args:
            loop: asyncio 事件循环对象
        """
        # 如果已经在运行，先停止
        if self._observer:
            self.stop()

        if not self.config.enable_file_watch:
            self.log.info("目录监控功能已关闭")
            return

        if not loop:
            self.log.warning("无法获取运行中的事件循环，目录监控功能可能无法正常工作")
            return

        # 创建文件监控处理器
        self._file_watch_handler = XiaoMusicPathWatch(
            callback=self.on_change_callback,
            debounce_delay=self.config.file_watch_debounce,
            loop=loop,
        )

        # 创建并启动监控器
        self._observer = Observer()
        self._observer.schedule(
            self._file_watch_handler, self.config.music_path, recursive=True
        )
        self._observer.start()
        self.log.info(f"已启动对 {self.config.music_path} 的目录监控。")

    def stop(self):
        """停止文件监控（支持重入）

        如果监控器未运行，不做任何操作。
        """
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self.log.info("已停止目录监控。")
            self._observer = None
            self._file_watch_handler = None
