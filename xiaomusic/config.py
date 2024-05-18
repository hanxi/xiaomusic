from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

from xiaomusic.utils import validate_proxy

LATEST_ASK_API = "https://userprofile.mina.mi.com/device_profile/v2/conversation?source=dialogu&hardware={hardware}&timestamp={timestamp}&limit=2"
COOKIE_TEMPLATE = "deviceId={device_id}; serviceToken={service_token}; userId={user_id}"
HARDWARE_COMMAND_DICT = {
    # hardware: (tts_command, wakeup_command, volume_command)
    "LX06": ("5-1", "5-5", "2-1"),
    "L05B": ("5-3", "5-4", "2-1"),    
    "S12": ("5-1", "5-5", "2-1"),  # 第一代小爱，型号MDZ-25-DA
    "S12A": ("5-1", "5-5", "2-1"),
    "LX01": ("5-1", "5-5", "2-1"),
    "L06A": ("5-1", "5-5", "2-1"),
    "LX04": ("5-1", "5-4", "2-1"),
    "L05C": ("5-3", "5-4", "2-1"),
    "L17A": ("7-3", "7-4", "2-1"),
    "X08E": ("7-3", "7-4", "2-1"),
    "LX05A": ("5-1", "5-5", "2-1"),  # 小爱红外版
    "LX5A": ("5-1", "5-5", "2-1"),  # 小爱红外版
    "L07A": ("5-1", "5-5", "2-1"),  # Redmi小爱音箱Play(l7a)
    "L15A": ("7-3", "7-4", "2-1"),
    "X6A": ("7-3", "7-4", "2-1"),  # 小米智能家庭屏6
    "X10A": ("7-3", "7-4", "2-1"),  # 小米智能家庭屏10
    # add more here
}

DEFAULT_COMMAND = ("5-1", "5-5", "2-1")

KEY_WORD_DICT = {
    "播放歌曲": "play",
    "放歌曲": "play",
    "下一首": "play_next",
    "单曲循环": "set_play_type_one",
    "全部循环": "set_play_type_all",
    "随机播放": "random_play",
    "关机": "stop",
    "停止播放": "stop",
    "分钟后关机": "stop_after_minute",
    "set_volume#": "set_volume",
    "get_volume#": "get_volume",
}

# 命令参数在前面
KEY_WORD_ARG_BEFORE_DICT = {
    "分钟后关机": True,
}

# 匹配优先级
KEY_MATCH_ORDER = [
    "set_volume#",
    "get_volume#",
    "分钟后关机",
    "播放歌曲",
    "放歌曲",
    "下一首",
    "单曲循环",
    "全部循环",
    "随机播放",
    "关机",
    "停止播放",
]

SUPPORT_MUSIC_TYPE = [
    ".mp3",
    ".flac",
]


@dataclass
class Config:
    hardware: str = os.getenv("MI_HARDWARE", "L07A")
    account: str = os.getenv("MI_USER", "")
    password: str = os.getenv("MI_PASS", "")
    mi_did: str = os.getenv("MI_DID", "")
    mute_xiaoai: bool = True
    cookie: str = ""
    use_command: bool = False
    verbose: bool = False
    music_path: str = os.getenv("XIAOMUSIC_MUSIC_PATH", "music")
    hostname: str = os.getenv("XIAOMUSIC_HOSTNAME", "192.168.2.5")
    port: int = int(os.getenv("XIAOMUSIC_PORT", "8090"))
    proxy: str | None = os.getenv("XIAOMUSIC_PROXY", None)
    search_prefix: str = os.getenv(
        "XIAOMUSIC_SEARCH", "ytsearch:"
    )  # "bilisearch:" or "ytsearch:"
    ffmpeg_location: str = os.getenv("XIAOMUSIC_FFMPEG_LOCATION", "./ffmpeg/bin")
    active_cmd: str = os.getenv("XIAOMUSIC_ACTIVE_CMD", "play,random_play")

    def __post_init__(self) -> None:
        if self.proxy:
            validate_proxy(self.proxy)

    @property
    def tts_command(self) -> str:
        return HARDWARE_COMMAND_DICT.get(self.hardware, DEFAULT_COMMAND)[0]

    @property
    def wakeup_command(self) -> str:
        return HARDWARE_COMMAND_DICT.get(self.hardware, DEFAULT_COMMAND)[1]

    @property
    def volume_command(self) -> str:
        return HARDWARE_COMMAND_DICT.get(self.hardware, DEFAULT_COMMAND)[2]

    @classmethod
    def from_options(cls, options: argparse.Namespace) -> Config:
        config = {}
        if options.config:
            config = cls.read_from_file(options.config)
        for key, value in vars(options).items():
            if value is not None and key in cls.__dataclass_fields__:
                config[key] = value
        return cls(**config)

    @classmethod
    def read_from_file(cls, config_path: str) -> dict:
        result = {}
        with open(config_path, "rb") as f:
            config = json.load(f)
            for key, value in config.items():
                if value is not None and key in cls.__dataclass_fields__:
                    result[key] = value
        return result
