import asyncio
import base64
import hashlib
import json
import os
import secrets
import shutil
import tempfile
import urllib.parse
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlparse

import socketio

if TYPE_CHECKING:
    from xiaomusic.xiaomusic import XiaoMusic

if TYPE_CHECKING:
    from xiaomusic.xiaomusic import XiaoMusic

import aiofiles
import aiohttp
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import FileResponse, Response

from xiaomusic import __version__
from xiaomusic.utils import (
    check_bili_fav_list,
    chmoddir,
    convert_file_to_mp3,
    deepcopy_data_no_sensitive_info,
    download_one_music,
    download_playlist,
    downloadfile,
    get_latest_version,
    is_mp3,
    remove_common_prefix,
    remove_id3_tags,
    restart_xiaomusic,
    safe_join_path,
    try_add_access_control_param,
    update_version,
)

xiaomusic: "XiaoMusic" = None
config = None
log = None


# 3thplay指令
class Item(BaseModel):
    action: str
    args: str


# 在线用户
onlines = set()


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
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# 创建Socket.IO实例
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",  # 允许所有跨域请求，生产环境应限制
)
# 将Socket.IO挂载到FastAPI应用
socketio_app = socketio.ASGIApp(
    socketio_server=sio, other_asgi_app=app, socketio_path="/socket.io"
)


# Socket.IO事件处理
@sio.event
async def connect(sid, environ, auth):
    global onlines
    print(f"客户端连接: {sid}")
    onlines.update([sid])
    await sio.emit("message", {"data": "欢迎连接"}, room=sid)


@sio.event
async def disconnect(sid):
    print(f"客户端断开: {sid}")
    onlines.discard(sid)


@sio.on("message")
async def custom_event(sid, data):
    log.info(f"收到来自 {sid} 的数据: {data}")
    await sio.emit("response", {"action": "切歌", "status": data})


@app.post("/thdaction")
async def thdaction(item: Item):
    await sio.emit(
        "response",
        {"action": item.action, "args": item.args, "status": item.args},
    )
    return onlines


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许访问的源
    allow_credentials=False,  # 支持 cookie
    allow_methods=["*"],  # 允许使用的请求方法
    allow_headers=["*"],  # 允许携带的 Headers
)
# 添加 GZip 中间件
app.add_middleware(GZipMiddleware, minimum_size=500)


def reset_http_server():
    log.info(f"disable_httpauth:{config.disable_httpauth}")
    if config.disable_httpauth:
        app.dependency_overrides[verification] = no_verification
    else:
        app.dependency_overrides = {}


class AuthStaticFiles(StaticFiles):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send) -> None:
        request = Request(scope, receive)
        if not config.disable_httpauth:
            assert verification(await security(request))
        await super().__call__(scope, receive, send)


def HttpInit(_xiaomusic):
    global xiaomusic, config, log, onlines
    xiaomusic = _xiaomusic
    config = xiaomusic.config
    log = xiaomusic.log
    onlines = set()
    folder = os.path.dirname(__file__)
    app.mount("/static", AuthStaticFiles(directory=f"{folder}/static"), name="static")
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
    cur_playlist = xiaomusic.get_cur_play_list(did)
    # 播放进度
    offset, duration = xiaomusic.get_offset_duration(did)
    return {
        "ret": "OK",
        "is_playing": is_playing,
        "cur_music": cur_music,
        "cur_playlist": cur_playlist,
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


@app.get("/cmdstatus")
async def cmd_status(Verifcation=Depends(verification)):
    finish = await xiaomusic.is_task_finish()
    if finish:
        return {"ret": "OK", "status": "finish"}
    return {"ret": "OK", "status": "running"}


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
async def musicinfo(
    name: str, musictag: bool = False, Verifcation=Depends(verification)
):
    url, _ = await xiaomusic.get_music_url(name)
    info = {
        "ret": "OK",
        "name": name,
        "url": url,
    }
    if musictag:
        info["tags"] = xiaomusic.get_music_tags(name)
    return info


@app.get("/musicinfos")
async def musicinfos(
    name: list[str] = Query(None),
    musictag: bool = False,
    Verifcation=Depends(verification),
):
    ret = []
    for music_name in name:
        url, _ = await xiaomusic.get_music_url(music_name)
        info = {
            "name": music_name,
            "url": url,
        }
        if musictag:
            info["tags"] = xiaomusic.get_music_tags(music_name)
        ret.append(info)
    return ret


class MusicInfoObj(BaseModel):
    musicname: str
    title: str = ""
    artist: str = ""
    album: str = ""
    year: str = ""
    genre: str = ""
    lyrics: str = ""
    picture: str = ""  # base64


@app.post("/setmusictag")
async def setmusictag(info: MusicInfoObj, Verifcation=Depends(verification)):
    ret = xiaomusic.set_music_tag(info.musicname, info)
    return {"ret": ret}


@app.get("/curplaylist")
async def curplaylist(did: str = "", Verifcation=Depends(verification)):
    if not xiaomusic.did_exist(did):
        return ""
    return xiaomusic.get_cur_play_list(did)


class MusicItem(BaseModel):
    name: str


@app.post("/delmusic")
async def delmusic(data: MusicItem, Verifcation=Depends(verification)):
    log.info(data)
    await xiaomusic.del_music(data.name)
    return "success"


class UrlInfo(BaseModel):
    url: str


class DidPlayMusic(BaseModel):
    did: str
    musicname: str = ""
    searchkey: str = ""


@app.post("/playmusic")
async def playmusic(data: DidPlayMusic, Verifcation=Depends(verification)):
    did = data.did
    musicname = data.musicname
    searchkey = data.searchkey
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    log.info(f"playmusic {did} musicname:{musicname} searchkey:{searchkey}")
    await xiaomusic.do_play(did, musicname, searchkey)
    return {"ret": "OK"}


class DidPlayMusicList(BaseModel):
    did: str
    listname: str = ""
    musicname: str = ""


@app.post("/playmusiclist")
async def playmusiclist(data: DidPlayMusicList, Verifcation=Depends(verification)):
    did = data.did
    listname = data.listname
    musicname = data.musicname
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    log.info(f"playmusiclist {did} listname:{listname} musicname:{musicname}")
    await xiaomusic.do_play_music_list(did, listname, musicname)
    return {"ret": "OK"}


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


@app.get("/playtts")
async def playtts(did: str, text: str, Verifcation=Depends(verification)):
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    log.info(f"tts {did} {text}")
    await xiaomusic.do_tts(did=did, value=text)
    return {"ret": "OK"}


@app.post("/refreshmusictag")
async def refreshmusictag(Verifcation=Depends(verification)):
    xiaomusic.refresh_music_tag()
    return {
        "ret": "OK",
    }


@app.post("/debug_play_by_music_url")
async def debug_play_by_music_url(request: Request, Verifcation=Depends(verification)):
    try:
        data = await request.body()
        data_dict = json.loads(data.decode("utf-8"))
        log.info(f"data:{data_dict}")
        return await xiaomusic.debug_play_by_music_url(arg1=data_dict)
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON") from err


@app.get("/latestversion")
async def latest_version(Verifcation=Depends(verification)):
    version = await get_latest_version("xiaomusic")
    if version:
        return {"ret": "OK", "version": version}
    else:
        return {"ret": "Fetch version failed"}


class DownloadPlayList(BaseModel):
    dirname: str
    url: str


# 下载歌单
@app.post("/downloadplaylist")
async def downloadplaylist(data: DownloadPlayList, Verifcation=Depends(verification)):
    try:
        bili_fav_list = await check_bili_fav_list(data.url)
        download_proc_list = []
        if bili_fav_list:
            for bvid, title in bili_fav_list.items():
                bvurl = f"https://www.bilibili.com/video/{bvid}"
                download_proc_list[title] = await download_one_music(
                    config, bvurl, os.path.join(data.dirname, title)
                )
            for title, download_proc_sigle in download_proc_list.items():
                exit_code = await download_proc_sigle.wait()
                log.info(f"Download completed {title} with exit code {exit_code}")
            dir_path = safe_join_path(config.download_path, data.dirname)
            log.debug(f"Download dir_path: {dir_path}")
            # 可能只是部分失败，都需要整理下载目录
            remove_common_prefix(dir_path)
            chmoddir(dir_path)
            return {"ret": "OK"}
        else:
            download_proc = await download_playlist(config, data.url, data.dirname)

        async def check_download_proc():
            # 等待子进程完成
            exit_code = await download_proc.wait()
            log.info(f"Download completed with exit code {exit_code}")

            dir_path = safe_join_path(config.download_path, data.dirname)
            log.debug(f"Download dir_path: {dir_path}")
            # 可能只是部分失败，都需要整理下载目录
            remove_common_prefix(dir_path)
            chmoddir(dir_path)

        asyncio.create_task(check_download_proc())
        return {"ret": "OK"}
    except Exception as e:
        log.exception(f"Execption {e}")

    return {"ret": "Failed download"}


class DownloadOneMusic(BaseModel):
    name: str = ""
    url: str


# 下载单首歌曲
@app.post("/downloadonemusic")
async def downloadonemusic(data: DownloadOneMusic, Verifcation=Depends(verification)):
    try:
        download_proc = await download_one_music(config, data.url, data.name)

        async def check_download_proc():
            # 等待子进程完成
            exit_code = await download_proc.wait()
            log.info(f"Download completed with exit code {exit_code}")
            chmoddir(config.download_path)

        asyncio.create_task(check_download_proc())
        return {"ret": "OK"}
    except Exception as e:
        log.exception(f"Execption {e}")

    return {"ret": "Failed download"}


# 上传 yt-dlp cookies
@app.post("/uploadytdlpcookie")
async def upload_yt_dlp_cookie(file: UploadFile = File(...)):
    with open(config.yt_dlp_cookies_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {
        "ret": "OK",
        "filename": file.filename,
        "file_location": config.yt_dlp_cookies_path,
    }


class PlayListObj(BaseModel):
    name: str = ""  # 歌单名


# 新增歌单
@app.post("/playlistadd")
async def playlistadd(data: PlayListObj, Verifcation=Depends(verification)):
    ret = xiaomusic.play_list_add(data.name)
    if ret:
        return {"ret": "OK"}
    return {"ret": "Add failed, may be already exist."}


# 移除歌单
@app.post("/playlistdel")
async def playlistdel(data: PlayListObj, Verifcation=Depends(verification)):
    ret = xiaomusic.play_list_del(data.name)
    if ret:
        return {"ret": "OK"}
    return {"ret": "Del failed, may be not exist."}


class PlayListUpdateObj(BaseModel):
    oldname: str  # 旧歌单名字
    newname: str  # 新歌单名字


# 修改歌单名字
@app.post("/playlistupdatename")
async def playlistupdatename(
    data: PlayListUpdateObj, Verifcation=Depends(verification)
):
    ret = xiaomusic.play_list_update_name(data.oldname, data.newname)
    if ret:
        return {"ret": "OK"}
    return {"ret": "Update failed, may be not exist."}


# 获取所有自定义歌单
@app.get("/playlistnames")
async def getplaylistnames(Verifcation=Depends(verification)):
    names = xiaomusic.get_play_list_names()
    log.info(f"names {names}")
    return {
        "ret": "OK",
        "names": names,
    }


class PlayListMusicObj(BaseModel):
    name: str = ""  # 歌单名
    music_list: list[str]  # 歌曲名列表


# 歌单新增歌曲
@app.post("/playlistaddmusic")
async def playlistaddmusic(data: PlayListMusicObj, Verifcation=Depends(verification)):
    ret = xiaomusic.play_list_add_music(data.name, data.music_list)
    if ret:
        return {"ret": "OK"}
    return {"ret": "Add failed, may be playlist not exist."}


# 歌单移除歌曲
@app.post("/playlistdelmusic")
async def playlistdelmusic(data: PlayListMusicObj, Verifcation=Depends(verification)):
    ret = xiaomusic.play_list_del_music(data.name, data.music_list)
    if ret:
        return {"ret": "OK"}
    return {"ret": "Del failed, may be playlist not exist."}


# 歌单更新歌曲
@app.post("/playlistupdatemusic")
async def playlistupdatemusic(
    data: PlayListMusicObj, Verifcation=Depends(verification)
):
    ret = xiaomusic.play_list_update_music(data.name, data.music_list)
    if ret:
        return {"ret": "OK"}
    return {"ret": "Del failed, may be playlist not exist."}


# 获取歌单中所有歌曲
@app.get("/playlistmusics")
async def getplaylist(name: str, Verifcation=Depends(verification)):
    ret, musics = xiaomusic.play_list_musics(name)
    return {
        "ret": "OK",
        "musics": musics,
    }


# 更新版本
@app.post("/updateversion")
async def updateversion(
    version: str = "", lite: bool = True, Verifcation=Depends(verification)
):
    ret = await update_version(version, lite)
    if ret != "OK":
        return {"ret": ret}

    asyncio.create_task(restart_xiaomusic())
    return {"ret": "OK"}


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


def access_key_verification(file_path, key, code):
    if config.disable_httpauth:
        return True

    log.debug(f"访问限制接收端[{file_path}, {key}, {code}]")
    if key is not None:
        current_key_bytes = key.encode("utf8")
        correct_key_bytes = (
            config.httpauth_username + config.httpauth_password
        ).encode("utf8")
        is_correct_key = secrets.compare_digest(correct_key_bytes, current_key_bytes)
        if is_correct_key:
            return True

    if code is not None:
        current_code_bytes = code.encode("utf8")
        correct_code_bytes = (
            hashlib.sha256(
                (
                    file_path + config.httpauth_username + config.httpauth_password
                ).encode("utf-8")
            )
            .hexdigest()
            .encode("utf-8")
        )
        is_correct_code = secrets.compare_digest(correct_code_bytes, current_code_bytes)
        if is_correct_code:
            return True

    return False


def safe_redirect(url):
    url = try_add_access_control_param(config, url)
    url = url.replace("\\", "")
    if not urllib.parse.urlparse(url).netloc and not urllib.parse.urlparse(url).scheme:
        log.debug(f"redirect to {url}")
        return RedirectResponse(url=url)
    return None


@app.get("/music/{file_path:path}")
async def music_file(request: Request, file_path: str, key: str = "", code: str = ""):
    if not access_key_verification(f"/music/{file_path}", key, code):
        raise HTTPException(status_code=404, detail="File not found")

    absolute_path = os.path.abspath(config.music_path)
    absolute_file_path = os.path.normpath(os.path.join(absolute_path, file_path))
    if not absolute_file_path.startswith(absolute_path):
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.exists(absolute_file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # 移除MP3 ID3 v2标签和填充
    if config.remove_id3tag and is_mp3(file_path):
        log.info(f"remove_id3tag:{config.remove_id3tag}, is_mp3:True ")
        temp_mp3_file = remove_id3_tags(absolute_file_path, config)
        if temp_mp3_file:
            log.info(f"ID3 tag removed {absolute_file_path} to {temp_mp3_file}")
            redirect = safe_redirect(f"/music/{temp_mp3_file}")
            if redirect:
                return redirect
        else:
            log.info(f"No ID3 tag remove needed: {absolute_file_path}")

    if config.convert_to_mp3 and not is_mp3(file_path):
        temp_mp3_file = convert_file_to_mp3(absolute_file_path, config)
        if temp_mp3_file:
            log.info(f"Converted file: {absolute_file_path} to {temp_mp3_file}")
            redirect = safe_redirect(f"/music/{temp_mp3_file}")
            if redirect:
                return redirect
        else:
            log.warning(f"Failed to convert file to MP3 format: {absolute_file_path}")

    return FileResponse(absolute_file_path)


@app.options("/music/{file_path:path}")
async def music_options():
    headers = {
        "Accept-Ranges": "bytes",
    }
    return Response(headers=headers)


@app.get("/picture/{file_path:path}")
async def get_picture(request: Request, file_path: str, key: str = "", code: str = ""):
    if not access_key_verification(f"/picture/{file_path}", key, code):
        raise HTTPException(status_code=404, detail="File not found")

    absolute_path = os.path.abspath(config.picture_cache_path)
    absolute_file_path = os.path.normpath(os.path.join(absolute_path, file_path))
    if not absolute_file_path.startswith(absolute_path):
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.exists(absolute_file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(absolute_file_path)


@app.get("/docs", include_in_schema=False)
async def get_swagger_documentation(Verifcation=Depends(verification)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")


@app.get("/redoc", include_in_schema=False)
async def get_redoc_documentation(Verifcation=Depends(verification)):
    return get_redoc_html(openapi_url="/openapi.json", title="docs")


@app.get("/openapi.json", include_in_schema=False)
async def openapi(Verifcation=Depends(verification)):
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


@app.get("/proxy", summary="基于正常下载逻辑的代理接口")
async def proxy(urlb64: str):
    try:
        # 将Base64编码的URL解码为字符串
        url_bytes = base64.b64decode(urlb64)
        url = url_bytes.decode("utf-8")
        print(f"解码后的代理请求: {url}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Base64解码失败: {str(e)}") from e

    log.info(f"代理请求: {url}")

    parsed_url = urlparse(url)
    if not parsed_url.scheme or not parsed_url.netloc:
        # Fixed: Use a new exception instance since 'e' from previous block is out of scope
        invalid_url_exc = ValueError("URL缺少协议或域名")
        raise HTTPException(
            status_code=400, detail="无效的URL格式"
        ) from invalid_url_exc

    # 创建会话并确保关闭
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=600),
        connector=aiohttp.TCPConnector(ssl=True),
    )

    # 复用经过验证的请求头配置
    def get_wget_headers(parsed_url):
        return {
            "User-Agent": "Wget/1.21.3",
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "Keep-Alive",
        }

    async def close_session():
        if not session.closed:
            await session.close()

    try:
        # 复用download_file中的请求逻辑
        headers = get_wget_headers(parsed_url)
        resp = await session.get(url, headers=headers, allow_redirects=True)

        if resp.status not in (200, 206):
            await close_session()
            status_exc = ValueError(f"服务器返回状态码: {resp.status}")
            raise HTTPException(
                status_code=resp.status, detail=f"下载失败，状态码: {resp.status}"
            ) from status_exc

        # 流式生成器，与download_file的分块逻辑一致
        async def stream_generator():
            try:
                async for data in resp.content.iter_chunked(4096):
                    yield data
            finally:
                await close_session()

        # 提取文件名
        filename = parsed_url.path.split("/")[-1].split("?")[0] or "output.mp3"

        return StreamingResponse(
            stream_generator(),
            media_type=resp.headers.get("Content-Type", "audio/mpeg"),
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
            background=BackgroundTask(close_session),
        )

    except aiohttp.ClientConnectionError as e:
        await close_session()
        raise HTTPException(status_code=502, detail=f"连接错误: {str(e)}") from e
    except asyncio.TimeoutError as e:
        await close_session()
        raise HTTPException(status_code=504, detail="下载超时") from e
    except Exception as e:
        await close_session()
        raise HTTPException(status_code=500, detail=f"发生错误: {str(e)}") from e
