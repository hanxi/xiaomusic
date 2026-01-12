"""文件操作路由"""

import asyncio
import base64
import os
import shutil
from urllib.parse import urlparse

import aiohttp
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import (
    FileResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.background import BackgroundTask

from xiaomusic.api.dependencies import (
    access_key_verification,
    config,
    log,
    verification,
    xiaomusic,
)
from xiaomusic.api.models import (
    DownloadOneMusic,
    DownloadPlayList,
    UrlInfo,
)
from xiaomusic.utils import (
    check_bili_fav_list,
    chmoddir,
    convert_file_to_mp3,
    download_one_music,
    download_playlist,
    downloadfile,
    is_mp3,
    remove_common_prefix,
    remove_id3_tags,
    safe_join_path,
    try_add_access_control_param,
)

router = APIRouter()


@router.post("/downloadjson")
async def downloadjson(data: UrlInfo, Verifcation=Depends(verification)):
    """下载 JSON"""
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


@router.post("/downloadplaylist")
async def downloadplaylist(data: DownloadPlayList, Verifcation=Depends(verification)):
    """下载歌单"""
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


@router.post("/downloadonemusic")
async def downloadonemusic(data: DownloadOneMusic, Verifcation=Depends(verification)):
    """下载单首歌曲"""
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


@router.post("/uploadytdlpcookie")
async def upload_yt_dlp_cookie(file: UploadFile = File(...)):
    """上传 yt-dlp cookies"""
    with open(config.yt_dlp_cookies_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {
        "ret": "OK",
        "filename": file.filename,
        "file_location": config.yt_dlp_cookies_path,
    }


@router.post("/uploadmusic")
async def upload_music(playlist: str = Form(...), file: UploadFile = File(...)):
    """上传音乐文件到当前播放列表对应的目录"""
    try:
        # 选择目标目录：优先尝试由播放列表中已有歌曲推断目录
        dest_dir = xiaomusic.music_path
        # 特殊歌单映射
        if playlist == "下载":
            dest_dir = xiaomusic.download_path
        elif playlist == "其他":
            dest_dir = xiaomusic.music_path
        else:
            # 如果播放列表中存在歌曲，从其中任意一首推断目录
            musics = xiaomusic.music_list.get(playlist, [])
            if musics and len(musics) > 0:
                first = musics[0]
                filepath = xiaomusic._music_library.all_music.get(first, "")
                if filepath:
                    dest_dir = os.path.dirname(filepath)

        # 确保目录存在
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)

        # 保存文件，避免路径穿越
        filename = os.path.basename(file.filename)
        if filename == "":
            raise HTTPException(status_code=400, detail="Invalid filename")

        dest_path = os.path.join(dest_dir, filename)
        # 避免覆盖已有文件，简单地添加序号后缀
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(dest_path):
            filename = f"{base}_{counter}{ext}"
            dest_path = os.path.join(dest_dir, filename)
            counter += 1

        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 修复权限并刷新列表索引
        try:
            chmoddir(dest_dir)
        except Exception:
            pass

        # 重新生成音乐列表索引
        try:
            xiaomusic.music_library().gen_all_music_list()
        except Exception:
            pass

        return {"ret": "OK", "filename": filename}
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"upload music failed: {e}")
        raise HTTPException(status_code=500, detail="Upload failed") from e


def safe_redirect(url):
    """安全重定向"""
    url = try_add_access_control_param(config, url)
    url = url.replace("\\", "")
    if not urlparse(url).netloc and not urlparse(url).scheme:
        log.debug(f"redirect to {url}")
        return RedirectResponse(url=url)
    return None


@router.get("/music/{file_path:path}")
async def music_file(request: Request, file_path: str, key: str = "", code: str = ""):
    """音乐文件访问"""
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


@router.options("/music/{file_path:path}")
async def music_options():
    """音乐文件 OPTIONS"""
    headers = {
        "Accept-Ranges": "bytes",
    }
    return Response(headers=headers)


@router.get("/picture/{file_path:path}")
async def get_picture(request: Request, file_path: str, key: str = "", code: str = ""):
    """图片文件访问"""
    if not access_key_verification(f"/picture/{file_path}", key, code):
        raise HTTPException(status_code=404, detail="File not found")

    absolute_path = os.path.abspath(config.picture_cache_path)
    absolute_file_path = os.path.normpath(os.path.join(absolute_path, file_path))
    if not absolute_file_path.startswith(absolute_path):
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.exists(absolute_file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(absolute_file_path)


@router.get("/proxy", summary="基于正常下载逻辑的代理接口")
async def proxy(urlb64: str):
    """代理接口"""
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
    def gen_headers(parsed_url):
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "priority": "u=0, i",
            "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        }
        return headers

    async def close_session():
        if not session.closed:
            await session.close()

    try:
        # 复用download_file中的请求逻辑
        headers = gen_headers(parsed_url)
        resp = await session.get(url, headers=headers, allow_redirects=True)

        log.info(f"proxy status: {resp.status}")
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
