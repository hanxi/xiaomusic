#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import base64
import copy
import difflib
import hashlib
import io
import json
import logging
import mimetypes
import os
import platform
import random
import re
import shutil
import string
import subprocess
import tempfile
import urllib.parse
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from http.cookies import SimpleCookie
from urllib.parse import urlparse

import aiohttp
import mutagen
from mutagen.asf import ASF
from mutagen.flac import FLAC
from mutagen.id3 import (
    APIC,
    ID3,
    TALB,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    USLT,
    Encoding,
    TextFrame,
    TimeStampTextFrame,
)
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from mutagen.wavpack import WavPack
from opencc import OpenCC
from PIL import Image
from requests.utils import cookiejar_from_dict

from xiaomusic.const import SUPPORT_MUSIC_TYPE

log = logging.getLogger(__package__)

cc = OpenCC("t2s")  # convert from Traditional Chinese to Simplified Chinese


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
def fuzzyfinder(user_input, collection, extra_search_index=None):
    return find_best_match(
        user_input, collection, cutoff=0.1, n=10, extra_search_index=extra_search_index
    )


def traditional_to_simple(to_convert: str):
    return cc.convert(to_convert)


# 关键词检测
def keyword_detection(user_input, str_list, n):
    # 过滤包含关键字的字符串
    matched, remains = [], []
    for item in str_list:
        if user_input in item:
            matched.append(item)
        else:
            remains.append(item)

    matched = sorted(
        matched,
        key=lambda s: difflib.SequenceMatcher(None, s, user_input).ratio(),
        reverse=True,  # 降序排序，越相似的越靠前
    )

    # 如果 n 是 -1，如果 n 大于匹配的数量，返回所有匹配的结果
    if n == -1 or n > len(matched):
        return matched, remains

    # 选择前 n 个匹配的结果
    remains = matched[n:] + remains
    return matched[:n], remains


def real_search(prompt, candidates, cutoff, n):
    matches, remains = keyword_detection(prompt, candidates, n=n)
    if len(matches) < n:
        # 如果没有准确关键词匹配，开始模糊匹配
        matches += difflib.get_close_matches(prompt, remains, n=n, cutoff=cutoff)
    return matches


def find_best_match(user_input, collection, cutoff=0.6, n=1, extra_search_index=None):
    lower_collection = {
        traditional_to_simple(item.lower()): item for item in collection
    }
    user_input = traditional_to_simple(user_input.lower())
    matches = real_search(user_input, lower_collection.keys(), cutoff, n)
    cur_matched_collection = [lower_collection[match] for match in matches]
    if len(matches) >= n or extra_search_index is None:
        return cur_matched_collection[:n]

    # 如果数量不满足，继续搜索
    lower_extra_search_index = {
        traditional_to_simple(k.lower()): v
        for k, v in extra_search_index.items()
        if v not in cur_matched_collection
    }
    matches = real_search(user_input, lower_extra_search_index.keys(), cutoff, n)
    cur_matched_collection += [lower_extra_search_index[match] for match in matches]
    return cur_matched_collection[:n]


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


def traverse_music_directory(directory, depth, exclude_dirs, support_extension):
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


def is_m4a(url):
    return url.endswith(".m4a")


async def _get_web_music_duration(session, url, ffmpeg_location, start=0, end=500):
    duration = 0
    headers = {"Range": f"bytes={start}-{end}"}
    async with session.get(url, headers=headers) as response:
        array_buffer = await response.read()
    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(array_buffer)
        try:
            if is_mp3(url):
                m = mutagen.mp3.MP3(tmp)
            elif is_m4a(url):
                return get_duration_by_ffprobe(tmp, ffmpeg_location)
            else:
                m = mutagen.File(tmp)
            duration = m.info.length
        except Exception as e:
            log.error(f"Error _get_web_music_duration: {e}")
    return duration


async def get_web_music_duration(url, ffmpeg_location="./ffmpeg/bin"):
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
            duration = await _get_web_music_duration(
                session, url, ffmpeg_location, start=0, end=500
            )
            if duration <= 0:
                duration = await _get_web_music_duration(
                    session, url, ffmpeg_location, start=0, end=3000
                )
    except Exception as e:
        log.error(f"Error get_web_music_duration: {e}")
    return duration, url


# 获取文件播放时长
async def get_local_music_duration(filename, ffmpeg_location="./ffmpeg/bin"):
    loop = asyncio.get_event_loop()
    duration = 0
    try:
        if is_mp3(filename):
            m = await loop.run_in_executor(None, mutagen.mp3.MP3, filename)
        elif is_m4a(filename):
            duration = get_duration_by_ffprobe(filename, ffmpeg_location)
            return duration
        else:
            m = await loop.run_in_executor(None, mutagen.File, filename)
        duration = m.info.length
    except Exception as e:
        log.warning(f"Error getting local music {filename} duration: {e}")
    return duration


def get_duration_by_ffprobe(file_path, ffmpeg_location):
    # 使用 ffprobe 获取文件的元数据，并以 JSON 格式输出
    result = subprocess.run(
        [
            os.path.join(ffmpeg_location, "ffprobe"),
            "-v",
            "error",  # 只输出错误信息，避免混杂在其他输出中
            "-show_entries",
            "format=duration",  # 仅显示时长
            "-of",
            "json",  # 以 JSON 格式输出
            file_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # 解析 JSON 输出
    ffprobe_output = json.loads(result.stdout)

    # 获取时长
    duration = float(ffprobe_output["format"]["duration"])

    return duration


def get_random(length):
    return "".join(random.sample(string.ascii_letters + string.digits, length))


# 深拷贝把敏感数据设置为*
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


def remove_id3_tags(input_file: str, config) -> str:
    audio = MP3(input_file, ID3=ID3)

    # 检查是否存在ID3 v2.3或v2.4标签
    if not (
        audio.tags
        and (audio.tags.version == (2, 3, 0) or audio.tags.version == (2, 4, 0))
    ):
        return None

    music_path = config.music_path
    temp_dir = config.temp_dir

    # 构造新文件的路径
    out_file_name = os.path.splitext(os.path.basename(input_file))[0]
    out_file_path = os.path.join(temp_dir, f"{out_file_name}.mp3")
    relative_path = os.path.relpath(out_file_path, music_path)

    # 路径相同的情况
    input_absolute_path = os.path.abspath(input_file)
    output_absolute_path = os.path.abspath(out_file_path)
    if input_absolute_path == output_absolute_path:
        log.info(f"File {input_file} = {out_file_path} . Skipping remove_id3_tags.")
        return None

    # 检查目标文件是否存在
    if os.path.exists(out_file_path):
        log.info(f"File {out_file_path} already exists. Skipping remove_id3_tags.")
        return relative_path

    # 开始去除（不再需要检查）
    # 拷贝文件
    shutil.copy(input_file, out_file_path)
    outaudio = MP3(out_file_path, ID3=ID3)
    # 删除ID3标签
    outaudio.delete()
    # 保存修改后的文件
    outaudio.save(padding=no_padding)
    log.info(f"File {out_file_path} remove_id3_tags ok.")
    return relative_path


def convert_file_to_mp3(input_file: str, config) -> str:
    music_path = config.music_path
    temp_dir = config.temp_dir

    out_file_name = os.path.splitext(os.path.basename(input_file))[0]
    out_file_path = os.path.join(temp_dir, f"{out_file_name}.mp3")
    relative_path = os.path.relpath(out_file_path, music_path)

    # 路径相同的情况
    input_absolute_path = os.path.abspath(input_file)
    output_absolute_path = os.path.abspath(out_file_path)
    if input_absolute_path == output_absolute_path:
        log.info(f"File {input_file} = {out_file_path} . Skipping convert_file_to_mp3.")
        return None

    absolute_music_path = os.path.abspath(music_path)
    if not input_absolute_path.startswith(absolute_music_path):
        log.error(f"Invalid input file path: {input_file}")
        return None

    # 检查目标文件是否存在
    if os.path.exists(out_file_path):
        log.info(f"File {out_file_path} already exists. Skipping convert_file_to_mp3.")
        return relative_path

    command = [
        os.path.join(config.ffmpeg_location, "ffmpeg"),
        "-i",
        input_absolute_path,
        "-f",
        "mp3",
        "-vn",
        "-y",
        out_file_path,
    ]

    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        log.exception(f"Error during conversion: {e}")
        return None

    log.info(f"File {input_file} to {out_file_path} convert_file_to_mp3 ok.")
    return relative_path


chinese_to_arabic = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
    "亿": 100000000,
}


def chinese_to_number(chinese):
    result = 0
    unit = 1
    num = 0
    # 处理特殊情况：以"十"开头时，在前面加"一"
    if chinese.startswith("十"):
        chinese = "一" + chinese

    # 如果只有一个字符且是单位，直接返回其值
    if len(chinese) == 1 and chinese_to_arabic[chinese] >= 10:
        return chinese_to_arabic[chinese]
    for char in reversed(chinese):
        if char in chinese_to_arabic:
            val = chinese_to_arabic[char]
            if val >= 10:
                if val > unit:
                    unit = val
                else:
                    unit *= val
            else:
                num += val * unit
    result += num

    return result


def list2str(li, verbose=False):
    if len(li) > 5 and not verbose:
        return f"{li[:2]} ... {li[-2:]} with len: {len(li)}"
    else:
        return f"{li}"


async def get_latest_version(package_name: str) -> str:
    url = f"https://pypi.org/pypi/{package_name}/json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data["info"]["version"]
            else:
                return None


@dataclass
class Metadata:
    title: str = ""
    artist: str = ""
    album: str = ""
    year: str = ""
    genre: str = ""
    picture: str = ""
    lyrics: str = ""

    def __init__(self, info=None):
        if info:
            self.title = info.get("title", "")
            self.artist = info.get("artist", "")
            self.album = info.get("album", "")
            self.year = info.get("year", "")
            self.genre = info.get("genre", "")
            self.picture = info.get("picture", "")
            self.lyrics = info.get("lyrics", "")


def _get_alltag_value(tags, k):
    v = tags.getall(k)
    if len(v) > 0:
        return _to_utf8(v[0])
    return ""


def _get_tag_value(tags, k):
    if k not in tags:
        return ""
    v = tags[k]
    return _to_utf8(v)


def _to_utf8(v):
    if isinstance(v, TextFrame) and not isinstance(v, TimeStampTextFrame):
        old_ts = "".join(v.text)
        if v.encoding == Encoding.LATIN1:
            bs = old_ts.encode("latin1")
            ts = bs.decode("GBK", errors="ignore")
            return ts
        return old_ts
    elif isinstance(v, list):
        return "".join(str(item) for item in v)
    return str(v)


def save_picture_by_base64(picture_base64_data, save_root, file_path):
    try:
        picture_data = base64.b64decode(picture_base64_data)
    except (TypeError, ValueError) as e:
        log.exception(f"Error decoding base64 data: {e}")
        return None
    return _save_picture(picture_data, save_root, file_path)


def _save_picture(picture_data, save_root, file_path):
    # 计算文件名的哈希值
    file_hash = hashlib.md5(file_path.encode("utf-8")).hexdigest()
    # 创建目录结构
    dir_path = os.path.join(save_root, file_hash[-6:])
    os.makedirs(dir_path, exist_ok=True)

    # 保存图片
    filename = os.path.basename(file_path)
    (name, _) = os.path.splitext(filename)
    picture_path = os.path.join(dir_path, f"{name}.jpg")

    try:
        _resize_save_image(picture_data, picture_path)
    except Exception as e:
        log.warning(f"Error _resize_save_image: {e}")
    return picture_path


def _resize_save_image(image_bytes, save_path, max_size=300):
    # 将 bytes 转换为 PIL Image 对象
    image = None
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image = image.convert("RGB")
    except Exception as e:
        log.warning(f"Error _resize_save_image: {e}")
        return

    # 获取原始尺寸
    original_width, original_height = image.size

    # 如果图片的宽度和高度都小于 max_size，则直接保存原始图片
    if original_width <= max_size and original_height <= max_size:
        image.save(save_path, format="JPEG")
        return

    # 计算缩放比例，保持等比缩放
    scaling_factor = min(max_size / original_width, max_size / original_height)

    # 计算新的尺寸
    new_width = int(original_width * scaling_factor)
    new_height = int(original_height * scaling_factor)

    resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    resized_image.save(save_path, format="JPEG")
    return save_path


def extract_audio_metadata(file_path, save_root):
    metadata = Metadata()

    audio = None
    try:
        audio = mutagen.File(file_path)
    except Exception as e:
        log.warning(f"Error extract_audio_metadata file: {file_path} {e}")
    if audio is None:
        return asdict(metadata)

    tags = audio.tags
    if tags is None:
        return asdict(metadata)

    if isinstance(audio, MP3):
        metadata.title = _get_tag_value(tags, "TIT2")
        metadata.artist = _get_tag_value(tags, "TPE1")
        metadata.album = _get_tag_value(tags, "TALB")
        metadata.year = _get_tag_value(tags, "TDRC")
        metadata.genre = _get_tag_value(tags, "TCON")
        metadata.lyrics = _get_alltag_value(tags, "USLT")
        for tag in tags.values():
            if isinstance(tag, APIC):
                metadata.picture = _save_picture(tag.data, save_root, file_path)
                break

    elif isinstance(audio, FLAC):
        metadata.title = _get_tag_value(tags, "TITLE")
        metadata.artist = _get_tag_value(tags, "ARTIST")
        metadata.album = _get_tag_value(tags, "ALBUM")
        metadata.year = _get_tag_value(tags, "DATE")
        metadata.genre = _get_tag_value(tags, "GENRE")
        if audio.pictures:
            metadata.picture = _save_picture(
                audio.pictures[0].data, save_root, file_path
            )
        if "lyrics" in audio:
            metadata.lyrics = audio["lyrics"][0]

    elif isinstance(audio, MP4):
        metadata.title = _get_tag_value(tags, "\xa9nam")
        metadata.artist = _get_tag_value(tags, "\xa9ART")
        metadata.album = _get_tag_value(tags, "\xa9alb")
        metadata.year = _get_tag_value(tags, "\xa9day")
        metadata.genre = _get_tag_value(tags, "\xa9gen")
        if "covr" in tags:
            metadata.picture = _save_picture(tags["covr"][0], save_root, file_path)

    elif isinstance(audio, OggVorbis):
        metadata.title = _get_tag_value(tags, "TITLE")
        metadata.artist = _get_tag_value(tags, "ARTIST")
        metadata.album = _get_tag_value(tags, "ALBUM")
        metadata.year = _get_tag_value(tags, "DATE")
        metadata.genre = _get_tag_value(tags, "GENRE")
        if "metadata_block_picture" in tags:
            picture = json.loads(base64.b64decode(tags["metadata_block_picture"][0]))
            metadata.picture = _save_picture(
                base64.b64decode(picture["data"]), save_root, file_path
            )

    elif isinstance(audio, ASF):
        metadata.title = _get_tag_value(tags, "Title")
        metadata.artist = _get_tag_value(tags, "Author")
        metadata.album = _get_tag_value(tags, "WM/AlbumTitle")
        metadata.year = _get_tag_value(tags, "WM/Year")
        metadata.genre = _get_tag_value(tags, "WM/Genre")
        if "WM/Picture" in tags:
            metadata.picture = _save_picture(
                tags["WM/Picture"][0].value, save_root, file_path
            )

    elif isinstance(audio, WavPack):
        metadata.title = _get_tag_value(tags, "Title")
        metadata.artist = _get_tag_value(tags, "Artist")
        metadata.album = _get_tag_value(tags, "Album")
        metadata.year = _get_tag_value(tags, "Year")
        metadata.genre = _get_tag_value(tags, "Genre")
        if audio.pictures:
            metadata.picture = _save_picture(
                audio.pictures[0].data, save_root, file_path
            )

    elif isinstance(audio, WAVE):
        metadata.title = _get_tag_value(tags, "Title")
        metadata.artist = _get_tag_value(tags, "Artist")

    return asdict(metadata)


def set_music_tag_to_file(file_path, info):
    audio = mutagen.File(file_path, easy=True)
    if audio is None:
        log.error(f"Unable to open file {file_path}")
        return "Unable to open file"

    if isinstance(audio, MP3):
        _set_mp3_tags(audio, info)
    elif isinstance(audio, FLAC):
        _set_flac_tags(audio, info)
    elif isinstance(audio, MP4):
        _set_mp4_tags(audio, info)
    elif isinstance(audio, OggVorbis):
        _set_ogg_tags(audio, info)
    elif isinstance(audio, ASF):
        _set_asf_tags(audio, info)
    elif isinstance(audio, WAVE):
        _set_wave_tags(audio, info)
    else:
        log.error(f"Unsupported file type for {file_path}")
        return "Unsupported file type"

    try:
        audio.save()
        log.info(f"Tags saved successfully to {file_path}")
        return "OK"
    except Exception as e:
        log.exception(f"Error saving tags: {e}")
        return "Error saving tags"


def _set_mp3_tags(audio, info):
    audio["TIT2"] = TIT2(encoding=3, text=info.title)
    audio["TPE1"] = TPE1(encoding=3, text=info.artist)
    audio["TALB"] = TALB(encoding=3, text=info.album)
    audio["TDRC"] = TDRC(encoding=3, text=info.year)
    audio["TCON"] = TCON(encoding=3, text=info.genre)
    if info.lyrics:
        audio["USLT"] = USLT(encoding=3, lang="eng", text=info.lyrics)
    if info.picture:
        with open(info.picture, "rb") as img_file:
            image_data = img_file.read()
        audio["APIC"] = APIC(
            encoding=3, mime="image/jpeg", type=3, desc="Cover", data=image_data
        )


def _set_flac_tags(audio, info):
    audio["TITLE"] = info.title
    audio["ARTIST"] = info.artist
    audio["ALBUM"] = info.album
    audio["DATE"] = info.year
    audio["GENRE"] = info.genre
    if info.lyrics:
        audio["LYRICS"] = info.lyrics
    if info.picture:
        with open(info.picture, "rb") as img_file:
            image_data = img_file.read()
        audio.add_picture(image_data)


def _set_mp4_tags(audio, info):
    audio["\xa9nam"] = info.title
    audio["\xa9ART"] = info.artist
    audio["\xa9alb"] = info.album
    audio["\xa9day"] = info.year
    audio["\xa9gen"] = info.genre
    if info.picture:
        with open(info.picture, "rb") as img_file:
            image_data = img_file.read()
        audio["covr"] = [image_data]


def _set_ogg_tags(audio, info):
    audio["TITLE"] = info.title
    audio["ARTIST"] = info.artist
    audio["ALBUM"] = info.album
    audio["DATE"] = info.year
    audio["GENRE"] = info.genre
    if info.lyrics:
        audio["LYRICS"] = info.lyrics
    if info.picture:
        with open(info.picture, "rb") as img_file:
            image_data = img_file.read()
        audio["metadata_block_picture"] = base64.b64encode(image_data).decode()


def _set_asf_tags(audio, info):
    audio["Title"] = info.title
    audio["Author"] = info.artist
    audio["WM/AlbumTitle"] = info.album
    audio["WM/Year"] = info.year
    audio["WM/Genre"] = info.genre
    if info.picture:
        with open(info.picture, "rb") as img_file:
            image_data = img_file.read()
        audio["WM/Picture"] = image_data


def _set_wave_tags(audio, info):
    audio["Title"] = info.title
    audio["Artist"] = info.artist


# 下载播放列表
async def download_playlist(config, url, dirname):
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

    sbp_args += (url,)

    cmd = " ".join(sbp_args)
    log.info(f"download_playlist: {cmd}")
    download_proc = await asyncio.create_subprocess_exec(*sbp_args)
    return download_proc


# 下载一首歌曲
async def download_one_music(config, url, name=""):
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

    sbp_args += (url,)

    cmd = " ".join(sbp_args)
    log.info(f"download_one_music: {cmd}")
    download_proc = await asyncio.create_subprocess_exec(*sbp_args)
    return download_proc


def _longest_common_prefix(file_names):
    if not file_names:
        return ""

    # 将第一个文件名作为初始前缀
    prefix = file_names[0]

    for file_name in file_names[1:]:
        while not file_name.startswith(prefix):
            # 如果当前文件名不以prefix开头，则缩短prefix
            prefix = prefix[:-1]
            if not prefix:
                return ""

    return prefix


# 移除目录下文件名前缀相同的
def remove_common_prefix(directory):
    files = os.listdir(directory)

    # 获取所有文件的前缀
    common_prefix = _longest_common_prefix(files)

    log.info(f'Common prefix identified: "{common_prefix}"')

    pattern = re.compile(r"^(\d+)\s+\d*(.+?)\.(.*$)")
    for filename in files:
        if filename == common_prefix:
            continue
        # 检查文件名是否以共同前缀开头
        if filename.startswith(common_prefix):
            # 构造新的文件名
            new_filename = filename[len(common_prefix) :]
            match = pattern.search(new_filename.strip())
            if match:
                num = match.group(1)
                name = match.group(2).replace(".", " ").strip()
                suffix = match.group(3)
                new_filename = f"{num}.{name}.{suffix}"
            # 生成完整的文件路径
            old_file_path = os.path.join(directory, filename)
            new_file_path = os.path.join(directory, new_filename)

            # 重命名文件
            os.rename(old_file_path, new_file_path)
            log.debug(f'Renamed: "{filename}" to "{new_filename}"')


def try_add_access_control_param(config, url):
    if config.disable_httpauth:
        return url

    url_parts = urllib.parse.urlparse(url)
    file_path = urllib.parse.unquote(url_parts.path)
    correct_code = hashlib.sha256(
        (file_path + config.httpauth_username + config.httpauth_password).encode(
            "utf-8"
        )
    ).hexdigest()
    log.debug(f"rewrite url: [{file_path}, {correct_code}]")

    # make new url
    parsed_get_args = dict(urllib.parse.parse_qsl(url_parts.query))
    parsed_get_args.update({"code": correct_code})
    encoded_get_args = urllib.parse.urlencode(parsed_get_args, doseq=True)
    new_url = urllib.parse.ParseResult(
        url_parts.scheme,
        url_parts.netloc,
        url_parts.path,
        url_parts.params,
        encoded_get_args,
        url_parts.fragment,
    ).geturl()

    return new_url


# 判断文件在不在排除目录列表
def not_in_dirs(filename, ignore_absolute_dirs):
    file_absolute_path = os.path.abspath(filename)
    file_dir = os.path.dirname(file_absolute_path)
    for ignore_dir in ignore_absolute_dirs:
        if file_dir.startswith(ignore_dir):
            log.info(f"{file_dir} in {ignore_dir}")
            return False  # 文件在排除目录中

    return True  # 文件不在排除目录中


def is_docker():
    return os.path.exists("/app/.dockerenv")


async def restart_xiaomusic():
    # 重启 xiaomusic 程序
    sbp_args = (
        "supervisorctl",
        "restart",
        "xiaomusic",
    )

    cmd = " ".join(sbp_args)
    log.info(f"restart_xiaomusic: {cmd}")
    await asyncio.sleep(2)
    proc = await asyncio.create_subprocess_exec(*sbp_args)
    exit_code = await proc.wait()  # 等待子进程完成
    log.info(f"restart_xiaomusic completed with exit code {exit_code}")
    return exit_code


async def update_version(version: str, lite: bool = True):
    if not is_docker():
        ret = "xiaomusic 更新只能在 docker 中进行"
        log.info(ret)
        return ret
    lite_tag = ""
    if lite:
        lite_tag = "-lite"
    arch = get_os_architecture()
    if "unknown" in arch:
        log.warning(f"update_version failed: {arch}")
        return arch
    # https://github.com/hanxi/xiaomusic/releases/download/main/app-amd64-lite.tar.gz
    url = f"https://gproxy.hanxi.cc/proxy/hanxi/xiaomusic/releases/download/{version}/app-{arch}{lite_tag}.tar.gz"
    target_directory = "/app"
    return await download_and_extract(url, target_directory)


def get_os_architecture():
    """
    获取操作系统架构类型：amd64、arm64、arm-v7。

    Returns:
        str: 架构类型
    """
    arch = platform.machine().lower()

    if arch in ("x86_64", "amd64"):
        return "amd64"
    elif arch in ("aarch64", "arm64"):
        return "arm64"
    elif "arm" in arch or "armv7" in arch:
        return "arm-v7"
    else:
        return f"unknown architecture: {arch}"


async def download_and_extract(url: str, target_directory: str):
    ret = "OK"
    # 创建目标目录
    os.makedirs(target_directory, exist_ok=True)

    # 使用 aiohttp 异步下载文件
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                file_name = os.path.join(target_directory, url.split("/")[-1])
                file_name = os.path.normpath(file_name)
                if not file_name.startswith(target_directory):
                    log.warning(f"Invalid file path: {file_name}")
                    return
                with open(file_name, "wb") as f:
                    # 以块的方式下载文件，防止内存占用过大
                    async for chunk in response.content.iter_any():
                        f.write(chunk)
                log.info(f"文件下载完成: {file_name}")

                # 解压下载的文件
                if file_name.endswith(".tar.gz"):
                    await extract_tar_gz(file_name, target_directory)
                else:
                    ret = f"下载失败, 包有问题: {file_name}"
                log.warning(ret)

            else:
                ret = f"下载失败, 状态码: {response.status}"
                log.warning(ret)
    return ret


async def extract_tar_gz(file_name: str, target_directory: str):
    # 使用 asyncio.create_subprocess_exec 执行 tar 解压命令
    command = ["tar", "-xzvf", file_name, "-C", target_directory]
    # 启动子进程执行解压命令
    await asyncio.create_subprocess_exec(*command)
    # 不等待子进程完成
    log.info(f"extract_tar_gz ing {file_name}")


def chmodfile(file_path: str):
    try:
        os.chmod(file_path, 0o775)
    except Exception as e:
        log.info(f"chmodfile failed: {e}")


def chmoddir(dir_path: str):
    # 获取指定目录下的所有文件和子目录
    for item in os.listdir(dir_path):
        item_path = os.path.join(dir_path, item)
        # 确保是文件，且不是目录
        if os.path.isfile(item_path):
            try:
                os.chmod(item_path, 0o775)
                log.info(f"Changed permissions of file: {item_path}")
            except Exception as e:
                log.info(f"chmoddir failed: {e}")
