import json
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from xiaomusic import __version__
from xiaomusic.config import Config

config = Config()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(app):
    global config
    try:
        filename = config.getsettingfile()
        with open(filename) as f:
            data = json.loads(f.read())
            config.update_config(data)
    except Exception as e:
        log.exception(f"Execption {e}")
    yield


app = FastAPI(
    lifespan=app_lifespan,
    version=__version__,
)


def reset_gate():
    # 更新 music 链接
    app.router.routes = [route for route in app.router.routes if route.path != "/music"]
    app.mount(
        "/music",
        StaticFiles(directory=config.music_path, follow_symlink=True),
        name="music",
    )


folder = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=f"{folder}/static"), name="static")
reset_gate()


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(path: str, request: Request):
    async with httpx.AsyncClient() as client:
        port = config.port + 1
        url = f"http://127.0.0.1:{port}/{path}"
        response = await client.request(
            method=request.method,
            url=url,
            headers=request.headers,
            params=request.query_params,
            content=await request.body() if request.method in ["POST", "PUT"] else None,
        )
        if path == "savesetting":
            # 使用BackgroundTask在响应发送完毕后执行逻辑
            background_task = BackgroundTask(reset_gate)
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                background=background_task,
            )
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers),
        )
