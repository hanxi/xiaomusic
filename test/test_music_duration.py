import math

from xiaomusic.const import (
    SUPPORT_MUSIC_TYPE,
)
from xiaomusic.utils import (
    get_local_music_duration,
    traverse_music_directory,
)


async def test_one_music(filename):
    # 获取播放时长
    duration = await get_local_music_duration(filename)
    sec = math.ceil(duration)
    print(f"本地歌曲 : {filename} 的时长 {duration} {sec} 秒")


async def main(directory):
    # 获取所有歌曲文件
    local_musics = traverse_music_directory(directory, 10, [], SUPPORT_MUSIC_TYPE)
    print(local_musics)
    for _, files in local_musics.items():
        for file in files:
            await test_one_music(file)


if __name__ == "__main__":
    import asyncio

    directory = "./music"  # 替换为你的音乐目录路径
    asyncio.run(main(directory))
