import argparse
import asyncio

from xiaomusic.config import Config
from xiaomusic.xiaomusic import XiaoMusic


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hardware",
        dest="hardware",
        help="小爱 hardware",
    )
    parser.add_argument(
        "--account",
        dest="account",
        help="xiaomi account",
    )
    parser.add_argument(
        "--password",
        dest="password",
        help="xiaomi password",
    )
    parser.add_argument(
        "--cookie",
        dest="cookie",
        help="xiaomi cookie",
    )
    parser.add_argument(
        "--use_command",
        dest="use_command",
        action="store_true",
        default=None,
        help="use command to tts",
    )
    parser.add_argument(
        "--mute_xiaoai",
        dest="mute_xiaoai",
        action="store_true",
        default=None,
        help="try to mute xiaoai answer",
    )
    parser.add_argument(
        "--verbose",
        dest="verbose",
        action="store_true",
        default=None,
        help="show info",
    )
    parser.add_argument(
        "--config",
        dest="config",
        help="config file path",
    )
    parser.add_argument(
        "--ffmpeg_location",
        dest="ffmpeg_location",
        help="ffmpeg bin path",
    )

    options = parser.parse_args()
    config = Config.from_options(options)

    xiaomusic = XiaoMusic(config)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(xiaomusic.run_forever())


if __name__ == "__main__":
    main()
