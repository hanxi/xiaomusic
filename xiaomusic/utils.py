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
from mutagen.id3 import APIC, ID3, Encoding, TextFrame, TimeStampTextFrame
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

    # 如果 n 是 -1，如果 n 大于匹配的数量，返回所有匹配的结果
    if n == -1 or n > len(matched):
        return matched, remains

    # 随机选择 n 个匹配的结果
    return random.sample(matched, n), remains


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
        log.error(f"Error getting local music {filename} duration: {e}")
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


def get_temp_dir(music_path: str):
    # 指定临时文件的目录为 music_path 目录下的 tmp 文件夹
    temp_dir = os.path.join(music_path, "tmp")
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)  # 确保目录存在
    return temp_dir


def remove_id3_tags(input_file: str, config) -> str:
    music_path = config.music_path
    temp_dir = get_temp_dir(music_path)

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

    audio = MP3(input_file, ID3=ID3)

    # 检查是否存在ID3 v2.3或v2.4标签
    if audio.tags and (
        audio.tags.version == (2, 3, 0) or audio.tags.version == (2, 4, 0)
    ):
        # 拷贝文件
        shutil.copy(input_file, out_file_path)
        outaudio = MP3(out_file_path, ID3=ID3)
        # 删除ID3标签
        outaudio.delete()
        # 保存修改后的文件
        outaudio.save(padding=no_padding)
        log.info(f"File {out_file_path} remove_id3_tags ok.")
        return relative_path

    return relative_path


def convert_file_to_mp3(input_file: str, config) -> str:
    music_path = config.music_path
    temp_dir = get_temp_dir(music_path)

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
        num = 0
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
        return "".join(v)
    return str(v)


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
        log.exception(f"Error _resize_save_image: {e}")
    return picture_path


def _resize_save_image(image_bytes, save_path, max_size=300):
    # 将 bytes 转换为 PIL Image 对象
    image = Image.open(io.BytesIO(image_bytes))
    image = image.convert("RGB")

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
    audio = mutagen.File(file_path)
    metadata = Metadata()
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


# 下载播放列表
async def download_playlist(config, url, dirname):
    title = f"{dirname}/%(title)s.%(ext)s"
    sbp_args = (
        "yt-dlp",
        "--yes-playlist",
        "-x",
        "--audio-format",
        "mp3",
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

    for filename in files:
        if filename == common_prefix:
            continue
        # 检查文件名是否以共同前缀开头
        if filename.startswith(common_prefix):
            # 构造新的文件名
            new_filename = filename[len(common_prefix) :]
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
