import json
import logging
import mimetypes
import os
import re
from contextlib import asynccontextmanager

import aiofiles
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

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


folder = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=f"{folder}/static"), name="static")


async def file_iterator(file_path, start, end):
    async with aiofiles.open(file_path, mode="rb") as file:
        await file.seek(start)
        chunk_size = 1024
        while start <= end:
            read_size = min(chunk_size, end - start + 1)
            data = await file.read(read_size)
            if not data:
                break
            start += len(data)
            yield data


range_pattern = re.compile(r"bytes=(\d+)-(\d*)")


@app.get("/music/{file_path:path}")
async def music_file(request: Request, file_path: str):
    absolute_path = os.path.abspath(config.music_path)
    absolute_file_path = os.path.normpath(os.path.join(absolute_path, file_path))
    if not absolute_file_path.startswith(absolute_path):
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.exists(absolute_file_path):
        raise HTTPException(status_code=404, detail="File not found")

    file_size = os.path.getsize(absolute_file_path)
    range_start, range_end = 0, file_size - 1

    range_header = request.headers.get("Range")
    log.info(f"music_file range_header {range_header}")
    if range_header:
        range_match = range_pattern.match(range_header)
        if range_match:
            range_start = int(range_match.group(1))
        if range_match.group(2):
            range_end = int(range_match.group(2))

        log.info(f"music_file in range {absolute_file_path}")

    log.info(f"music_file {range_start} {range_end} {absolute_file_path}")
    headers = {
        "Content-Range": f"bytes {range_start}-{range_end}/{file_size}",
        "Accept-Ranges": "bytes",
    }
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is None:
        mime_type = "application/octet-stream"
    return StreamingResponse(
        file_iterator(absolute_file_path, range_start, range_end),
        headers=headers,
        status_code=206 if range_header else 200,
        media_type=mime_type,
    )


@app.options("/music/{file_path:path}")
async def music_options():
    headers = {
        "Accept-Ranges": "bytes",
    }
    return Response(headers=headers)


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
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers),
        )
