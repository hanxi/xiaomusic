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

# 导入全局变量引用（将在 HttpInit 中初始化）
import xiaomusic.api.dependencies as deps


@asynccontextmanager
async def app_lifespan(app):
    """应用生命周期管理"""
    if deps.xiaomusic is not None:
        await asyncio.create_task(deps.xiaomusic.run_forever())
    try:
        yield
    except Exception as e:
        deps.log.exception(f"Execption {e}")


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
    # 设置全局变量
    deps.xiaomusic = _xiaomusic
    deps.config = _xiaomusic.config
    deps.log = _xiaomusic.log

    # 挂载静态文件
    folder = os.path.dirname(os.path.dirname(__file__))  # xiaomusic 目录
    app.mount("/static", AuthStaticFiles(directory=f"{folder}/static"), name="static")

    # 注册所有路由
    from xiaomusic.api.routers import register_routers

    register_routers(app)

    # 重置 HTTP 服务器配置
    reset_http_server(app)
