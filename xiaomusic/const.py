SUPPORT_MUSIC_TYPE = [
    ".mp3",
    ".flac",
    ".wav",
    ".ape",
    ".ogg",
    ".m4a",
]

LATEST_ASK_API = "https://userprofile.mina.mi.com/device_profile/v2/conversation?source=dialogu&hardware={hardware}&timestamp={timestamp}&limit=2"
COOKIE_TEMPLATE = "deviceId={device_id}; serviceToken={service_token}; userId={user_id}"

PLAY_TYPE_ONE = 0  # 单曲循环
PLAY_TYPE_ALL = 1  # 全部循环
PLAY_TYPE_RND = 2  # 随机播放

PLAY_TYPE_TTS = {
    PLAY_TYPE_ONE: "已经设置为单曲循环",
    PLAY_TYPE_ALL: "已经设置为全部循环",
    PLAY_TYPE_RND: "已经设置为随机播放",
}
