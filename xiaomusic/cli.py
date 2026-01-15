#!/usr/bin/env python3
import argparse
import json
import logging
import os
import signal

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import (
    LoggingIntegration,
    ignore_logger,
)

LOGO = r"""
 __  __  _                   __  __                 _
 \ \/ / (_)   __ _    ___   |  \/  |  _   _   ___  (_)   ___
  \  /  | |  / _` |  / _ \  | |\/| | | | | | / __| | |  / __|
  /  \  | | | (_| | | (_) | | |  | | | |_| | \__ \ | | | (__
 /_/\_\ |_|  \__,_|  \___/  |_|  |_|  \__,_| |___/ |_|  \___|
          {}
"""


sentry_sdk.init(
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
    from xiaomusic import __version__
    from xiaomusic.api import (
        HttpInit,
    )
    from xiaomusic.api import (
        app as HttpApp,
    )
    from xiaomusic.config import Config
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

    print(LOGO.format(f"XiaoMusic v{__version__} by: github.com/hanxi"), flush=True)

    options = parser.parse_args()
    config = Config.from_options(options)

    # 自定义过滤器，过滤掉关闭时的 CancelledError
    class CancelledErrorFilter(logging.Filter):
        def filter(self, record):
            if record.exc_info:
                exc_type = record.exc_info[0]
                if exc_type and exc_type.__name__ == "CancelledError":
                    return False
            return True

    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": f"%(asctime)s [{__version__}] [%(levelname)s] %(message)s",
                "datefmt": "[%Y-%m-%d %H:%M:%S]",
                "use_colors": False,
            },
            "access": {
                "format": f"%(asctime)s [{__version__}] [%(levelname)s] %(message)s",
                "datefmt": "[%Y-%m-%d %H:%M:%S]",
            },
        },
        "filters": {
            "cancelled_error": {
                "()": CancelledErrorFilter,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "filters": ["cancelled_error"],
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
                "filters": ["cancelled_error"],
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
        if not os.path.exists(filename):
            with open(filename, encoding="utf-8") as f:
                data = json.loads(f.read())
                config.update_config(data)
    except Exception as e:
        print(f"Execption {e}")

    import asyncio

    import uvicorn

    async def async_main(config: Config) -> None:
        xiaomusic = XiaoMusic(config)
        HttpInit(xiaomusic)
        port = int(config.port)

        # 创建 uvicorn 配置，禁用其信号处理
        uvicorn_config = uvicorn.Config(
            HttpApp,
            host=["0.0.0.0", "::"],
            port=port,
            log_config=LOGGING_CONFIG,
        )
        server = uvicorn.Server(uvicorn_config)

        # 自定义信号处理
        shutdown_initiated = False

        def handle_exit(signum, frame):
            nonlocal shutdown_initiated
            if not shutdown_initiated:
                shutdown_initiated = True
                print("\n正在关闭服务器...")
                server.should_exit = True

        signal.signal(signal.SIGINT, handle_exit)
        signal.signal(signal.SIGTERM, handle_exit)

        # 运行服务器
        await server.serve()

    asyncio.run(async_main(config))


if __name__ == "__main__":
    main()
