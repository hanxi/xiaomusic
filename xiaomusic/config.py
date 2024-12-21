from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from typing import get_type_hints

from xiaomusic.const import (
    PLAY_TYPE_ALL,
    PLAY_TYPE_ONE,
    PLAY_TYPE_RND,
    PLAY_TYPE_SEQ,
    PLAY_TYPE_SIN,
)
from xiaomusic.utils import validate_proxy


# 默认口令
def default_key_word_dict():
    return {
        "下一首": "play_next",
        "上一首": "play_prev",
        "单曲循环": "set_play_type_one",
        "全部循环": "set_play_type_all",
        "随机播放": "set_play_type_rnd",
        "单曲播放": "set_play_type_sin",
        "顺序播放": "set_play_type_seq",
        "分钟后关机": "stop_after_minute",
        "刷新列表": "gen_music_list",
        "加入收藏": "add_to_favorites",
        "收藏歌曲": "add_to_favorites",
        "取消收藏": "del_from_favorites",
        "播放列表第": "play_music_list_index",
    }


def default_user_key_word_dict():
    return {
        "测试自定义口令": 'exec#code1("hello")',
        "测试链接": 'exec#httpget("https://github.com/hanxi/xiaomusic")',
    }


# 命令参数在前面
KEY_WORD_ARG_BEFORE_DICT = {
    "分钟后关机": True,
}


# 口令匹配优先级
def default_key_match_order():
    return [
        "分钟后关机",
        "下一首",
        "上一首",
        "单曲循环",
        "全部循环",
        "随机播放",
        "单曲播放",
        "顺序播放",
        "关机",
        "刷新列表",
        "播放列表第",
        "播放列表",
        "加入收藏",
        "收藏歌曲",
        "取消收藏",
    ]


@dataclass
class Device:
    did: str = ""
    device_id: str = ""
    hardware: str = ""
    name: str = ""
    play_type: int = PLAY_TYPE_RND
    cur_music: str = ""
    cur_playlist: str = ""


@dataclass
class Config:
    account: str = os.getenv("MI_USER", "")
    password: str = os.getenv("MI_PASS", "")
    mi_did: str = os.getenv("MI_DID", "")  # 逗号分割支持多设备
    miio_tts_command: str = os.getenv("MIIO_TTS_CMD", "")
    cookie: str = ""
    verbose: bool = os.getenv("XIAOMUSIC_VERBOSE", "").lower() == "true"
    music_path: str = os.getenv("XIAOMUSIC_MUSIC_PATH", "music")
    temp_path: str = os.getenv("XIAOMUSIC_TEMP_PATH", "music/tmp")
    download_path: str = os.getenv("XIAOMUSIC_DOWNLOAD_PATH", "music/download")
    conf_path: str = os.getenv("XIAOMUSIC_CONF_PATH", "conf")
    cache_dir: str = os.getenv("XIAOMUSIC_CACHE_DIR", "cache")
    hostname: str = os.getenv("XIAOMUSIC_HOSTNAME", "192.168.2.5")
    port: int = int(os.getenv("XIAOMUSIC_PORT", "8090"))  # 监听端口
    public_port: int = int(os.getenv("XIAOMUSIC_PUBLIC_PORT", 0))  # 歌曲访问端口
    proxy: str = os.getenv("XIAOMUSIC_PROXY", None)
    search_prefix: str = os.getenv(
        "XIAOMUSIC_SEARCH", "bilisearch:"
    )  # "bilisearch:" or "ytsearch:"
    ffmpeg_location: str = os.getenv("XIAOMUSIC_FFMPEG_LOCATION", "./ffmpeg/bin")
    active_cmd: str = os.getenv(
        "XIAOMUSIC_ACTIVE_CMD",
        "play,search_play,set_play_type_rnd,playlocal,search_playlocal,play_music_list,play_music_list_index,stop_after_minute,stop",
    )
    exclude_dirs: str = os.getenv("XIAOMUSIC_EXCLUDE_DIRS", "@eaDir,tmp")
    ignore_tag_dirs: str = os.getenv("XIAOMUSIC_IGNORE_TAG_DIRS", "")
    music_path_depth: int = int(os.getenv("XIAOMUSIC_MUSIC_PATH_DEPTH", "10"))
    disable_httpauth: bool = (
        os.getenv("XIAOMUSIC_DISABLE_HTTPAUTH", "true").lower() == "true"
    )
    httpauth_username: str = os.getenv("XIAOMUSIC_HTTPAUTH_USERNAME", "")
    httpauth_password: str = os.getenv("XIAOMUSIC_HTTPAUTH_PASSWORD", "")
    music_list_url: str = os.getenv("XIAOMUSIC_MUSIC_LIST_URL", "")
    music_list_json: str = os.getenv("XIAOMUSIC_MUSIC_LIST_JSON", "")
    custom_play_list_json: str = os.getenv("XIAOMUSIC_CUSTOM_PLAY_LIST_JSON", "")
    disable_download: bool = (
        os.getenv("XIAOMUSIC_DISABLE_DOWNLOAD", "false").lower() == "true"
    )
    key_word_dict: dict[str, str] = field(default_factory=default_key_word_dict)
    key_match_order: list[str] = field(default_factory=default_key_match_order)
    use_music_api: bool = (
        os.getenv("XIAOMUSIC_USE_MUSIC_API", "false").lower() == "true"
    )
    use_music_audio_id: str = os.getenv(
        "XIAOMUSIC_USE_MUSIC_AUDIO_ID", "1582971365183456177"
    )
    use_music_id: str = os.getenv("XIAOMUSIC_USE_MUSIC_ID", "355454500")
    log_file: str = os.getenv("XIAOMUSIC_LOG_FILE", "xiaomusic.log.txt")
    # 模糊搜索匹配的最低相似度阈值
    fuzzy_match_cutoff: float = float(os.getenv("XIAOMUSIC_FUZZY_MATCH_CUTOFF", "0.6"))
    # 开启模糊搜索
    enable_fuzzy_match: bool = (
        os.getenv("XIAOMUSIC_ENABLE_FUZZY_MATCH", "true").lower() == "true"
    )
    stop_tts_msg: str = os.getenv("XIAOMUSIC_STOP_TTS_MSG", "收到,再见")
    enable_config_example: bool = False

    keywords_playlocal: str = os.getenv(
        "XIAOMUSIC_KEYWORDS_PLAYLOCAL", "播放本地歌曲,本地播放歌曲"
    )
    keywords_search_playlocal: str = os.getenv(
        "XIAOMUSIC_KEYWORDS_SEARCH_PLAYLOCAL", "本地搜索播放"
    )
    keywords_play: str = os.getenv("XIAOMUSIC_KEYWORDS_PLAY", "播放歌曲,放歌曲")
    keywords_search_play: str = os.getenv("XIAOMUSIC_KEYWORDS_SEARCH_PLAY", "搜索播放")
    keywords_stop: str = os.getenv("XIAOMUSIC_KEYWORDS_STOP", "关机,暂停,停止,停止播放")
    keywords_playlist: str = os.getenv(
        "XIAOMUSIC_KEYWORDS_PLAYLIST", "播放列表,播放歌单"
    )
    user_key_word_dict: dict[str, str] = field(
        default_factory=default_user_key_word_dict
    )
    enable_force_stop: bool = (
        os.getenv("XIAOMUSIC_ENABLE_FORCE_STOP", "false").lower() == "true"
    )
    devices: dict[str, Device] = field(default_factory=dict)
    group_list: str = os.getenv(
        "XIAOMUSIC_GROUP_LIST", ""
    )  # did1:group_name,did2:group_name
    remove_id3tag: bool = (
        os.getenv("XIAOMUSIC_REMOVE_ID3TAG", "false").lower() == "true"
    )
    convert_to_mp3: bool = os.getenv("CONVERT_TO_MP3", "false").lower() == "true"
    delay_sec: int = int(os.getenv("XIAOMUSIC_DELAY_SEC", 3))  # 下一首歌延迟播放秒数
    continue_play: bool = (
        os.getenv("XIAOMUSIC_CONTINUE_PLAY", "false").lower() == "true"
    )
    pull_ask_sec: int = int(os.getenv("XIAOMUSIC_PULL_ASK_SEC", "1"))
    crontab_json: str = os.getenv("XIAOMUSIC_CRONTAB_JSON", "")  # 定时任务
    enable_yt_dlp_cookies: bool = (
        os.getenv("XIAOMUSIC_ENABLE_YT_DLP_COOKIES", "false").lower() == "true"
    )
    enable_save_tag: bool = (
        os.getenv("XIAOMUSIC_ENABLE_SAVE_TAG", "false").lower() == "true"
    )
    get_ask_by_mina: bool = (
        os.getenv("XIAOMUSIC_GET_ASK_BY_MINA", "false").lower() == "true"
    )
    play_type_one_tts_msg: str = os.getenv(
        "XIAOMUSIC_PLAY_TYPE_ONE_TTS_MSG", "已经设置为单曲循环"
    )
    play_type_all_tts_msg: str = os.getenv(
        "XIAOMUSIC_PLAY_TYPE_ALL_TTS_MSG", "已经设置为全部循环"
    )
    play_type_rnd_tts_msg: str = os.getenv(
        "XIAOMUSIC_PLAY_TYPE_RND_TTS_MSG", "已经设置为随机播放"
    )
    play_type_sin_tts_msg: str = os.getenv(
        "XIAOMUSIC_PLAY_TYPE_SIN_TTS_MSG", "已经设置为单曲播放"
    )
    play_type_seq_tts_msg: str = os.getenv(
        "XIAOMUSIC_PLAY_TYPE_SEQ_TTS_MSG", "已经设置为顺序播放"
    )
    recently_added_playlist_len: int = int(
        os.getenv("XIAOMUSIC_RECENTLY_ADDED_PLAYLIST_LEN", "50")
    )

    def append_keyword(self, keys, action):
        for key in keys.split(","):
            if key:
                self.key_word_dict[key] = action
                if key not in self.key_match_order:
                    self.key_match_order.append(key)

    def append_user_keyword(self):
        for k, v in self.user_key_word_dict.items():
            self.key_word_dict[k] = v
            if k not in self.key_match_order:
                self.key_match_order.append(k)

    def init_keyword(self):
        self.key_match_order = default_key_match_order()
        self.key_word_dict = default_key_word_dict()
        self.append_keyword(self.keywords_playlocal, "playlocal")
        self.append_keyword(self.keywords_search_playlocal, "search_playlocal")
        self.append_keyword(self.keywords_play, "play")
        self.append_keyword(self.keywords_search_play, "search_play")
        self.append_keyword(self.keywords_stop, "stop")
        self.append_keyword(self.keywords_playlist, "play_music_list")
        self.append_user_keyword()
        self.key_match_order = [
            x for x in self.key_match_order if x in self.key_word_dict
        ]

    def __post_init__(self) -> None:
        if self.proxy:
            validate_proxy(self.proxy)

        self.init_keyword()
        # 保存配置到 config-example.json 文件
        if self.enable_config_example:
            with open("config-example.json", "w") as f:
                data = asdict(self)
                json.dump(data, f, ensure_ascii=False, indent=2)

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
    def convert_value(cls, k, v, type_hints):
        if v is not None and k in type_hints:
            expected_type = type_hints[k]
            try:
                if expected_type is bool:
                    converted_value = False
                    if str(v).lower() == "true":
                        converted_value = True
                elif expected_type == dict[str, Device]:
                    converted_value = {}
                    for kk, vv in v.items():
                        converted_value[kk] = Device(**vv)
                else:
                    converted_value = expected_type(v)
                return converted_value
            except (ValueError, TypeError) as e:
                print(f"Error converting {k}:{v} to {expected_type}: {e}")
        return None

    @classmethod
    def read_from_file(cls, config_path: str) -> dict:
        result = {}
        with open(config_path, "rb") as f:
            data = json.load(f)
            type_hints = get_type_hints(cls)

            for k, v in data.items():
                converted_value = cls.convert_value(k, v, type_hints)
                if converted_value is not None:
                    result[k] = converted_value
        return result

    def update_config(self, data):
        type_hints = get_type_hints(self, globals(), locals())

        for k, v in data.items():
            converted_value = self.convert_value(k, v, type_hints)
            if converted_value is not None:
                setattr(self, k, converted_value)
        self.init_keyword()

    # 获取设置文件
    def getsettingfile(self):
        # 兼容旧配置空的情况
        if not self.conf_path:
            self.conf_path = "conf"
        if not os.path.exists(self.conf_path):
            os.makedirs(self.conf_path)
        filename = os.path.join(self.conf_path, "setting.json")
        return filename

    @property
    def tag_cache_path(self):
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        filename = os.path.join(self.cache_dir, "tag_cache.json")
        return filename

    @property
    def picture_cache_path(self):
        cache_path = os.path.join(self.cache_dir, "picture_cache")
        if not os.path.exists(cache_path):
            os.makedirs(cache_path)
        return cache_path

    @property
    def yt_dlp_cookies_path(self):
        if not os.path.exists(self.conf_path):
            os.makedirs(self.conf_path)
        cookies_path = os.path.join(self.conf_path, "yt-dlp-cookie.txt")
        return cookies_path

    @property
    def temp_dir(self):
        if not os.path.exists(self.temp_path):
            os.makedirs(self.temp_path)
        return self.temp_path

    def get_play_type_tts(self, play_type):
        if play_type == PLAY_TYPE_ONE:
            return self.play_type_one_tts_msg
        if play_type == PLAY_TYPE_ALL:
            return self.play_type_all_tts_msg
        if play_type == PLAY_TYPE_RND:
            return self.play_type_rnd_tts_msg
        if play_type == PLAY_TYPE_SIN:
            return self.play_type_sin_tts_msg
        if play_type == PLAY_TYPE_SEQ:
            return self.play_type_seq_tts_msg
        return ""

    def get_ignore_tag_dirs(self):
        ignore_tag_absolute_dirs = []
        for ignore_tag_dir in self.ignore_tag_dirs.split(","):
            if ignore_tag_dir:
                ignore_tag_absolute_path = os.path.abspath(ignore_tag_dir)
                ignore_tag_absolute_dirs.append(ignore_tag_absolute_path)
        return ignore_tag_absolute_dirs
