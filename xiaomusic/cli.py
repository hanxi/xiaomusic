#!/usr/bin/env python3
import argparse
import json
import logging
import os
import signal

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import LoggingIntegration, ignore_logger

LOGO = r"""
 __  __  _                   __  __                 _
 \ \/ / (_)   __ _    ___   |  \/  |  _   _   ___  (_)   ___
  \  /  | |  / _` |  / _ \  | |\/| | | | | | / __| | |  / __|
  /  \  | | | (_| | | (_) | | |  | | | |_| | \__ \ | | | (__
 /_/\_\ |_|  \__,_|  \___/  |_|  |_|  \__,_| |___/ |_|  \___|
          {}
"""


sentry_sdk.init(
    # dsn="https://659690a901a37237df8097a9eb95e60f@github.hanxi.cc/sentry/4508470200434688",
    dsn="https://ffe4962642d04b29afe62ebd1a065231@glitchtip.hanxi.cc/1",
    integrations=[
        AsyncioIntegration(),
        LoggingIntegration(
            level=logging.WARNING,
            event_level=logging.ERROR,
        ),
    ],
    # debug=True,
)
ignore_logger("miservice")


def main():
    import uvicorn

    from xiaomusic import __version__
    from xiaomusic.config import Config
    from xiaomusic.httpserver import HttpInit
    from xiaomusic.httpserver import socketio_app as HttpApp
    from xiaomusic.xiaomusic import XiaoMusic

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

    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": f"%(asctime)s [{__version__}] [%(levelname)s] %(message)s",
                "datefmt": "[%X]",
                "use_colors": False,
            },
            "access": {
                "format": f"%(asctime)s [{__version__}] [%(levelname)s] %(message)s",
                "datefmt": "[%X]",
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "level": "INFO",
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "access",
                "filename": config.log_file,
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 1,
            },
        },
        "loggers": {
            "uvicorn": {
                "handlers": [
                    "default",
                    "file",
                ],
                "level": "INFO",
            },
            "uvicorn.error": {
                "level": "INFO",
            },
            "uvicorn.access": {
                "handlers": [
                    "access",
                    "file",
                ],
                "level": "INFO",
                "propagate": False,
            },
        },
    }

    try:
        filename = config.getsettingfile()
        with open(filename, encoding="utf-8") as f:
            data = json.loads(f.read())
            config.update_config(data)
    except Exception as e:
        print(f"Execption {e}")

    def run_server(port):
        xiaomusic = XiaoMusic(config)
        HttpInit(xiaomusic)
        uvicorn.run(
            HttpApp,
            host=["0.0.0.0", "::"],
            port=port,
            log_config=LOGGING_CONFIG,
        )

    def signal_handler(sig, frame):
        print("主进程收到退出信号，准备退出...")
        os._exit(0)  # 退出主进程

    # 捕获主进程的退出信号
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    port = int(config.port)
    run_server(port)


if __name__ == "__main__":
    main()
