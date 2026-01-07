#!/usr/bin/env python3
"""网络请求和下载相关工具函数"""

import asyncio
import hashlib
import logging
import os
import time
from collections import OrderedDict
from pathlib import Path
from time import sleep
from urllib.parse import (
    parse_qs,
    urlparse,
)

import aiohttp
import edge_tts

log = logging.getLogger(__package__)


async def downloadfile(url: str) -> str:
    """
    下载文件内容

    Args:
        url: 文件 URL

    Returns:
        文件文本内容

    Raises:
        Warning: 如果 URL 协议不是 HTTP/HTTPS
    """
    # 清理和验证URL
    # 解析URL
    parsed_url = urlparse(url)
    # 基础验证：仅允许HTTP和HTTPS协议
    if parsed_url.scheme not in ("http", "https"):
        raise Warning(
            f"Invalid URL scheme: {parsed_url.scheme}. Only HTTP and HTTPS are allowed."
        )
    # 构建目标URL
    cleaned_url = parsed_url.geturl()

    # 使用 aiohttp 创建一个客户端会话来发起请求
    async with aiohttp.ClientSession() as session:
        async with session.get(
            cleaned_url, timeout=5
        ) as response:  # 增加超时以避免长时间挂起
            # 如果响应不是200，引发异常
            response.raise_for_status()
            # 读取响应文本
            text = await response.text()
            return text


async def check_bili_fav_list(url: str) -> dict:
    """
    检查 B 站收藏夹/合集

    Args:
        url: B站收藏夹或合集 URL

    Returns:
        {bvid/url: title} 字典

    Raises:
        ValueError: 如果不支持的类型
        Exception: 如果请求失败
    """
    bvid_info = {}
    parsed_url = urlparse(url)
    path = parsed_url.path
    # 提取查询参数
    query_params = parse_qs(parsed_url.query)

    if parsed_url.hostname == "space.bilibili.com":
        if "/favlist" in path:
            lid = query_params.get("fid", [None])[0]
            type = query_params.get("ctype", [None])[0]
            if type == "11":
                type = "create"
            elif type == "21":
                type = "collect"
            else:
                raise ValueError("当前只支持合集和收藏夹")
        elif "/lists/" in path:
            parts = path.split("/")
            if len(parts) >= 4 and "?" in url:
                lid = parts[3]  # 提取 lid
                type = query_params.get("type", [None])[0]

        # https://api.bilibili.com/x/polymer/web-space/seasons_archives_list?season_id={lid}&page_size=30&page_num=1
        page_size = 100
        page_num = 1
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": url,
            "Origin": "https://space.bilibili.com",
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            if type == "season" or type == "collect":
                while True:
                    list_url = f"https://api.bilibili.com/x/polymer/web-space/seasons_archives_list?season_id={lid}&page_size={page_size}&page_num={page_num}"
                    async with session.get(list_url) as response:
                        if response.status != 200:
                            raise Exception(f"Failed to fetch data from {list_url}")
                        data = await response.json()
                        archives = data.get("data", {}).get("archives", [])
                        if not archives:
                            break
                        for archive in archives:
                            bvid = archive.get("bvid", None)
                            title = archive.get("title", None)
                            bvid_info[bvid] = title

                        if len(archives) < page_size:
                            break
                        page_num += 1
                        sleep(1)
            elif type == "create":
                while True:
                    list_url = f"https://api.bilibili.com/x/v3/fav/resource/list?media_id={lid}&pn={page_num}&ps={page_size}&order=mtime"
                    async with session.get(list_url) as response:
                        if response.status != 200:
                            raise Exception(f"Failed to fetch data from {list_url}")
                        data = await response.json()
                        medias = data.get("data", {}).get("medias", [])
                        if not medias:
                            break
                        for media in medias:
                            bvid = media.get("bvid", None)
                            title = media.get("title", None)
                            bvurl = f"https://www.bilibili.com/video/{bvid}"
                            bvid_info[bvurl] = title

                        if len(medias) < page_size:
                            break
                        page_num += 1
            else:
                raise ValueError("当前只支持合集和收藏夹")
    return bvid_info


async def download_playlist(config, url: str, dirname: str):
    """
    下载播放列表

    Args:
        config: 配置对象
        url: 播放列表 URL
        dirname: 保存目录名

    Returns:
        下载进程对象
    """
    title = f"{dirname}/%(title)s.%(ext)s"
    sbp_args = (
        "yt-dlp",
        "--yes-playlist",
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "--paths",
        config.download_path,
        "-o",
        title,
        "--ffmpeg-location",
        f"{config.ffmpeg_location}",
    )

    if config.proxy:
        sbp_args += ("--proxy", f"{config.proxy}")

    if config.enable_yt_dlp_cookies:
        sbp_args += ("--cookies", f"{config.yt_dlp_cookies_path}")

    if config.loudnorm:
        sbp_args += ("--postprocessor-args", f"-af {config.loudnorm}")

    sbp_args += (url,)

    cmd = " ".join(sbp_args)
    log.info(f"download_playlist: {cmd}")
    download_proc = await asyncio.create_subprocess_exec(*sbp_args)
    return download_proc


async def download_one_music(config, url: str, name: str = ""):
    """
    下载单首歌曲

    Args:
        config: 配置对象
        url: 歌曲 URL
        name: 文件名（可选）

    Returns:
        下载进程对象
    """
    title = "%(title)s.%(ext)s"
    if name:
        title = f"{name}.%(ext)s"
    sbp_args = (
        "yt-dlp",
        "--no-playlist",
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "--paths",
        config.download_path,
        "-o",
        title,
        "--ffmpeg-location",
        f"{config.ffmpeg_location}",
    )

    if config.proxy:
        sbp_args += ("--proxy", f"{config.proxy}")

    if config.enable_yt_dlp_cookies:
        sbp_args += ("--cookies", f"{config.yt_dlp_cookies_path}")

    if config.loudnorm:
        sbp_args += ("--postprocessor-args", f"-af {config.loudnorm}")

    sbp_args += (url,)

    cmd = " ".join(sbp_args)
    log.info(f"download_one_music: {cmd}")
    download_proc = await asyncio.create_subprocess_exec(*sbp_args)
    return download_proc


async def fetch_json_get(url: str, headers: dict, config) -> dict:
    """
    发起 GET 请求获取 JSON 数据

    Args:
        url: 请求 URL
        headers: 请求头
        config: 配置对象（用于代理设置）

    Returns:
        JSON 响应数据字典
    """
    connector = None
    proxy = None
    if config and config.proxy:
        connector = aiohttp.TCPConnector(
            ssl=False,  # 如需验证SSL证书，可改为True（需确保代理支持）
            limit=10,
        )
        proxy = config.proxy
    try:
        # 2. 传入代理配置创建ClientSession
        async with aiohttp.ClientSession(connector=connector) as session:
            # 3. 发起带代理的GET请求
            async with session.get(
                url,
                headers=headers,
                proxy=proxy,  # 传入格式化后的代理参数
                timeout=10,  # 超时时间（秒），避免无限等待
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    log.info(f"fetch_json_get: {url} success {data}")

                    # 确保返回结果为dict
                    if isinstance(data, dict):
                        return data
                    else:
                        log.warning(f"Expected dict, but got {type(data)}: {data}")
                        return {}
                else:
                    log.error(f"HTTP Error: {response.status} {url}")
                    return {}
    except aiohttp.ClientError as e:
        log.error(f"ClientError fetching {url} (proxy: {proxy}): {e}")
        return {}
    except asyncio.TimeoutError:
        log.error(f"Timeout fetching {url} (proxy: {proxy})")
        return {}
    except Exception as e:
        log.error(f"Unexpected error fetching {url} (proxy: {proxy}): {e}")
        return {}
    finally:
        # 4. 关闭连接器（避免资源泄漏）
        if connector and not connector.closed:
            await connector.close()


class LRUCache(OrderedDict):
    """LRU 缓存实现"""

    def __init__(self, max_size: int = 1000):
        super().__init__()
        self.max_size = max_size

    def __setitem__(self, key, value):
        if key in self:
            # 移动到末尾(最近使用)
            self.move_to_end(key)
        super().__setitem__(key, value)
        # 如果超出大小限制,删除最早使用的项
        if len(self) > self.max_size:
            self.popitem(last=False)

    def __getitem__(self, key):
        # 访问时移动到末尾(最近使用)
        if key in self:
            self.move_to_end(key)
        return super().__getitem__(key)


class MusicUrlCache:
    """音乐 URL 缓存管理器"""

    def __init__(self, default_expire_days: int = 1, max_size: int = 1000):
        self.cache = LRUCache(max_size)
        self.default_expire_days = default_expire_days
        self.log = logging.getLogger(__name__)

    async def get(self, url: str, headers: dict = None, config=None) -> str:
        """
        获取URL(优先从缓存获取,没有则请求API)

        Args:
            url: 原始URL
            headers: API请求需要的headers
            config: 配置对象

        Returns:
            str: 真实播放URL
        """
        # 先查询缓存
        cached_url = self._get_from_cache(url)
        if cached_url:
            self.log.info(f"Using cached url: {cached_url}")
            return cached_url

        # 缓存未命中,请求API
        return await self._fetch_from_api(url, headers, config)

    def _get_from_cache(self, url: str) -> str:
        """从缓存中获取URL"""
        try:
            cached_url, expire_time = self.cache[url]
            if time.time() > expire_time:
                # 缓存过期,删除
                del self.cache[url]
                return ""
            return cached_url
        except KeyError:
            return ""

    async def _fetch_from_api(self, url: str, headers: dict = None, config=None) -> str:
        """从API获取真实URL"""
        data = await fetch_json_get(url, headers or {}, config)

        if not isinstance(data, dict):
            self.log.error(f"Invalid API response format: {data}")
            return ""

        real_url = data.get("url")
        if not real_url:
            self.log.error(f"No url in API response: {data}")
            return ""

        # 获取过期时间
        expire_time = self._parse_expire_time(data)

        # 缓存结果
        self._set_cache(url, real_url, expire_time)
        self.log.info(
            f"Cached url, expire_time: {expire_time}, cache size: {len(self.cache)}"
        )
        return real_url

    def _parse_expire_time(self, data: dict) -> float | None:
        """解析API返回的过期时间"""
        try:
            extra = data.get("extra", {})
            expire_info = extra.get("expire", {})
            if expire_info and expire_info.get("canExpire"):
                expire_time = expire_info.get("time")
                if expire_time:
                    return float(expire_time)
        except Exception as e:
            self.log.warning(f"Failed to parse expire time: {e}")
        return None

    def _set_cache(self, url: str, real_url: str, expire_time: float = None):
        """设置缓存"""
        if expire_time is None:
            expire_time = time.time() + (self.default_expire_days * 24 * 3600)
        self.cache[url] = (real_url, expire_time)

    def clear(self):
        """清空缓存"""
        self.cache.clear()

    @property
    def size(self) -> int:
        """当前缓存大小"""
        return len(self.cache)


async def text_to_mp3(
    text: str, save_dir: str, voice: str = "zh-CN-XiaoxiaoNeural"
) -> str:
    """
    使用edge-tts将文本转换为MP3语音文件

    参数:
        text: 需要转换的文本内容
        save_dir: 保存MP3文件的目录路径
        voice: 语音模型（默认中文晓晓）

    返回:
        str: 生成的MP3文件完整路径
    """
    # 确保保存目录存在
    Path(save_dir).mkdir(parents=True, exist_ok=True)

    # 基于文本和语音模型生成唯一文件名（避免相同文本不同语音重复）
    content = f"{text}_{voice}".encode()
    file_hash = hashlib.md5(content).hexdigest()
    mp3_filename = f"{file_hash}.mp3"
    mp3_path = os.path.join(save_dir, mp3_filename)

    # 文件已存在直接返回路径
    if os.path.exists(mp3_path):
        return mp3_path

    # 调用edge-tts生成语音
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(mp3_path)
        log.info(f"语音文件生成成功: {mp3_path}")
    except Exception as e:
        raise RuntimeError(f"生成语音文件失败: {e}") from e

    return mp3_path
