"""FastAPI 应用实例和中间件配置"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from xiaomusic import __version__
from xiaomusic.api.dependencies import (
    AuthStaticFiles,
    reset_http_server,
)

if TYPE_CHECKING:
    from xiaomusic.xiaomusic import XiaoMusic

# 导入内部状态管理器
from xiaomusic.api.dependencies import _state


@asynccontextmanager
async def app_lifespan(app):
    """应用生命周期管理"""
    task = None
    if _state.is_initialized():
        task = asyncio.create_task(_state._xiaomusic.run_forever())
    try:
        yield
    except asyncio.CancelledError:
        # 正常关闭时的取消，不需要记录
        pass
    finally:
        # 关闭时取消后台任务
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                if _state.is_initialized():
                    _state._log.info("Background task cleanup: CancelledError")
            except Exception as e:
                if _state.is_initialized():
                    _state._log.error(f"Background task cleanup error: {e}")


# 创建 FastAPI 应用实例
app = FastAPI(
    lifespan=app_lifespan,
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许访问的源
    allow_credentials=False,  # 支持 cookie
    allow_methods=["*"],  # 允许使用的请求方法
    allow_headers=["*"],  # 允许携带的 Headers
)

# 添加 GZip 中间件
app.add_middleware(GZipMiddleware, minimum_size=500)


def HttpInit(_xiaomusic: "XiaoMusic"):
    """初始化 HTTP 服务器

    Args:
        _xiaomusic: XiaoMusic 实例
    """
    # 初始化应用状态
    _state.initialize(_xiaomusic)

    # 挂载静态文件
    folder = os.path.dirname(os.path.dirname(__file__))  # xiaomusic 目录
    app.mount("/static", AuthStaticFiles(directory=f"{folder}/static"), name="static")

    # 注册所有路由
    from xiaomusic.api.routers import register_routers

    register_routers(app)

    # 重置 HTTP 服务器配置
    reset_http_server(app)
