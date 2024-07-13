import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
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
        task = asyncio.create_task(xiaomusic.run_forever())
        yield
        task.cancel()


app = FastAPI(lifespan=app_lifespan)
security = HTTPBasic()


def HttpInit(_xiaomusic):
    global xiaomusic, config, log
    xiaomusic = _xiaomusic
    config = xiaomusic.config
    log = xiaomusic.log

    app.mount("/static", StaticFiles(directory="xiaomusic/static"), name="static")
    app.mount("/music", StaticFiles(directory=config.music_path), name="music")


def verification(creds: HTTPBasicCredentials = Depends(security)):
    username = creds.username
    password = creds.password

    if config.disable_httpauth:
        return True
    if config.httpauth_username == username and config.httpauth_password == password:
        return True
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )


@app.get("/")
async def read_index():
    return FileResponse("xiaomusic/static/index.html")


@app.get("/getversion")
def getversion():
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
    return {
        "ret": "OK",
        "is_playing": is_playing,
        "cur_music": cur_music,
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
        asyncio.create_task(xiaomusic.do_check_cmd(did=did, query=cmd))
        return {"ret": "OK"}
    return {"ret": "Unknow cmd"}


@app.get("/getsetting")
async def getsetting(need_device_list: bool = False, Verifcation=Depends(verification)):
    config = xiaomusic.getconfig()
    data = asdict(config)
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
        await xiaomusic.saveconfig(data)
        return "save success"
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON") from err


@app.get("/musiclist")
async def musiclist(Verifcation=Depends(verification)):
    return xiaomusic.get_music_list()


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
        return FileResponse(path=file_path, media_type="text/plain")
    else:
        return {"message": "File not found."}


@app.get("/playurl")
async def playurl(did: str, url: str, Verifcation=Depends(verification)):
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    log.info(f"playurl did: {did} url: {url}")
    return await xiaomusic.call_main_thread_function(
        xiaomusic.play_url, did=did, arg1=url
    )


@app.post("/debug_play_by_music_url")
async def debug_play_by_music_url(request: Request, Verifcation=Depends(verification)):
    try:
        data = await request.body()
        data_dict = json.loads(data.decode("utf-8"))
        log.info(f"data:{data_dict}")
        return await xiaomusic.debug_play_by_music_url(arg1=data_dict)
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON") from err
