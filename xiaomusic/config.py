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
    # hardware: (tts_command, wakeup_command)
    "LX06": ("5-1", "5-5"),
    "L05B": ("5-3", "5-4"),
    "S12A": ("5-1", "5-5"),
    "LX01": ("5-1", "5-5"),
    "L06A": ("5-1", "5-5"),
    "LX04": ("5-1", "5-4"),
    "L05C": ("5-3", "5-4"),
    "L17A": ("7-3", "7-4"),
    "X08E": ("7-3", "7-4"),
    "LX05A": ("5-1", "5-5"),  # 小爱红外版
    "LX5A": ("5-1", "5-5"),  # 小爱红外版
    "L07A": ("5-1", "5-5"),  # Redmi小爱音箱Play(l7a)
    "L15A": ("7-3", "7-4"),
    "X6A": ("7-3", "7-4"),  # 小米智能家庭屏6
    "X10A": ("7-3", "7-4"),  # 小米智能家庭屏10
    # add more here
}

DEFAULT_COMMAND = ("5-1", "5-5")

KEY_WORD_DICT = {
    "播放歌曲": "play",
    "放歌曲": "play",
    "下一首": "play_next",
    "单曲循环":"set_play_type_one",
    "全部循环":"set_play_type_all",
    "关机":"stop",
    "停止播放":"stop",
}

@dataclass
class Config:
    hardware: str = os.getenv("MI_HARDWARE", "L07A")
    account: str = os.getenv("MI_USER", "")
    password: str = os.getenv("MI_PASS", "")
    mi_did: str = os.getenv("MI_DID", "")
    mute_xiaoai: bool = True
    cookie: str = ""
    use_command: bool = True
    verbose: bool = False
    music_path: str = os.getenv("XIAOMUSIC_MUSIC_PATH", "music")
    hostname: str = os.getenv("XIAOMUSIC_HOSTNAME", "192.168.2.5")
    port: int = int(os.getenv("XIAOMUSIC_PORT", "8090"))
    proxy: str | None = os.getenv("XIAOMUSIC_PROXY", None)

    def __post_init__(self) -> None:
        if self.proxy:
            validate_proxy(self.proxy)

    @property
    def tts_command(self) -> str:
        return HARDWARE_COMMAND_DICT.get(self.hardware, DEFAULT_COMMAND)[0]

    @property
    def wakeup_command(self) -> str:
        return HARDWARE_COMMAND_DICT.get(self.hardware, DEFAULT_COMMAND)[1]

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
