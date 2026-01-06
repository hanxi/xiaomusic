"""音乐URL处理模块

负责音乐播放地址的获取、代理和时长计算。
"""

import base64
import math
import urllib.parse

from xiaomusic.utils import (
    get_local_music_duration,
    get_web_music_duration,
    try_add_access_control_param,
)


class MusicUrlHandler:
    """音乐URL处理器

    负责处理音乐播放地址的获取、代理URL生成和播放时长计算。
    """

    def __init__(
        self,
        config,
        log,
        hostname,
        public_port,
        all_music,
        web_music_api,
        url_cache,
        get_filename_func,
        is_web_music_func,
        is_web_radio_music_func,
        is_need_use_play_music_api_func,
    ):
        """初始化URL处理器

        Args:
            config: 配置对象
            log: 日志对象
            hostname: 主机名
            public_port: 公开端口
            all_music: 所有音乐字典 {name: url/path}
            web_music_api: 网络音乐API配置
            url_cache: URL缓存对象
            get_filename_func: 获取文件名的函数
            is_web_music_func: 判断是否为网络音乐的函数
            is_web_radio_music_func: 判断是否为网络电台的函数
            is_need_use_play_music_api_func: 判断是否需要使用API的函数
        """
        self.config = config
        self.log = log
        self.hostname = hostname
        self.public_port = public_port
        self.all_music = all_music
        self._web_music_api = web_music_api
        self.url_cache = url_cache

        # 回调函数
        self.get_filename = get_filename_func
        self.is_web_music = is_web_music_func
        self.is_web_radio_music = is_web_radio_music_func
        self.is_need_use_play_music_api = is_need_use_play_music_api_func

    async def get_music_sec_url(self, name, true_url=None):
        """获取歌曲播放时长和播放地址

        Args:
            name: 歌曲名称
            true_url: 真实播放URL（可选）

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
        """获取网络音乐播放地址

        Args:
            name: 歌曲名称

        Returns:
            tuple: (播放地址, 原始地址)
        """
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
        """通过API获取真实播放地址

        Args:
            name: 歌曲名称
            url: 原始URL

        Returns:
            str: 真实播放地址，失败返回空字符串
        """
        headers = self._web_music_api[name].get("headers", {})
        url = await self.url_cache.get(url, headers, self.config)
        if not url:
            self.log.error(f"get_music_url use api fail. name:{name}, url:{url}")
        return url

    def _get_proxy_url(self, origin_url):
        """获取代理URL

        Args:
            origin_url: 原始URL

        Returns:
            str: 代理URL
        """
        urlb64 = base64.b64encode(origin_url.encode("utf-8")).decode("utf-8")
        proxy_url = f"{self.hostname}:{self.public_port}/proxy?urlb64={urlb64}"
        self.log.info(f"Using proxy url: {proxy_url}")
        return proxy_url

    def _get_local_music_url(self, name):
        """获取本地音乐播放地址

        Args:
            name: 歌曲名称

        Returns:
            str: 本地音乐播放URL
        """
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

    async def _get_web_music_duration(self, name, url, origin_url):
        """获取网络音乐时长

        Args:
            name: 歌曲名称
            url: 播放URL
            origin_url: 原始URL

        Returns:
            int: 播放时长（秒）
        """
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
        """获取本地音乐时长

        Args:
            name: 歌曲名称
            url: 播放URL

        Returns:
            int: 播放时长（秒）
        """
        filename = self.get_filename(name)
        self.log.info(f"get_music_sec_url. name:{name} filename:{filename}")
        duration = await get_local_music_duration(filename, self.config)
        sec = math.ceil(duration)
        self.log.info(f"本地歌曲 {name} : {filename} {url} 的时长 {sec} 秒")
        return sec

    async def _get_online_music_duration(self, name, url):
        """获取在线音乐时长

        Args:
            name: 歌曲名称
            url: 播放URL

        Returns:
            int: 播放时长（秒）
        """
        self.log.info(f"get_music_sec_url. name:{name}")
        duration = await get_local_music_duration(url, self.config)
        sec = math.ceil(duration)
        self.log.info(f"在线歌曲 {name} : {url} 的时长 {sec} 秒")
        return sec
