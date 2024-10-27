import traceback

from xiaomusic.const import (
    SUPPORT_MUSIC_TYPE,
)
from xiaomusic.utils import (
    extract_audio_metadata,
    traverse_music_directory,
)

# title 标题
# artist 艺术家
# album 影集
# year 年
# genre 性
# picture 图片
# lyrics 歌词


async def test_one_music(filename):
    # 获取播放时长
    try:
        metadata = extract_audio_metadata(filename, "cache/picture_cache")
        print(metadata)
    except Exception as e:
        print(f"歌曲 : {filename} no tag {e}")
        traceback.print_exc()


async def main(directory):
    # 获取所有歌曲文件
    local_musics = traverse_music_directory(directory, 10, [], SUPPORT_MUSIC_TYPE)
    for _, files in local_musics.items():
        for file in files:
            print(file)
            # await test_one_music(file)
            pass

    await test_one_music("music/4 In Love - 一千零一个愿望.mp3")
    # await test_one_music("./music/程响-人间烟火.flac")


if __name__ == "__main__":
    import asyncio

    directory = "./music"  # 替换为你的音乐目录路径
    asyncio.run(main(directory))
