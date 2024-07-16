#!/usr/bin/env python3
import argparse

import uvicorn

from xiaomusic import __version__
from xiaomusic.config import Config
from xiaomusic.httpserver import HttpInit
from xiaomusic.httpserver import app as HttpApp
from xiaomusic.xiaomusic import XiaoMusic

LOGO = r"""
 __  __  _                   __  __                 _
 \ \/ / (_)   __ _    ___   |  \/  |  _   _   ___  (_)   ___
  \  /  | |  / _` |  / _ \  | |\/| | | | | | / __| | |  / __|
  /  \  | | | (_| | | (_) | | |  | | | |_| | \__ \ | | | (__
 /_/\_\ |_|  \__,_|  \___/  |_|  |_|  \__,_| |___/ |_|  \___|
          {}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        dest="port",
        help="监听端口",
    )
    parser.add_argument(
        "--hardware",
        dest="hardware",
        help="小爱音箱型号",
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
    parser.add_argument(
        "--enable_config_example",
        dest="enable_config_example",
        help="是否输出示例配置文件",
        action="store_true",
    )

    print(LOGO.format(f"XiaoMusic v{__version__} by: github.com/hanxi"))

    options = parser.parse_args()
    config = Config.from_options(options)

    xiaomusic = XiaoMusic(config)
    HttpInit(xiaomusic)

    log_config = {
        "version": 1,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "format": f"%(asctime)s [{__version__}] [%(levelname)s] %(filename)s:%(lineno)d: %(message)s",
                "use_colors": False,
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.FileHandler",
                "formatter": "default",
                "filename": config.log_file,
                "mode": "a",
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["default", "file"],
                "level": "INFO",
            },
            "uvicorn.error": {
                "level": "INFO",
                "handlers": ["default", "file"],
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["default", "file"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }

    uvicorn.run(
        HttpApp, host=["::", "0.0.0.0"], port=config.port, log_config=log_config
    )


if __name__ == "__main__":
    main()
