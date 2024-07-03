from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass

from xiaomusic.utils import validate_proxy

# 默认口令
DEFAULT_KEY_WORD_DICT = {
    "播放歌曲": "play",
    "播放本地歌曲": "playlocal",
    "关机": "stop",
    "下一首": "play_next",
    "单曲循环": "set_play_type_one",
    "全部循环": "set_play_type_all",
    "随机播放": "random_play",
    "分钟后关机": "stop_after_minute",
    "播放列表": "play_music_list",
    "刷新列表": "gen_music_list",
    "set_volume#": "set_volume",
    "get_volume#": "get_volume",
}

# 命令参数在前面
KEY_WORD_ARG_BEFORE_DICT = {
    "分钟后关机": True,
}

# 口令匹配优先级
DEFAULT_KEY_MATCH_ORDER = [
    "set_volume#",
    "get_volume#",
    "分钟后关机",
    "播放歌曲",
    "下一首",
    "单曲循环",
    "全部循环",
    "随机播放",
    "关机",
    "刷新列表",
    "播放列表",
]


@dataclass
class Config:
    hardware: str = os.getenv("MI_HARDWARE", "L07A")
    account: str = os.getenv("MI_USER", "")
    password: str = os.getenv("MI_PASS", "")
    mi_did: str = os.getenv("MI_DID", "")
    cookie: str = ""
    verbose: bool = os.getenv("XIAOMUSIC_VERBOSE", "").lower() == "true"
    music_path: str = os.getenv("XIAOMUSIC_MUSIC_PATH", "music")
    conf_path: str = os.getenv("XIAOMUSIC_CONF_PATH", None)
    hostname: str = os.getenv("XIAOMUSIC_HOSTNAME", "192.168.2.5")
    port: int = int(os.getenv("XIAOMUSIC_PORT", "8090"))
    proxy: str | None = os.getenv("XIAOMUSIC_PROXY", None)
    search_prefix: str = os.getenv(
        "XIAOMUSIC_SEARCH", "ytsearch:"
    )  # "bilisearch:" or "ytsearch:"
    ffmpeg_location: str = os.getenv("XIAOMUSIC_FFMPEG_LOCATION", "./ffmpeg/bin")
    active_cmd: str = os.getenv(
        "XIAOMUSIC_ACTIVE_CMD", "play,random_play,playlocal,play_music_list,stop"
    )
    exclude_dirs: str = os.getenv("XIAOMUSIC_EXCLUDE_DIRS", "@eaDir")
    music_path_depth: int = int(os.getenv("XIAOMUSIC_MUSIC_PATH_DEPTH", "10"))
    disable_httpauth: bool = (
        os.getenv("XIAOMUSIC_DISABLE_HTTPAUTH", "true").lower() == "true"
    )
    httpauth_username: str = os.getenv("XIAOMUSIC_HTTPAUTH_USERNAME", "admin")
    httpauth_password: str = os.getenv("XIAOMUSIC_HTTPAUTH_PASSWORD", "admin")
    music_list_url: str = os.getenv("XIAOMUSIC_MUSIC_LIST_URL", "")
    music_list_json: str = os.getenv("XIAOMUSIC_MUSIC_LIST_JSON", "")
    disable_download: bool = (
        os.getenv("XIAOMUSIC_DISABLE_DOWNLOAD", "false").lower() == "true"
    )
    key_word_dict = DEFAULT_KEY_WORD_DICT.copy()
    key_match_order = DEFAULT_KEY_MATCH_ORDER.copy()
    use_music_api: bool = (
        os.getenv("XIAOMUSIC_USE_MUSIC_API", "false").lower() == "true"
    )
    use_music_audio_id: str = os.getenv("XIAOMUSIC_USE_MUSIC_AUDIO_ID", "1582971365183456177")
    use_music_id: str = os.getenv("XIAOMUSIC_USE_MUSIC_ID", "355454500")
    log_file: str = os.getenv("XIAOMUSIC_MUSIC_LOG_FILE", "/tmp/xiaomusic.txt")
    # 模糊搜索匹配的最低相似度阈值
    fuzzy_match_cutoff: float = float(os.getenv("XIAOMUSIC_FUZZY_MATCH_CUTOFF", "0.6"))
    # 开启模糊搜索
    enable_fuzzy_match: bool = (
        os.getenv("XIAOMUSIC_ENABLE_FUZZY_MATCH", "true").lower() == "true"
    )
    stop_tts_msg: str = os.getenv("XIAOMUSIC_STOP_TTS_MSG", "收到,再见")

    keywords_playlocal: str = os.getenv(
        "XIAOMUSIC_KEYWORDS_PLAYLOCAL", "播放本地歌曲,本地播放歌曲"
    )
    keywords_play: str = os.getenv("XIAOMUSIC_KEYWORDS_PLAY", "播放歌曲,放歌曲")
    keywords_stop: str = os.getenv("XIAOMUSIC_KEYWORDS_STOP", "关机,暂停,停止,停止播放")

    def append_keyword(self, keys, action):
        for key in keys.split(","):
            self.key_word_dict[key] = action
            if key not in self.key_match_order:
                self.key_match_order.append(key)

    def __post_init__(self) -> None:
        if self.proxy:
            validate_proxy(self.proxy)
        self.append_keyword(self.keywords_playlocal, "playlocal")
        self.append_keyword(self.keywords_play, "play")
        self.append_keyword(self.keywords_stop, "stop")

        # 保存配置到 config-example.json 文件
        # with open("config-example.json", "w") as f:
        #    data = asdict(self)
        #    json.dump(data, f, ensure_ascii=False, indent=4)

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
