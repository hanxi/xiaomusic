# convert_to_mp3.py
import os
import subprocess
import tempfile
from pydub import AudioSegment
from pydub.playback import play
from xiaomusic.config import Config

class Convert_To_MP3:
    def __init__(self, config: Config):
        self.config = config
        self.music_path = self.config.music_path
        self.ffmpeg_location = self.config.ffmpeg_location

    @staticmethod
    def convert_to_mp3(input_file: str, ffmpeg_location: str, music_path: str) -> str:
        """
        Convert the music file to MP3 format and return the path of the temporary MP3 file.
        """
        # 指定临时文件的目录为 music_path 目录下的 tmp 文件夹
        temp_dir = os.path.join(music_path, 'tmp')
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)  # 确保目录存在

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3', dir=temp_dir)
        temp_file.close()
        temp_file_path = temp_file.name

        command = [
            ffmpeg_location,
            '-i', input_file,
            '-f', 'mp3',
            '-y',
            temp_file_path
        ]

        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error during conversion: {e}")
            return None

        return temp_file_path

    @classmethod
    def convert_and_play(cls, input_file: str, ffmpeg_location: str):
        """
        将音乐文件转码为 MP3 格式，播放，然后不删除临时文件，依赖于 xiaomusic 启动时的清理逻辑。
        """
        temp_mp3_file = cls.convert_to_mp3(input_file, ffmpeg_location, cls.music_path)
        if temp_mp3_file:
            try:
                # 假设 xiaomusic_playmusic 是一个播放 MP3 文件的函数
                cls.xiaomusic.xiaomusic_playmusic(temp_mp3_file)
            finally:
                # 此处不再删除临时文件，依赖 xiaomusic 的清理逻辑
                pass
        else:
            print("Conversion failed")