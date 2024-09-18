import asyncio
import json
import mimetypes
import os
import re
import secrets
import shutil
import tempfile
import urllib.parse
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated

import aiofiles
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.responses import FileResponse, Response

from xiaomusic import __version__
from xiaomusic.utils import (
    deepcopy_data_no_sensitive_info,
    downloadfile,
)

xiaomusic = None
config = None
log = None


@asynccontextmanager
async def app_lifespan(app):
    if xiaomusic is not None:
        asyncio.create_task(xiaomusic.run_forever())
    try:
        yield
    except Exception as e:
        log.exception(f"Execption {e}")


security = HTTPBasic()


def verification(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
):
    current_username_bytes = credentials.username.encode("utf8")
    correct_username_bytes = config.httpauth_username.encode("utf8")
    is_correct_username = secrets.compare_digest(
        current_username_bytes, correct_username_bytes
    )
    current_password_bytes = credentials.password.encode("utf8")
    correct_password_bytes = config.httpauth_password.encode("utf8")
    is_correct_password = secrets.compare_digest(
        current_password_bytes, correct_password_bytes
    )
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


def no_verification():
    return True


app = FastAPI(
    lifespan=app_lifespan,
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许访问的源
    allow_credentials=False,  # 支持 cookie
    allow_methods=["*"],  # 允许使用的请求方法
    allow_headers=["*"],  # 允许携带的 Headers
)


def reset_http_server():
    log.info(f"disable_httpauth:{config.disable_httpauth}")
    if config.disable_httpauth:
        app.dependency_overrides[verification] = no_verification
    else:
        app.dependency_overrides = {}


def HttpInit(_xiaomusic):
    global xiaomusic, config, log
    xiaomusic = _xiaomusic
    config = xiaomusic.config
    log = xiaomusic.log

    folder = os.path.dirname(__file__)
    app.mount("/static", StaticFiles(directory=f"{folder}/static"), name="static")
    reset_http_server()


@app.get("/")
async def read_index(Verifcation=Depends(verification)):
    folder = os.path.dirname(__file__)
    return FileResponse(f"{folder}/static/index.html")


@app.get("/getversion")
def getversion(Verifcation=Depends(verification)):
    log.debug("getversion %s", __version__)
    return {"version": __version__}


@app.get("/getvolume")
async def getvolume(did: str = "", Verifcation=Depends(verification)):
    if not xiaomusic.did_exist(did):
        return {"volume": 0}

    volume = await xiaomusic.get_volume(did=did)
    return {"volume": volume}


class DidVolume(BaseModel):
    did: str
    volume: int = 0


@app.post("/setvolume")
async def setvolume(data: DidVolume, Verifcation=Depends(verification)):
    did = data.did
    volume = data.volume
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    log.info(f"set_volume {did} {volume}")
    await xiaomusic.set_volume(did=did, arg1=volume)
    return {"ret": "OK", "volume": volume}


@app.get("/searchmusic")
def searchmusic(name: str = "", Verifcation=Depends(verification)):
    return xiaomusic.searchmusic(name)


@app.get("/playingmusic")
def playingmusic(did: str = "", Verifcation=Depends(verification)):
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    is_playing = xiaomusic.isplaying(did)
    cur_music = xiaomusic.playingmusic(did)
    # 播放进度
    offset, duration = xiaomusic.get_offset_duration(did)
    return {
        "ret": "OK",
        "is_playing": is_playing,
        "cur_music": cur_music,
        "offset": offset,
        "duration": duration,
    }


class DidCmd(BaseModel):
    did: str
    cmd: str


@app.post("/cmd")
async def do_cmd(data: DidCmd, Verifcation=Depends(verification)):
    did = data.did
    cmd = data.cmd
    log.info(f"docmd. did:{did} cmd:{cmd}")
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    if len(cmd) > 0:
        try:
            await xiaomusic.cancel_all_tasks()
            task = asyncio.create_task(xiaomusic.do_check_cmd(did=did, query=cmd))
            xiaomusic.append_running_task(task)
        except Exception as e:
            log.warning(f"Execption {e}")
        return {"ret": "OK"}
    return {"ret": "Unknow cmd"}


@app.get("/getsetting")
async def getsetting(need_device_list: bool = False, Verifcation=Depends(verification)):
    config = xiaomusic.getconfig()
    data = asdict(config)
    data["password"] = "******"
    data["httpauth_password"] = "******"
    if need_device_list:
        device_list = await xiaomusic.getalldevices()
        log.info(f"getsetting device_list: {device_list}")
        data["device_list"] = device_list
    return data


@app.post("/savesetting")
async def savesetting(request: Request, Verifcation=Depends(verification)):
    try:
        data_json = await request.body()
        data = json.loads(data_json.decode("utf-8"))
        debug_data = deepcopy_data_no_sensitive_info(data)
        log.info(f"saveconfig: {debug_data}")
        config = xiaomusic.getconfig()
        if data["password"] == "******" or data["password"] == "":
            data["password"] = config.password
        if data["httpauth_password"] == "******" or data["httpauth_password"] == "":
            data["httpauth_password"] = config.httpauth_password
        await xiaomusic.saveconfig(data)
        reset_http_server()
        return "save success"
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON") from err


@app.get("/musiclist")
async def musiclist(Verifcation=Depends(verification)):
    return xiaomusic.get_music_list()


@app.get("/musicinfo")
async def musicinfo(name: str, Verifcation=Depends(verification)):
    url = xiaomusic.get_music_url(name)
    return {
        "ret": "OK",
        "name": name,
        "url": url,
    }


@app.get("/curplaylist")
async def curplaylist(did: str = "", Verifcation=Depends(verification)):
    if not xiaomusic.did_exist(did):
        return ""
    return xiaomusic.get_cur_play_list(did)


class MusicItem(BaseModel):
    name: str


@app.post("/delmusic")
def delmusic(data: MusicItem, Verifcation=Depends(verification)):
    log.info(data)
    xiaomusic.del_music(data.name)
    return "success"


class UrlInfo(BaseModel):
    url: str


@app.post("/downloadjson")
async def downloadjson(data: UrlInfo, Verifcation=Depends(verification)):
    log.info(data)
    url = data.url
    content = ""
    try:
        ret = "OK"
        content = await downloadfile(url)
    except Exception as e:
        log.exception(f"Execption {e}")
        ret = "Download JSON file failed."
    return {
        "ret": ret,
        "content": content,
    }


@app.get("/downloadlog")
def downloadlog(Verifcation=Depends(verification)):
    file_path = xiaomusic.config.log_file
    if os.path.exists(file_path):
        # 创建一个临时文件来保存日志的快照
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        try:
            with open(file_path, "rb") as f:
                shutil.copyfileobj(f, temp_file)
            temp_file.close()

            # 使用BackgroundTask在响应发送完毕后删除临时文件
            def cleanup_temp_file(tmp_file_path):
                os.remove(tmp_file_path)

            background_task = BackgroundTask(cleanup_temp_file, temp_file.name)
            return FileResponse(
                temp_file.name,
                media_type="text/plain",
                filename="xiaomusic.txt",
                background=background_task,
            )
        except Exception as e:
            os.remove(temp_file.name)
            raise HTTPException(
                status_code=500, detail="Error capturing log file"
            ) from e
    else:
        return {"message": "File not found."}


@app.get("/playurl")
async def playurl(did: str, url: str, Verifcation=Depends(verification)):
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}
    decoded_url = urllib.parse.unquote(url)
    log.info(f"playurl did: {did} url: {decoded_url}")
    return await xiaomusic.play_url(did=did, arg1=decoded_url)


@app.post("/debug_play_by_music_url")
async def debug_play_by_music_url(request: Request, Verifcation=Depends(verification)):
    try:
        data = await request.body()
        data_dict = json.loads(data.decode("utf-8"))
        log.info(f"data:{data_dict}")
        return await xiaomusic.debug_play_by_music_url(arg1=data_dict)
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON") from err


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
