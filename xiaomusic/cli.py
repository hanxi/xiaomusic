#!/usr/bin/env python3
import argparse
import json
import logging
import os
import signal
import sys

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
    from xiaomusic.api import HttpInit
    from xiaomusic.api import app as HttpApp
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

    xiaomusic_instance = None
    original_sigint_handler = None
    
    def signal_handler(sig, frame):
        """信号处理函数 - 立即关闭并退出"""
        print("\n收到中断信号，正在关闭...")
        # 设置退出标志，避免重复处理
        signal_handler.has_been_called = getattr(signal_handler, 'has_been_called', False)
        if signal_handler.has_been_called:
            print("程序正在关闭中，请稍候...")
            return
        signal_handler.has_been_called = True
        
        if xiaomusic_instance and hasattr(xiaomusic_instance, "js_plugin_manager") and xiaomusic_instance.js_plugin_manager:
            try:
                xiaomusic_instance.js_plugin_manager.shutdown()
                print("JS 插件管理器已关闭")
            except Exception as e:
                print(f"关闭 JS 插件管理器时出错: {e}")
        
        # 强制退出程序
        print("程序已退出")
        os._exit(0)
    
    # 提前注册信号处理函数，确保在 uvicorn 启动前生效
    original_sigint_handler = signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    print("[DEBUG] 信号处理函数已注册")
    
    def run_server(port):
        nonlocal xiaomusic_instance, original_sigint_handler
        xiaomusic_instance = XiaoMusic(config)
        HttpInit(xiaomusic_instance)

        try:
            # 使用 Uvicorn 的 Config 类来配置服务器，避免信号处理冲突
            from uvicorn import Config, Server
            
            uvicorn_config = Config(
                app=HttpApp,
                host="0.0.0.0",
                port=port,
                log_config=LOGGING_CONFIG,
            )
            server = Server(config=uvicorn_config)
            
            # 运行服务器
            import asyncio
            asyncio.run(server.serve())
        except ImportError:
            # 如果无法导入 Config 和 Server，则回退到原来的 uvicorn.run 方式
            uvicorn.run(
                HttpApp,
                host="0.0.0.0",
                port=port,
                log_config=LOGGING_CONFIG,
            )
        finally:
            # uvicorn 关闭后清理资源
            if (
                xiaomusic_instance
                and hasattr(xiaomusic_instance, "js_plugin_manager")
                and xiaomusic_instance.js_plugin_manager
            ):
                try:
                    xiaomusic_instance.js_plugin_manager.shutdown()
                    print("JS 插件管理器已关闭")
                except Exception as e:
                    print(f"关闭 JS 插件管理器时出错: {e}")

    port = int(config.port)
    run_server(port)


if __name__ == "__main__":
    main()
