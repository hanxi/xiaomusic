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

    from uvicorn.config import LOGGING_CONFIG

    LOGGING_CONFIG["formatters"]["access"] = {
        "format": f"%(asctime)s [{__version__}] [%(levelname)s] %(filename)s:%(lineno)d: %(message)s",
        "datefmt": "[%X]",
    }
    LOGGING_CONFIG["handlers"]["access"] = {
        "level": "INFO",
        "class": "logging.handlers.RotatingFileHandler",
        "formatter": "access",
        "filename": config.log_file,
        "maxBytes": 10 * 1024 * 1024,
        "backupCount": 1,
    }
    uvicorn.run(
        HttpApp,
        host=["::", "0.0.0.0"],
        port=config.port,
        log_config=LOGGING_CONFIG,
    )


if __name__ == "__main__":
    main()
