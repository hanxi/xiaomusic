#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import copy
import difflib
import logging
import mimetypes
import os
import random
import re
import shutil
import string
import tempfile
from collections.abc import AsyncIterator
from http.cookies import SimpleCookie
from urllib.parse import urlparse

import aiohttp
import mutagen
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
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
    lower_collection = {item.lower(): item for item in collection}
    user_input = user_input.lower()
    matches = difflib.get_close_matches(
        user_input, lower_collection.keys(), n=10, cutoff=0.1
    )
    return [lower_collection[match] for match in matches]


def find_best_match(user_input, collection, cutoff=0.6):
    lower_collection = {item.lower(): item for item in collection}
    user_input = user_input.lower()
    matches = difflib.get_close_matches(
        user_input, lower_collection.keys(), n=1, cutoff=cutoff
    )
    return lower_collection[matches[0]] if matches else None


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


def _get_depth_path(root, directory, depth):
    # 计算当前目录的深度
    relative_path = root[len(directory) :].strip(os.sep)
    path_parts = relative_path.split(os.sep)
    if len(path_parts) >= depth:
        return os.path.join(directory, *path_parts[:depth])
    else:
        return root


def _append_files_result(result, root, joinpath, files, support_extension):
    dir_name = os.path.basename(root)
    if dir_name not in result:
        result[dir_name] = []
    for file in files:
        # 过滤隐藏文件
        if file.startswith("."):
            continue
        # 过滤文件后缀
        (name, extension) = os.path.splitext(file)
        if extension.lower() not in support_extension:
            continue

        result[dir_name].append(os.path.join(joinpath, file))


def traverse_music_directory(
    directory, depth=10, exclude_dirs=None, support_extension=None
):
    result = {}
    for root, dirs, files in os.walk(directory, followlinks=True):
        # 忽略排除的目录
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        # 计算当前目录的深度
        current_depth = root[len(directory) :].count(os.sep) + 1
        if current_depth > depth:
            depth_path = _get_depth_path(root, directory, depth - 1)
            _append_files_result(result, depth_path, root, files, support_extension)
        else:
            _append_files_result(result, root, root, files, support_extension)
    return result


async def downloadfile(url):
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


def is_mp3(url):
    mt = mimetypes.guess_type(url)
    if mt and mt[0] == "audio/mpeg":
        return True
    return False


async def _get_web_music_duration(session, url, start=0, end=500):
    duration = 0
    headers = {"Range": f"bytes={start}-{end}"}
    async with session.get(url, headers=headers) as response:
        array_buffer = await response.read()
    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(array_buffer)
        try:
            if is_mp3(url):
                m = mutagen.mp3.MP3(tmp)
            else:
                m = mutagen.File(tmp)
            duration = m.info.length
        except Exception as e:
            logging.error(f"Error _get_web_music_duration: {e}")
    return duration


async def get_web_music_duration(url):
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
                    session, url, start=0, end=3000
                )
    except Exception as e:
        logging.error(f"Error get_web_music_duration: {e}")
    return duration, url


# 获取文件播放时长
async def get_local_music_duration(filename):
    loop = asyncio.get_event_loop()
    duration = 0
    try:
        if is_mp3(filename):
            m = await loop.run_in_executor(None, mutagen.mp3.MP3, filename)
        else:
            m = await loop.run_in_executor(None, mutagen.File, filename)
        if m and m.info:
            duration = m.info.length
    except Exception as e:
        logging.error(f"Error getting local music duration: {e}")
    return duration


def get_random(length):
    return "".join(random.sample(string.ascii_letters + string.digits, length))


# 深拷贝把敏感数据设置位*
def deepcopy_data_no_sensitive_info(data, fields_to_anonymize=None):
    if fields_to_anonymize is None:
        fields_to_anonymize = [
            "account",
            "password",
            "httpauth_username",
            "httpauth_password",
        ]

    copy_data = copy.deepcopy(data)

    # 检查copy_data是否是字典或具有属性的对象
    if isinstance(copy_data, dict):
        # 对字典进行处理
        for field in fields_to_anonymize:
            if field in copy_data:
                copy_data[field] = "******"
    else:
        # 对对象进行处理
        for field in fields_to_anonymize:
            if hasattr(copy_data, field):
                setattr(copy_data, field, "******")

    return copy_data


# k1:v1,k2:v2
def parse_str_to_dict(s, d1=",", d2=":"):
    # 初始化一个空字典
    result = {}
    parts = s.split(d1)

    for part in parts:
        # 根据冒号切割
        subparts = part.split(d2)
        if len(subparts) == 2:  # 防止数据不是成对出现
            k, v = subparts
            result[k] = v

    return result


# remove mp3 file id3 tag and padding to reduce delay
def no_padding(info):
    # this will remove all padding
    return 0


def remove_id3_tags(file_path):
    audio = MP3(file_path, ID3=ID3)
    change = False

    # 检查是否存在ID3 v2.3或v2.4标签
    if audio.tags and (
        audio.tags.version == (2, 3, 0) or audio.tags.version == (2, 4, 0)
    ):
        # 构造新文件的路径
        new_file_path = file_path + ".bak"

        # 备份原始文件为新文件
        shutil.copy(file_path, new_file_path)

        # 删除ID3标签
        audio.delete()

        # 删除padding
        audio.save(padding=no_padding)

        # 保存修改后的文件
        audio.save()

        change = True

    return change
