import asyncio
import hashlib
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
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.responses import FileResponse, Response

from xiaomusic import __version__
from xiaomusic.utils import (
    convert_file_to_mp3,
    deepcopy_data_no_sensitive_info,
    download_one_music,
    download_playlist,
    downloadfile,
    get_latest_version,
    is_mp3,
    remove_common_prefix,
    remove_id3_tags,
    try_add_access_control_param,
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
    url = xiaomusic.get_music_url(name)
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
        url = xiaomusic.get_music_url(music_name)
        info = {
            "name": music_name,
            "url": url,
        }
        if musictag:
            info["tags"] = xiaomusic.get_music_tags(music_name)
        ret.append(info)
    return ret


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
        download_proc = await download_playlist(config, data.url, data.dirname)

        async def check_download_proc():
            # 等待子进程完成
            exit_code = await download_proc.wait()
            log.info(f"Download completed with exit code {exit_code}")

            dir_path = os.path.join(config.download_path, data.dirname)
            log.debug(f"Download dir_path: {dir_path}")
            # 可能只是部分失败，都需要整理下载目录
            remove_common_prefix(dir_path)

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
        await download_one_music(config, data.url, data.name)
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


range_pattern = re.compile(r"bytes=(\d+)-(\d*)")


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

    # 移除MP3 ID3 v2标签和填充，减少播放前延迟
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

    mime_type, _ = mimetypes.guess_type(absolute_file_path)
    if mime_type is None:
        mime_type = "image/jpeg"
    return FileResponse(absolute_file_path, media_type=mime_type)
