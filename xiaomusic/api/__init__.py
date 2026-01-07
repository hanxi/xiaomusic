"""API 模块统一入口"""

from xiaomusic.api.app import (
    HttpInit,
    app,
)

__all__ = ["app", "HttpInit"]
