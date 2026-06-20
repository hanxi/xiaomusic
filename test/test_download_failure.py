import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from xiaomusic.device_player import XiaoMusicDevice


class DummyLog:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


class DummyMusicLibrary:
    def is_music_exist(self, name):
        return False


class DummyDevice:
    cur_playlist = "全部"
    play_type = 0
    device_id = "did"
    cur_music = ""


def make_player():
    player = XiaoMusicDevice.__new__(XiaoMusicDevice)
    player.config = SimpleNamespace(
        disable_download=False,
        download_path="/tmp/xiaomusic-download-test",
        search_prefix="bilisearch:",
        proxy=None,
        enable_yt_dlp_cookies=False,
        loudnorm=None,
        ffmpeg_location="/usr/bin",
        yt_dlp_cookies_path="/tmp/cookies.txt",
        continue_play=True,
    )
    player.log = DummyLog()
    player.xiaomusic = SimpleNamespace(music_library=DummyMusicLibrary())
    player.device = DummyDevice()
    player.do_tts = AsyncMock()
    player._pending_selection = None
    player._pending_selection_count = 0
    player._play_list = []
    player.add_download_music = AsyncMock()
    player.ffmpeg_location = player.config.ffmpeg_location
    player._download_proc = None
    return player


def test_failed_download_does_not_add_song_to_playlist():
    player = make_player()

    async def fake_download(search_key, name):
        return False

    player.download = fake_download

    result = asyncio.run(player._check_and_download_music("test-song", "test-song", True))

    assert result is False
    assert player.add_download_music.await_count == 0
