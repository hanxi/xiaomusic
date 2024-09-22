import traceback

from xiaomusic.const import (
    SUPPORT_MUSIC_TYPE,
)
from xiaomusic.utils import (
    get_audio_metadata,
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
        metadata = get_audio_metadata(filename)
        print(metadata.title, metadata.album)
        if metadata:
            lyrics = metadata.lyrics
            if lyrics:
                print(f"歌曲 : {filename} 的 {lyrics}")
    except Exception as e:
        print(f"歌曲 : {filename} no tag {e}")
        traceback.print_exc()


async def main(directory):
    # 获取所有歌曲文件
    local_musics = traverse_music_directory(directory, 10, [], SUPPORT_MUSIC_TYPE)
    print(local_musics)
    for _, files in local_musics.items():
        for file in files:
            await test_one_music(file)
            pass

    await test_one_music("./music/一生何求.mp3")


if __name__ == "__main__":
    import asyncio

    directory = "./music"  # 替换为你的音乐目录路径
    asyncio.run(main(directory))
