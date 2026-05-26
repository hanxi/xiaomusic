#!/usr/bin/env python3
"""音乐文件处理相关工具函数"""

import asyncio
import base64
import hashlib
import io
import json
import logging
import mimetypes
import os
import re
import shutil
import struct
import subprocess
import tempfile
from dataclasses import (
    asdict,
    dataclass,
)
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
from PIL import Image

from xiaomusic.const import SUPPORT_MUSIC_TYPE
from xiaomusic.utils.file_utils import mark_audio_as_failed
from xiaomusic.utils.network_utils import download_plugin_audio

log = logging.getLogger(__package__)


@dataclass
class Metadata:
    """音乐元数据"""

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


def is_mp3(url: str) -> bool:
    """判断是否为 MP3 文件"""
    mt = mimetypes.guess_type(url)
    if mt and mt[0] == "audio/mpeg":
        return True
    return False


def is_m4a(url: str) -> bool:
    """判断是否为 M4A 文件"""
    return url.endswith(".m4a")


async def _get_web_music_duration(
    session, url: str, config, cache_path: str = None
) -> float:
    """
    异步获取网络音乐文件的完整内容并获取其时长。
    实现：下载 -> 测速 -> 质检 -> 失败物理清理

    下载完整文件，写入临时文件后调用本地工具（如 ffprobe）获取音频时长

    Args:
        session: aiohttp.ClientSession 实例
        url: 音乐文件的 URL 地址
        config: 包含配置信息的对象（如 ffmpeg 路径）

    Returns:
        返回音频的持续时间（秒），如果失败则返回 0
    """
    target_path = cache_path
    is_temp = False

    # 免疫机制。如果是本地 TTS、静音文件、系统提示音，绝对不建墓碑，直接测本地时长
    is_system_or_tts = (
        "music/tmp/" in url or "silence.mp3" in url or "xiaomusic_" in url
    )
    if is_system_or_tts:
        from urllib.parse import urlparse

        parsed_url = urlparse(url)
        # parsed_url.path 拿到的直接就是 "/music/tmp/xxx.mp3" 或 "/static/silence.mp3"
        local_path = parsed_url.path.lstrip("/")

        if os.path.exists(local_path):
            return await get_local_music_duration(local_path, config)
        return 0

    # 如果没有开启缓存或未传递缓存路径，使用用完即焚的临时文件
    if not target_path:
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".tmp")
        target_path = tmp_file.name
        tmp_file.close()
        is_temp = True
    else:
        # 确保父目录一定存在
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

    try:
        # 调用 network_utils 的流式下载工具 (这里最耗时)
        success = await download_plugin_audio(session, url, target_path)
        if not success:
            # 如果是由于网络 404/401 导致的下载失败，不在这里立物理墓碑！
            # 留给它未来网络恢复后改过自新的机会，仅返回 0 时长让前线去切歌
            log.warning(f"网络音频流下载失败(可能是临时故障): {url[:100]}")
            return 0

        # 测量本地文件时长
        duration = await get_local_music_duration(target_path, config)

        # 业务质检逻辑：防盗链和残次品拦截 (仅针对持久化缓存)
        if not is_temp and cache_path:
            # 只有网络畅通、文件成功下到本地，但确诊时长小于10秒（版权到期给的假静音音频）
            # 这才是真正的永久性下架，必须立下 .failed 墓碑。
            if duration < 10:
                log.warning(
                    f"检测到高仿无效资源（时长 {duration}s < 10s），确诊版权下架，触发负向缓存立碑"
                )
                mark_audio_as_failed(target_path)
                return 0

        return duration

    except Exception as e:
        log.error(f"Error _get_web_music_duration: {e}")
        return 0
    finally:
        # 无论成功失败，只要是临时文件，立刻销毁现场
        if is_temp and os.path.exists(target_path):
            try:
                os.unlink(target_path)
            except Exception as e:
                log.error(f"清理临时文件失败: {e}")


async def get_web_music_duration(
    url: str, config, cache_path: str = None
) -> tuple[float, str]:
    """
    获取网络音乐时长

    Args:
        url: 音乐 URL
        config: 配置对象

    Returns:
        (时长(秒), 最终URL)
    """
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
        # 设置总超时时间为60秒
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            duration = await _get_web_music_duration(session, url, config, cache_path)
    except Exception as e:
        log.error(f"获取网络音乐时长失败: {e}")
    return duration, url


async def get_local_music_duration(filename: str, config) -> float:
    """
    获取本地音乐文件播放时长

    Args:
        filename: 文件路径
        config: 配置对象

    Returns:
        时长(秒)
    """
    duration = 0
    if config.get_duration_type == "ffprobe":
        duration = get_duration_by_ffprobe(filename, config.ffmpeg_location)
    else:
        duration = await get_duration_by_mutagen(filename)

    # 换个方式重试一次
    if duration == 0:
        if config.get_duration_type != "ffprobe":
            duration = get_duration_by_ffprobe(filename, config.ffmpeg_location)
        else:
            duration = await get_duration_by_mutagen(filename)

    return duration


async def get_duration_by_mutagen(file_path: str) -> float:
    """使用 mutagen 获取音乐时长"""
    duration = 0
    try:
        loop = asyncio.get_event_loop()
        if is_mp3(file_path):
            m = await loop.run_in_executor(None, mutagen.mp3.MP3, file_path)
        else:
            m = await loop.run_in_executor(None, mutagen.File, file_path)
        duration = m.info.length
    except Exception as e:
        log.warning(f"Error getting local music {file_path} duration: {e}")
    return duration


def get_duration_by_ffprobe(file_path: str, ffmpeg_location: str) -> float:
    """使用 ffprobe 获取音乐时长"""
    duration = 0
    try:
        # 构造 ffprobe 命令参数
        cmd_args = [
            os.path.join(ffmpeg_location, "ffprobe"),
            "-v",
            "error",  # 只输出错误信息，避免混杂在其他输出中
            "-show_entries",
            "format=duration",  # 仅显示时长
            "-of",
            "json",  # 以 JSON 格式输出
            file_path,
        ]

        # 输出待执行的完整命令
        full_command = " ".join(cmd_args)
        log.info(f"待执行的完整命令 ffprobe command: {full_command}")

        # 使用 ffprobe 获取文件的元数据，并以 JSON 格式输出
        result = subprocess.run(
            cmd_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # 输出命令执行结果
        log.info(
            f"命令执行结果 command result - return code: {result.returncode}, stdout: {result.stdout}"
        )

        # 解析 JSON 输出
        ffprobe_output = json.loads(result.stdout)

        # 获取时长
        duration = float(ffprobe_output["format"]["duration"])
        log.info(
            f"Successfully extracted duration: {duration} seconds for file: {file_path}"
        )

    except Exception as e:
        log.warning(f"Error getting local music {file_path} duration: {e}")
    return duration


def no_padding(info) -> int:
    """移除 MP3 文件的 padding"""
    # this will remove all padding
    return 0


def remove_id3_tags(input_file: str, config) -> str:
    """
    移除 MP3 文件的 ID3 标签以减少延迟

    Args:
        input_file: 输入文件路径
        config: 配置对象

    Returns:
        处理后的相对路径，如果无需处理则返回 None
    """
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
    """
    转换音频文件为 MP3 格式

    Args:
        input_file: 输入文件路径
        config: 配置对象

    Returns:
        转换后的相对路径，如果无需转换则返回 None
    """
    music_path = config.music_path
    temp_dir = config.temp_dir

    absolute_music_path = os.path.abspath(music_path)

    out_file_name = os.path.splitext(os.path.basename(input_file))[0]
    out_file_path = os.path.join(temp_dir, f"{out_file_name}.mp3")
    relative_path = os.path.relpath(out_file_path, music_path)

    # 路径相同的情况
    input_absolute_path = os.path.abspath(input_file)
    output_absolute_path = os.path.abspath(out_file_path)
    if input_absolute_path == output_absolute_path:
        log.info(f"File {input_file} = {out_file_path} . Skipping convert_file_to_mp3.")
        return None

    # 确保输入文件位于音乐目录下
    if not input_absolute_path.startswith(absolute_music_path + os.sep):
        log.error(f"Invalid input file path: {input_file}")
        return None

    # 确保输出文件位于预期的临时目录或音乐目录下
    temp_dir_abs = os.path.abspath(temp_dir)
    if not (
        output_absolute_path.startswith(temp_dir_abs + os.sep)
        or output_absolute_path.startswith(absolute_music_path + os.sep)
    ):
        log.error(f"Invalid output file path: {out_file_path}")
        return None

    # 检查目标文件是否存在
    if os.path.exists(out_file_path):
        log.info(f"File {out_file_path} already exists. Skipping convert_file_to_mp3.")
        return relative_path

    # 检查是否存在 loudnorm 参数，并进行基本校验
    loudnorm_args = []
    if getattr(config, "loudnorm", None):
        loudnorm_value = str(config.loudnorm)
        # 允许常见的 ffmpeg 滤镜字符，禁止换行等控制字符
        if re.fullmatch(r"[A-Za-z0-9_\-=:,\. \+\*/]+", loudnorm_value):
            loudnorm_args = ["-af", loudnorm_value]
        else:
            log.error(f"Invalid loudnorm parameter, ignoring: {loudnorm_value!r}")

    command = [
        os.path.join(config.ffmpeg_location, "ffmpeg"),
        "-i",
        input_absolute_path,
        "-f",
        "mp3",
        "-vn",
        "-y",
        *loudnorm_args,
        out_file_path,
    ]

    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        log.exception(f"Error during conversion: {e}")
        return None

    log.info(f"File {input_file} to {out_file_path} convert_file_to_mp3 ok.")
    return relative_path


def _to_utf8(v):
    """转换标签值为 UTF-8 字符串"""
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


def _get_tag_value(tags, k: str) -> str:
    """获取标签值"""
    if k not in tags:
        return ""
    v = tags[k]
    return _to_utf8(v)


def _get_alltag_value(tags, k: str) -> str:
    """获取所有标签值"""
    v = tags.getall(k)
    if len(v) > 0:
        return _to_utf8(v[0])
    return ""


def _parse_metadata_block_picture(tag_value: str) -> bytes | None:
    """解析 OGG Vorbis 的 metadata_block_picture 标签

    先尝试 JSON 格式（部分工具使用），再尝试 FLAC 二进制结构格式。
    FLAC METADATA_BLOCK_PICTURE 二进制结构:
      4B picture type | 4B MIME length + MIME | 4B desc length + desc
      | 4B width | 4B height | 4B depth | 4B colors | 4B data length + data
    """
    raw = base64.b64decode(tag_value)

    # 尝试 JSON 格式
    try:
        picture = json.loads(raw)
        if isinstance(picture, dict) and "data" in picture:
            return base64.b64decode(picture["data"])
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    # 尝试 FLAC 二进制结构格式
    try:
        offset = 0
        # picture type (4B)
        offset += 4
        # MIME type
        mime_len = struct.unpack_from(">I", raw, offset)[0]
        offset += 4 + mime_len
        # description
        desc_len = struct.unpack_from(">I", raw, offset)[0]
        offset += 4 + desc_len
        # width, height, depth, colors (各4B)
        offset += 16
        # picture data
        data_len = struct.unpack_from(">I", raw, offset)[0]
        offset += 4
        return raw[offset : offset + data_len]
    except (struct.error, IndexError):
        pass

    log.warning("Failed to parse metadata_block_picture")
    return None


def _save_picture(picture_data: bytes, save_root: str, file_path: str) -> str:
    """保存图片"""
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


def _resize_save_image(image_bytes: bytes, save_path: str, max_size: int = 300) -> str:
    """缩放并保存图片"""
    # 将 bytes 转换为 PIL Image 对象
    image = None
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image = image.convert("RGB")
    except Exception as e:
        log.warning(f"Error _resize_save_image: {e}")
        return None

    # 获取原始尺寸
    original_width, original_height = image.size

    # 如果图片的宽度和高度都小于 max_size，则直接保存原始图片
    if original_width <= max_size and original_height <= max_size:
        image.save(save_path, format="JPEG")
        return save_path

    # 计算缩放比例，保持等比缩放
    scaling_factor = min(max_size / original_width, max_size / original_height)

    # 计算新的尺寸
    new_width = int(original_width * scaling_factor)
    new_height = int(original_height * scaling_factor)

    resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    resized_image.save(save_path, format="JPEG")
    return save_path


def save_picture_by_base64(
    picture_base64_data: str, save_root: str, file_path: str
) -> str:
    """通过 base64 数据保存图片"""
    try:
        picture_data = base64.b64decode(picture_base64_data)
    except (TypeError, ValueError) as e:
        log.exception(f"Error decoding base64 data: {e}")
        return None
    return _save_picture(picture_data, save_root, file_path)


def extract_audio_metadata(file_path: str, save_root: str) -> dict:
    """
    提取音频文件的元数据

    Args:
        file_path: 音频文件路径
        save_root: 图片保存根目录

    Returns:
        元数据字典
    """
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
        if "covr" in tags and isinstance(tags["covr"], list) and len(tags["covr"]) > 0:
            metadata.picture = _save_picture(tags["covr"][0], save_root, file_path)

    elif isinstance(audio, OggVorbis):
        metadata.title = _get_tag_value(tags, "TITLE")
        metadata.artist = _get_tag_value(tags, "ARTIST")
        metadata.album = _get_tag_value(tags, "ALBUM")
        metadata.year = _get_tag_value(tags, "DATE")
        metadata.genre = _get_tag_value(tags, "GENRE")
        if "metadata_block_picture" in tags:
            picture_data = _parse_metadata_block_picture(
                tags["metadata_block_picture"][0]
            )
            if picture_data:
                metadata.picture = _save_picture(picture_data, save_root, file_path)

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


def _set_mp3_tags(audio, info: Metadata) -> None:
    """设置 MP3 标签"""
    audio.tags = ID3()
    audio["TIT2"] = TIT2(encoding=3, text=info.title)
    audio["TPE1"] = TPE1(encoding=3, text=info.artist)
    audio["TALB"] = TALB(encoding=3, text=info.album)
    audio["TDRC"] = TDRC(encoding=3, text=info.year)
    audio["TCON"] = TCON(encoding=3, text=info.genre)

    # 使用 USLT 存储歌词
    if info.lyrics:
        audio["USLT"] = USLT(encoding=3, lang="eng", text=info.lyrics)

    # 添加封面图片
    if info.picture:
        with open(info.picture, "rb") as img_file:
            image_data = img_file.read()
        audio["APIC"] = APIC(
            encoding=3, mime="image/jpeg", type=3, desc="Cover", data=image_data
        )
    audio.save()  # 保存修改


def _set_flac_tags(audio, info: Metadata) -> None:
    """设置 FLAC 标签"""
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


def _set_mp4_tags(audio, info: Metadata) -> None:
    """设置 MP4 标签"""
    audio["nam"] = info.title
    audio["ART"] = info.artist
    audio["alb"] = info.album
    audio["day"] = info.year
    audio["gen"] = info.genre
    if info.picture:
        with open(info.picture, "rb") as img_file:
            image_data = img_file.read()
        audio["covr"] = [image_data]


def _set_ogg_tags(audio, info: Metadata) -> None:
    """设置 OGG 标签"""
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


def _set_asf_tags(audio, info: Metadata) -> None:
    """设置 ASF 标签"""
    audio["Title"] = info.title
    audio["Author"] = info.artist
    audio["WM/AlbumTitle"] = info.album
    audio["WM/Year"] = info.year
    audio["WM/Genre"] = info.genre
    if info.picture:
        with open(info.picture, "rb") as img_file:
            image_data = img_file.read()
        audio["WM/Picture"] = image_data


def _set_wave_tags(audio, info: Metadata) -> None:
    """设置 WAVE 标签"""
    audio["Title"] = info.title
    audio["Artist"] = info.artist


def set_music_tag_to_file(file_path: str, info: Metadata) -> str:
    """
    设置音乐文件的标签信息

    Args:
        file_path: 文件路径
        info: 元数据对象

    Returns:
        "OK" 或错误信息
    """
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


def get_real_audio_format(file_path: str) -> str:
    """通过读取文件头 Magic Number 瞬间嗅探真实音频格式"""
    try:
        with open(file_path, "rb") as f:
            header = f.read(32)

        if header.startswith(b"fLaC"):
            return "flac"
        if header.startswith(b"OggS"):
            return "ogg"
        if b"ftypM4A" in header or b"ftypm4a" in header or b"m4a" in header:
            return "m4a"
        if header.startswith(b"\xff\xf1") or header.startswith(b"\xff\xf9"):
            return "aac"
        if header.startswith(b"ID3") or header.startswith(b"\xff\xfb"):
            return "mp3"

        return "mp3"  # 兜底
    except Exception:
        return "mp3"


def build_cache_file_path(
    datab64: str, name: str, cache_dir: str, cache_song_name: str = "cache_songs"
) -> str:
    """
    根据核心字段生成唯一缓存路径，彻底免疫一切前端和插件附加的动态干扰字段。
    """
    if not datab64 or not cache_dir:
        return ""

    try:
        # 1. 解开 Base64
        raw_data = json.loads(base64.b64decode(datab64).decode("utf-8"))

        # 2. 提取全系统统一的“身份证号”
        platform = str(raw_data.get("platform", ""))
        song_id = str(raw_data.get("id", ""))

        if platform and song_id:
            fingerprint = f"{platform}_{song_id}"
            short_hash = hashlib.md5(fingerprint.encode()).hexdigest()[:8]
        else:
            short_hash = hashlib.md5(name.strip().encode()).hexdigest()[:8]

    except Exception:
        short_hash = hashlib.md5(datab64.encode()).hexdigest()[:8]

    safe_name = re.sub(r"[^\w\-_.\s()（）\[\]【】]", "_", name)
    filename = f"{short_hash}_{safe_name}.mp3"
    return os.path.join(cache_dir, cache_song_name, filename)
