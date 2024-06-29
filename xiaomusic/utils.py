#!/usr/bin/env python3
from __future__ import annotations

import difflib
import os
import random
import re
import string
import tempfile
from collections.abc import AsyncIterator
from http.cookies import SimpleCookie
from urllib.parse import urlparse

import aiohttp
import mutagen
import requests
from requests.utils import cookiejar_from_dict

from xiaomusic.const import SUPPORT_MUSIC_TYPE


### HELP FUNCTION ###
def parse_cookie_string(cookie_string):
    cookie = SimpleCookie()
    cookie.load(cookie_string)
    cookies_dict = {k: m.value for k, m in cookie.items()}
    return cookiejar_from_dict(cookies_dict, cookiejar=None, overwrite=True)


_no_elapse_chars = re.compile(r"([「」『』《》“”'\"()（）]|(?<!-)-(?!-))", re.UNICODE)


def calculate_tts_elapse(text: str) -> float:
    # for simplicity, we use a fixed speed
    speed = 4.5  # this value is picked by trial and error
    # Exclude quotes and brackets that do not affect the total elapsed time
    return len(_no_elapse_chars.sub("", text)) / speed


_ending_punctuations = ("。", "？", "！", "；", ".", "?", "!", ";")


async def split_sentences(text_stream: AsyncIterator[str]) -> AsyncIterator[str]:
    cur = ""
    async for text in text_stream:
        cur += text
        if cur.endswith(_ending_punctuations):
            yield cur
            cur = ""
    if cur:
        yield cur


### for edge-tts utils ###
def find_key_by_partial_string(dictionary: dict[str, str], partial_key: str) -> str:
    for key, value in dictionary.items():
        if key in partial_key:
            return value


def validate_proxy(proxy_str: str) -> bool:
    """Do a simple validation of the http proxy string."""

    parsed = urlparse(proxy_str)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Proxy scheme must be http or https")
    if not (parsed.hostname and parsed.port):
        raise ValueError("Proxy hostname and port must be set")

    return True


# 模糊搜索
def fuzzyfinder(user_input, collection):
    return difflib.get_close_matches(user_input, collection, n=10, cutoff=0.1)


def find_best_match(user_input, collection, cutoff=0.6):
    matches = difflib.get_close_matches(user_input, collection, n=1, cutoff=cutoff)
    return matches[0] if matches else None


# 歌曲排序
def custom_sort_key(s):
    # 使用正则表达式分别提取字符串的数字前缀和数字后缀
    prefix_match = re.match(r"^(\d+)", s)
    suffix_match = re.search(r"(\d+)$", s)

    numeric_prefix = int(prefix_match.group(0)) if prefix_match else None
    numeric_suffix = int(suffix_match.group(0)) if suffix_match else None

    if numeric_prefix is not None:
        # 如果前缀是数字，先按前缀数字排序，再按整个字符串排序
        return (0, numeric_prefix, s)
    elif numeric_suffix is not None:
        # 如果后缀是数字，先按前缀字符排序，再按后缀数字排序
        return (1, s[: suffix_match.start()], numeric_suffix)
    else:
        # 如果前缀和后缀都不是数字，按字典序排序
        return (2, s)


# fork from https://gist.github.com/dougthor42/001355248518bc64d2f8
def walk_to_depth(root, depth=None, *args, **kwargs):
    """
    Wrapper around os.walk that stops after going down `depth` folders.
    I had my own version, but it wasn't as efficient as
    http://stackoverflow.com/a/234329/1354930, so I modified to be more
    similar to nosklo's answer.
    However, nosklo's answer doesn't work if topdown=False, so I kept my
    version.
    """
    # Let people use this as a standard `os.walk` function.
    if depth is None:
        return os.walk(root, *args, **kwargs)

    # remove any trailing separators so that our counts are correct.
    root = root.rstrip(os.path.sep)

    def main_func(root, depth, *args, **kwargs):
        """Faster because it skips traversing dirs that are too deep."""
        root_depth = root.count(os.path.sep)
        for dirpath, dirnames, filenames in os.walk(root, *args, **kwargs):
            yield (dirpath, dirnames, filenames)

            # calculate how far down we are.
            current_folder_depth = dirpath.count(os.path.sep)
            if current_folder_depth >= root_depth + depth:
                del dirnames[:]

    def fallback_func(root, depth, *args, **kwargs):
        """Slower, but works when topdown is False"""
        root_depth = root.count(os.path.sep)
        for dirpath, dirnames, filenames in os.walk(root, *args, **kwargs):
            current_folder_depth = dirpath.count(os.path.sep)
            if current_folder_depth <= root_depth + depth:
                yield (dirpath, dirnames, filenames)

    # there's gotta be a better way do do this...
    try:
        if args[0] is False:
            yield from fallback_func(root, depth, *args, **kwargs)
            return
        else:
            yield from main_func(root, depth, *args, **kwargs)
            return
    except IndexError:
        pass

    try:
        if kwargs["topdown"] is False:
            yield from fallback_func(root, depth, *args, **kwargs)
            return
        else:
            yield from main_func(root, depth, *args, **kwargs)
            return
    except KeyError:
        yield from main_func(root, depth, *args, **kwargs)
        return


def downloadfile(url):
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

    # 发起请求
    response = requests.get(cleaned_url, timeout=5)  # 增加超时以避免长时间挂起
    response.raise_for_status()  # 如果响应不是200，引发HTTPError异常
    return response.text


async def _get_web_music_duration(session, url, start=0, end=500):
    duration = 0
    headers = {"Range": f"bytes={start}-{end}"}
    async with session.get(url, headers=headers) as response:
        array_buffer = await response.read()
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(array_buffer)
        name = tmp.name

    try:
        m = mutagen.File(name)
        duration = m.info.length
    except Exception:
        pass
    os.remove(name)
    return duration


async def get_web_music_duration(url, start=0, end=500):
    duration = 0
    try:
        parsed_url = urlparse(url)
        file_path = parsed_url.path
        _, extension = os.path.splitext(file_path)
        if extension.lower() not in SUPPORT_MUSIC_TYPE:
            cleaned_url = parsed_url.geturl()
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    cleaned_url,
                    allow_redirects=True,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36"
                    },
                ) as response:
                    url = str(response.url)
        # 设置总超时时间为3秒
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            duration = await _get_web_music_duration(session, url, start=0, end=500)
            if duration <= 0:
                duration = await _get_web_music_duration(
                    session, url, start=0, end=1000
                )
    except Exception:
        pass
    return duration, url


# 获取文件播放时长
def get_local_music_duration(filename):
    duration = 0
    try:
        m = mutagen.File(filename)
        duration = m.info.length
    except Exception:
        pass
    return duration


def get_random(length):
    return "".join(random.sample(string.ascii_letters + string.digits, length))
