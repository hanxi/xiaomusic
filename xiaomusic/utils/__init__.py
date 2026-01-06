#!/usr/bin/env python3
"""
Utils package - 工具函数模块

将原 utils.py 拆分为多个职责清晰的子模块：
- text_utils: 文本处理和搜索
- file_utils: 文件和目录操作
- music_utils: 音乐文件处理
- network_utils: 网络请求和下载
- system_utils: 系统操作和环境
"""

# 从各子模块导入常用函数，保持向后兼容
from xiaomusic.utils.file_utils import (
    chmoddir,
    chmodfile,
    not_in_dirs,
    remove_common_prefix,
    safe_join_path,
    traverse_music_directory,
)
from xiaomusic.utils.music_utils import (
    Metadata,
    convert_file_to_mp3,
    extract_audio_metadata,
    get_duration_by_ffprobe,
    get_duration_by_mutagen,
    get_local_music_duration,
    get_web_music_duration,
    is_m4a,
    is_mp3,
    remove_id3_tags,
    save_picture_by_base64,
    set_music_tag_to_file,
)
from xiaomusic.utils.network_utils import (
    MusicUrlCache,
    check_bili_fav_list,
    download_one_music,
    download_playlist,
    downloadfile,
    fetch_json_get,
    text_to_mp3,
)
from xiaomusic.utils.system_utils import (
    deepcopy_data_no_sensitive_info,
    download_and_extract,
    get_latest_version,
    get_os_architecture,
    get_random,
    is_docker,
    parse_cookie_string,
    restart_xiaomusic,
    try_add_access_control_param,
    update_version,
    validate_proxy,
)
from xiaomusic.utils.text_utils import (
    calculate_tts_elapse,
    chinese_to_number,
    custom_sort_key,
    find_best_match,
    find_key_by_partial_string,
    fuzzyfinder,
    keyword_detection,
    list2str,
    parse_str_to_dict,
    split_sentences,
    traditional_to_simple,
)

__all__ = [
    # text_utils
    "calculate_tts_elapse",
    "chinese_to_number",
    "custom_sort_key",
    "find_best_match",
    "find_key_by_partial_string",
    "fuzzyfinder",
    "keyword_detection",
    "list2str",
    "parse_str_to_dict",
    "split_sentences",
    "traditional_to_simple",
    # file_utils
    "chmoddir",
    "chmodfile",
    "not_in_dirs",
    "remove_common_prefix",
    "safe_join_path",
    "traverse_music_directory",
    # music_utils
    "Metadata",
    "convert_file_to_mp3",
    "extract_audio_metadata",
    "get_duration_by_ffprobe",
    "get_duration_by_mutagen",
    "get_local_music_duration",
    "get_web_music_duration",
    "is_m4a",
    "is_mp3",
    "remove_id3_tags",
    "set_music_tag_to_file",
    "save_picture_by_base64",
    # network_utils
    "MusicUrlCache",
    "check_bili_fav_list",
    "download_one_music",
    "download_playlist",
    "downloadfile",
    "fetch_json_get",
    "text_to_mp3",
    # system_utils
    "deepcopy_data_no_sensitive_info",
    "download_and_extract",
    "get_latest_version",
    "get_os_architecture",
    "get_random",
    "is_docker",
    "parse_cookie_string",
    "restart_xiaomusic",
    "try_add_access_control_param",
    "update_version",
    "validate_proxy",
]
