import asyncio
import json
import os
import secrets
import shutil
import tempfile
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

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
    dependencies=[Depends(verification)],
)


def reset_http_server():
    log.info(f"disable_httpauth:{config.disable_httpauth}")
    if config.disable_httpauth:
        app.dependency_overrides[verification] = no_verification
    else:
        app.dependency_overrides = {}

    # 更新 music 链接
    app.router.routes = [route for route in app.router.routes if route.path != "/music"]
    app.mount(
        "/music",
        StaticFiles(directory=config.music_path, follow_symlink=True),
        name="music",
    )


def HttpInit(_xiaomusic):
    global xiaomusic, config, log
    xiaomusic = _xiaomusic
    config = xiaomusic.config
    log = xiaomusic.log

    folder = os.path.dirname(__file__)
    app.mount("/static", StaticFiles(directory=f"{folder}/static"), name="static")
    reset_http_server()


@app.get("/")
async def read_index():
    folder = os.path.dirname(__file__)
    return FileResponse(f"{folder}/static/index.html")


@app.get("/getversion")
def getversion():
    log.debug("getversion %s", __version__)
    return {"version": __version__}


@app.get("/getvolume")
async def getvolume(did: str = ""):
    if not xiaomusic.did_exist(did):
        return {"volume": 0}

    volume = await xiaomusic.get_volume(did=did)
    return {"volume": volume}


class DidVolume(BaseModel):
    did: str
    volume: int = 0


@app.post("/setvolume")
async def setvolume(data: DidVolume):
    did = data.did
    volume = data.volume
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    log.info(f"set_volume {did} {volume}")
    await xiaomusic.set_volume(did=did, arg1=volume)
    return {"ret": "OK", "volume": volume}


@app.get("/searchmusic")
def searchmusic(name: str = ""):
    return xiaomusic.searchmusic(name)


@app.get("/playingmusic")
def playingmusic(did: str = ""):
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    is_playing = xiaomusic.isplaying(did)
    cur_music = xiaomusic.playingmusic(did)
    return {
        "ret": "OK",
        "is_playing": is_playing,
        "cur_music": cur_music,
    }


class DidCmd(BaseModel):
    did: str
    cmd: str


@app.post("/cmd")
async def do_cmd(data: DidCmd):
    did = data.did
    cmd = data.cmd
    log.info(f"docmd. did:{did} cmd:{cmd}")
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    if len(cmd) > 0:
        await xiaomusic.cancel_all_tasks()
        task = asyncio.create_task(xiaomusic.do_check_cmd(did=did, query=cmd))
        xiaomusic.append_running_task(task)
        return {"ret": "OK"}
    return {"ret": "Unknow cmd"}


@app.get("/getsetting")
async def getsetting(need_device_list: bool = False):
    config = xiaomusic.getconfig()
    data = asdict(config)
    if need_device_list:
        device_list = await xiaomusic.getalldevices()
        log.info(f"getsetting device_list: {device_list}")
        data["device_list"] = device_list
    return data


@app.post("/savesetting")
async def savesetting(request: Request):
    try:
        data_json = await request.body()
        data = json.loads(data_json.decode("utf-8"))
        debug_data = deepcopy_data_no_sensitive_info(data)
        log.info(f"saveconfig: {debug_data}")
        await xiaomusic.saveconfig(data)
        reset_http_server()
        return "save success"
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON") from err


@app.get("/musiclist")
async def musiclist(Verifcation=Depends(verification)):
    return xiaomusic.get_music_list()


@app.get("/curplaylist")
async def curplaylist(did: str = ""):
    if not xiaomusic.did_exist(did):
        return ""
    return xiaomusic.get_cur_play_list(did)


class MusicItem(BaseModel):
    name: str


@app.post("/delmusic")
def delmusic(data: MusicItem):
    log.info(data)
    xiaomusic.del_music(data.name)
    return "success"


class UrlInfo(BaseModel):
    url: str


@app.post("/downloadjson")
async def downloadjson(data: UrlInfo):
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
async def playurl(did: str, url: str):
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    log.info(f"playurl did: {did} url: {url}")
    return await xiaomusic.play_url(did=did, arg1=url)


@app.post("/debug_play_by_music_url")
async def debug_play_by_music_url(request: Request):
    try:
        data = await request.body()
        data_dict = json.loads(data.decode("utf-8"))
        log.info(f"data:{data_dict}")
        return await xiaomusic.debug_play_by_music_url(arg1=data_dict)
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON") from err
