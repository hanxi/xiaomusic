"""音乐URL处理模块

负责音乐播放地址的获取、代理和时长计算。
"""

import base64
import urllib.parse

from xiaomusic.utils import (
    MusicUrlCache,
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
        music_library,
    ):
        """初始化URL处理器

        Args:
            config: 配置对象
            log: 日志对象
            hostname: 主机名
            public_port: 公开端口
            music_library: 音乐库管理模块
        """
        self.config = config
        self.log = log
        self.hostname = hostname
        self.public_port = public_port
        self.music_library = music_library
        self.url_cache = MusicUrlCache()

    async def get_music_sec_url(self, name, cur_playlist):
        """获取歌曲播放时长和播放地址

        Args:
            name: 歌曲名称
            cur_playlist: 当前歌单名称
        Returns:
            tuple: (播放时长(秒), 播放地址)
        """
        url, origin_url = await self.get_music_url(name)
        self.log.info(
            f"get_music_sec_url. name:{name} url:{url} origin_url:{origin_url}"
        )
        sec = await self.music_library.get_music_duration(name)
        return sec, url

    async def get_music_url(self, name):
        self.log.info(f"get_music_url name:{name}")
        """获取音乐播放地址

        Args:
            name: 歌曲名称

        Returns:
            tuple: (播放地址, 原始地址) - 网络音乐时可能有原始地址
        """
        if self.music_library.is_web_music(name):
            return await self._get_web_music_url(name)
        return self._get_local_music_url(name), None

    async def _get_web_music_url(self, name):
        self.log.info("in _get_web_music_url")
        """获取网络音乐播放地址

        Args:
            name: 歌曲名称

        Returns:
            tuple: (播放地址, 原始地址)
        """
        url = self.music_library.all_music[name]
        self.log.info(f"get_music_url web music. name:{name}, url:{url}")

        # 需要通过API获取真实播放地址
        if self.music_library.is_need_use_play_music_api(name):
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
        headers = self.music_library._web_music_api[name].get("headers", {})
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
        filename = self.music_library.get_filename(name)
        self.log.info(
            f"_get_local_music_url local music. name:{name}, filename:{filename}"
        )
        return self._get_file_url(filename)

    def _get_file_url(self, filepath):
        """根据文件路径生成可访问的URL

        Args:
            filepath: 文件的完整路径

        Returns:
            str: 文件访问URL
        """
        filename = filepath

        # 处理文件路径
        if filename.startswith(self.config.music_path):
            filename = filename[len(self.config.music_path) :]
        filename = filename.replace("\\", "/")
        if filename.startswith("/"):
            filename = filename[1:]

        self.log.info(f"_get_file_url filepath:{filepath}, filename:{filename}")

        # 构造URL
        encoded_name = urllib.parse.quote(filename)
        url = f"{self.hostname}:{self.public_port}/music/{encoded_name}"
        return try_add_access_control_param(self.config, url)

    @staticmethod
    async def get_play_url(proxy_url):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(proxy_url) as response:
                # 获取最终重定向的 URL
                return str(response.url)
