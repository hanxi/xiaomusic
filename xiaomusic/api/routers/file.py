import asyncio
import base64
import os
import shutil
import uuid
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
from xiaomusic.music_library import get_proxy_token
from xiaomusic.utils.file_utils import (
    chmoddir,
    clean_temp_dir,
    remove_common_prefix,
    safe_join_path,
)
from xiaomusic.utils.music_utils import convert_file_to_mp3, is_mp3, remove_id3_tags
from xiaomusic.utils.network_utils import (
    check_bili_fav_list,
    download_one_music,
    download_playlist,
    downloadfile,
)
from xiaomusic.utils.system_utils import try_add_access_control_param

router = APIRouter()

# 下载任务状态管理
download_tasks = {}  # {task_id: {"total": 总数, "completed": 已完成数, "status": "pending|downloading|paused|stopped|completed|failed", "current_song": "当前歌曲名", "process": 进程对象}}


async def monitor_download_progress(task_id: str, dirname: str):
    """后台监控下载进度，通过统计mp3文件数量来更新

    Args:
        task_id: 任务ID
        dirname: 下载目录名
    """
    try:
        dir_path = safe_join_path(config.download_path, dirname)
        last_count = 0

        log.info(f"Monitor task started for {task_id}, watching directory: {dir_path}")

        while True:
            await asyncio.sleep(1)  # 每1秒检查一次

            # 检查任务是否还在进行中
            if task_id not in download_tasks:
                log.info(f"Task {task_id} not found, stopping monitor")
                break

            task = download_tasks[task_id]
            # 允许在 paused 状态下也继续监控（为继续做准备）
            if task["status"] not in ["downloading", "pending", "paused"]:
                log.info(f"Task {task_id} status is {task['status']}, stopping monitor")
                break

            # 统计已下载的mp3文件数量
            if os.path.exists(dir_path):
                try:
                    # 只统计.mp3文件，排除.m4a等临时文件
                    mp3_files = [f for f in os.listdir(dir_path) if f.endswith(".mp3")]
                    current_count = len(mp3_files)

                    # 只有当数量变化时才更新
                    if current_count > last_count:
                        download_tasks[task_id]["completed"] = current_count
                        download_tasks[task_id]["current_song"] = (
                            f"已下载 {current_count} 首歌曲..."
                        )
                        last_count = current_count
                        log.info(
                            f"Progress updated: {current_count} mp3 files downloaded"
                        )
                except Exception as e:
                    log.warning(f"Monitor progress error: {e}")
    except asyncio.CancelledError:
        log.info(f"Monitor task cancelled for {task_id}")
    except Exception as e:
        log.exception(f"Monitor task error: {e}")


async def monitor_download_progress_with_output(task_id: str, dirname: str, process):
    """后台监控下载进度，通过解析yt-dlp输出来获取总数和进度

    Args:
        task_id: 任务ID
        dirname: 下载目录名
        process: yt-dlp进程对象
    """
    try:
        dir_path = safe_join_path(config.download_path, dirname)
        last_count = 0
        import re

        log.info(f"Monitor task started for {task_id}, watching stderr")

        # 读取进程输出，解析总数和当前进度（yt-dlp输出到stderr）
        if process.stderr:
            line_count = 0
            while True:
                await asyncio.sleep(0.5)  # 每0.5秒检查一次，更实时

                # 检查任务状态
                if task_id not in download_tasks:
                    log.info(f"Task {task_id} not found, stopping monitor")
                    break

                task = download_tasks[task_id]
                if task["status"] not in ["downloading", "pending", "paused"]:
                    log.info(
                        f"Task {task_id} status is {task['status']}, stopping monitor"
                    )
                    break

                # 尝试从stderr读取一行
                try:
                    line = await asyncio.wait_for(
                        process.stderr.readline(), timeout=0.3
                    )
                    if not line:
                        # 没有更多输出，检查进程是否结束
                        if process.returncode is not None:
                            log.info(f"Process ended with code {process.returncode}")
                            break
                        continue

                    line_count += 1
                    line_str = line.decode("utf-8", errors="ignore").strip()

                    # 实时输出到日志，让用户看到进度
                    if line_str:
                        log.info(f"[yt-dlp] {line_str}")

                    # 每10行输出一次计数日志，避免太多
                    if line_count % 10 == 0:
                        log.debug(f"Read {line_count} lines from stderr")

                    # 解析 "Downloading X of Y" 或 "Downloading item X of Y"
                    match = re.search(
                        r"(?:Downloading|item)\s+(\d+)\s+of\s+(\d+)", line_str
                    )
                    if match:
                        current = int(match.group(1))
                        total = int(match.group(2))

                        # 更新任务状态
                        download_tasks[task_id]["completed"] = current
                        download_tasks[task_id]["total"] = total
                        download_tasks[task_id]["current_song"] = (
                            f"正在下载第 {current}/{total} 首..."
                        )
                        log.info(f"Parsed progress: {current}/{total}")

                    # 备用方案：统计已完成的mp3文件数（排除临时文件）
                    if os.path.exists(dir_path):
                        try:
                            # 只统计.mp3文件，排除.m4a等临时文件
                            mp3_files = [
                                f for f in os.listdir(dir_path) if f.endswith(".mp3")
                            ]
                            file_count = len(mp3_files)

                            if file_count > last_count:
                                # 如果还没有从输出中解析到total，使用文件数
                                if download_tasks[task_id]["total"] == 0:
                                    download_tasks[task_id]["completed"] = file_count
                                    download_tasks[task_id]["current_song"] = (
                                        f"已下载 {file_count} 首歌曲..."
                                    )
                                last_count = file_count
                                log.info(f"File count updated: {file_count} mp3 files")
                        except Exception as e:
                            log.warning(f"Count files error: {e}")

                except asyncio.TimeoutError:
                    # 读取超时，继续循环
                    continue
                except Exception as e:
                    log.warning(f"Read output error: {e}")
        else:
            log.warning(f"Process stderr is None, cannot monitor output")
            # 回退到简单的文件统计
            await monitor_download_progress(task_id, dirname)

    except asyncio.CancelledError:
        log.info(f"Monitor with output task cancelled for {task_id}")
    except Exception as e:
        log.exception(f"Monitor with output task error: {e}")


def _process_m3u8_content(m3u8_content: str, base_url: str, is_radio: bool) -> str:
    """处理 m3u8 文件内容，将资源 URL 替换为代理 URL

    Args:
        m3u8_content: m3u8 文件内容
        base_url: m3u8 文件的 URL（用于解析相对路径）
        is_radio: 是否为电台直播流

    Returns:
        str: 处理后的 m3u8 内容
    """
    from urllib.parse import urljoin

    lines = m3u8_content.split("\n")
    processed_lines = []

    for line in lines:
        stripped_line = line.strip()

        # 跳过注释行和空行
        if not stripped_line or stripped_line.startswith("#"):
            processed_lines.append(line)
            continue

        # 处理资源行（.ts、.m3u8 等）
        # 判断是否为 URL（包含协议或以 / 开头）
        if stripped_line.startswith(("http://", "https://", "/")):
            # 绝对 URL，直接使用
            resource_url = stripped_line
        else:
            # 相对 URL，需要拼接
            resource_url = urljoin(base_url, stripped_line)

        # 将资源 URL 替换为代理 URL，使用路径参数方式
        urlb64 = base64.b64encode(resource_url.encode("utf-8")).decode("utf-8")
        proxy_type = "radio" if is_radio else "music"
        proxy_url = f"/proxy/{proxy_type}?urlb64={urlb64}"

        processed_lines.append(proxy_url)

    return "\n".join(processed_lines)


@router.post("/api/file/cleantempdir")
async def cleantempdir(Verifcation=Depends(verification)):
    await clean_temp_dir(xiaomusic.config)
    log.info("clean_temp_dir ok")
    return {"ret": "OK"}


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
    task_id = str(uuid.uuid4())
    try:
        # 初始化任务状态
        download_tasks[task_id] = {
            "total": 0,
            "completed": 0,
            "status": "pending",
            "current_song": "",
            "dirname": data.dirname,
            "url": data.url,  # 保存URL以便重新开始
            "task_type": "playlist",  # 标记任务类型
            "created_at": asyncio.get_event_loop().time(),
        }

        bili_fav_list = await check_bili_fav_list(data.url)
        download_proc_list = []
        if bili_fav_list:
            total_songs = len(bili_fav_list)
            download_tasks[task_id]["total"] = total_songs
            download_tasks[task_id]["status"] = "downloading"

            for idx, (bvid, title) in enumerate(bili_fav_list.items(), 1):
                bvurl = f"https://www.bilibili.com/video/{bvid}"
                download_tasks[task_id]["current_song"] = (
                    f"{title} ({idx}/{total_songs})"
                )
                download_proc_list[title] = await download_one_music(
                    config, bvurl, os.path.join(data.dirname, title)
                )

            for title, download_proc_sigle in download_proc_list.items():
                exit_code = await download_proc_sigle.wait()
                log.info(f"Download completed {title} with exit code {exit_code}")
                download_tasks[task_id]["completed"] += 1

            dir_path = safe_join_path(config.download_path, data.dirname)
            log.debug(f"Download dir_path: {dir_path}")
            # 可能只是部分失败，都需要整理下载目录
            remove_common_prefix(dir_path)
            chmoddir(dir_path)

            download_tasks[task_id]["status"] = "completed"
            download_tasks[task_id]["current_song"] = ""
            return {"ret": "OK", "task_id": task_id}
        else:
            download_tasks[task_id]["status"] = "downloading"
            download_tasks[task_id]["current_song"] = "正在获取歌单信息..."
            download_tasks[task_id]["total"] = 0
            download_tasks[task_id]["completed"] = 0
            log.info(f"Starting download playlist: {data.url}")

            # 使用 yt-dlp Python API 快速获取总数
            try:
                import yt_dlp

                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": "in_playlist",  # 只提取播放列表结构，不下载
                    "skip_download": True,
                }

                log.info(f"Getting playlist count via yt-dlp API...")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(data.url, download=False)

                    if info and "entries" in info:
                        entries = list(info["entries"])
                        total_count = len(entries)
                        if total_count > 0:
                            download_tasks[task_id]["total"] = total_count
                            log.info(f"✓ Playlist has {total_count} items")
                        else:
                            log.warning("Empty playlist")
                    elif info and "playlist_count" in info:
                        total_count = info["playlist_count"]
                        if total_count > 0:
                            download_tasks[task_id]["total"] = total_count
                            log.info(f"✓ Playlist has {total_count} items")
                    else:
                        log.warning("Could not determine playlist size")
            except Exception as e:
                log.warning(
                    f"Error getting playlist count via API: {e} (continuing anyway)"
                )

            # 确保下载目录存在
            dir_path = safe_join_path(config.download_path, data.dirname)
            os.makedirs(dir_path, exist_ok=True)
            log.info(f"Download directory ensured: {dir_path}")

            download_tasks[task_id]["current_song"] = "正在解析歌单..."
            download_proc = await download_playlist(config, data.url, data.dirname)
            # 保存进程对象以便后续控制
            download_tasks[task_id]["process"] = download_proc
            log.info(f"Download process started, PID: {download_proc.pid}")

        async def check_download_proc():
            # 启动后台监控任务，通过文件统计来更新进度
            log.info(f"Starting monitor task for {task_id}")
            monitor_task = asyncio.create_task(
                monitor_download_progress(task_id, data.dirname)
            )

            try:
                # 等待子进程完成
                log.info(f"Waiting for download process to complete...")
                exit_code = await download_proc.wait()
                log.info(f"Download completed with exit code {exit_code}")

                # 停止监控任务
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass

                dir_path = safe_join_path(config.download_path, data.dirname)
                log.debug(f"Download dir_path: {dir_path}")
                # 可能只是部分失败，都需要整理下载目录
                remove_common_prefix(dir_path)
                chmoddir(dir_path)

                # 检查是否已被手动停止
                if download_tasks[task_id]["status"] == "stopped":
                    # 已经被停止，保持stopped状态
                    log.info(f"Task was already stopped, keeping status")
                else:
                    download_tasks[task_id]["status"] = (
                        "completed" if exit_code == 0 else "failed"
                    )
                    download_tasks[task_id]["current_song"] = ""
                    # 更新最终的完成数量
                    if os.path.exists(dir_path):
                        final_count = len(
                            [f for f in os.listdir(dir_path) if f.endswith(".mp3")]
                        )
                        download_tasks[task_id]["completed"] = final_count
                        download_tasks[task_id]["total"] = final_count
            except asyncio.CancelledError:
                log.info(f"Download task cancelled: {task_id}")
                monitor_task.cancel()
                download_tasks[task_id]["status"] = "stopped"
                download_tasks[task_id]["current_song"] = "已停止"
            except Exception as e:
                # 检查是否是因为被停止而导致的异常
                if download_tasks.get(task_id, {}).get("status") == "stopped":
                    log.info(f"Task was stopped, exception is expected: {e}")
                    # 已经被停止，保持stopped状态，不覆盖
                else:
                    log.exception(f"Download task error: {e}")
                    monitor_task.cancel()
                    download_tasks[task_id]["status"] = "failed"
                    download_tasks[task_id]["current_song"] = str(e)

        asyncio.create_task(check_download_proc())
        return {"ret": "OK", "task_id": task_id}
    except Exception as e:
        log.exception(f"Execption {e}")
        if task_id in download_tasks:
            download_tasks[task_id]["status"] = "failed"
            download_tasks[task_id]["current_song"] = str(e)

    return {"ret": "Failed download", "task_id": task_id}


@router.post("/downloadonemusic")
async def downloadonemusic(data: DownloadOneMusic, Verifcation=Depends(verification)):
    """下载单首歌曲

    Args:
        data.name: 文件名（可选）
        data.url: 下载链接（必填）
        data.dirname: 子目录名（可选，兼容字段），相对于 music 根目录
        data.playlist_name: 下载成功后要关联的歌单名（可选）
    """
    task_id = str(uuid.uuid4())
    try:
        # 初始化任务状态
        download_tasks[task_id] = {
            "total": 1,
            "completed": 0,
            "status": "downloading",
            "current_song": data.name or "正在下载...",
            "url": data.url,  # 保存URL以便重新开始
            "name": data.name,  # 保存文件名
            "dirname": data.dirname or "",  # 保存目录名
            "playlist_name": data.playlist_name or "",  # 保存歌单名
            "task_type": "single",  # 标记任务类型
            "created_at": asyncio.get_event_loop().time(),
        }

        pre_all_music_names = set(xiaomusic.music_library.all_music.keys())
        playlist_name = (data.playlist_name or "").strip()

        download_root = config.download_path
        if data.dirname:
            download_root = safe_join_path(config.music_path, data.dirname)
            os.makedirs(download_root, exist_ok=True)

        download_proc = await download_one_music(
            config,
            data.url,
            data.name,
            download_root=download_root,
        )
        # 保存进程对象以便后续控制
        download_tasks[task_id]["process"] = download_proc

        async def check_download_proc():
            # 对于单曲下载，设置初始状态
            download_tasks[task_id]["completed"] = 0
            download_tasks[task_id]["total"] = 1

            try:
                # 等待子进程完成
                exit_code = await download_proc.wait()
                log.info(f"Download completed with exit code {exit_code}")

                if exit_code != 0:
                    download_tasks[task_id]["status"] = "failed"
                    download_tasks[task_id]["current_song"] = "下载失败"
                    return

                # 下载成功，更新为完成
                download_tasks[task_id]["completed"] = 1
                download_tasks[task_id]["current_song"] = "下载完成"

                try:
                    chmoddir(download_root)
                except Exception:
                    pass

                try:
                    xiaomusic.music_library.gen_all_music_list()
                    xiaomusic.update_all_playlist()
                except Exception as e:
                    log.exception(f"refresh music list failed after download: {e}")
                    download_tasks[task_id]["status"] = "failed"
                    return

                if not playlist_name:
                    download_tasks[task_id]["status"] = "completed"
                    download_tasks[task_id]["completed"] = 1
                    download_tasks[task_id]["current_song"] = ""
                    return

                resolved_music_name = ""
                if data.name and data.name in xiaomusic.music_library.all_music:
                    resolved_music_name = data.name
                else:
                    new_music_names = [
                        name
                        for name in xiaomusic.music_library.all_music.keys()
                        if name not in pre_all_music_names
                    ]
                    if len(new_music_names) == 1:
                        resolved_music_name = new_music_names[0]
                    elif data.name:
                        for name in new_music_names:
                            if name.startswith(data.name):
                                resolved_music_name = name
                                break

                if not resolved_music_name:
                    log.warning(
                        f"download succeeded but failed to resolve music name for playlist: {playlist_name}"
                    )
                    download_tasks[task_id]["status"] = "completed"
                    download_tasks[task_id]["completed"] = 1
                    download_tasks[task_id]["current_song"] = ""
                    return

                added = xiaomusic.music_library.play_list_add_music(
                    playlist_name, [resolved_music_name]
                )
                if added:
                    xiaomusic.update_all_playlist()
                    log.info(
                        f"downloadonemusic auto add success: {resolved_music_name} -> {playlist_name}"
                    )
                else:
                    log.warning(
                        f"downloadonemusic auto add failed: {resolved_music_name} -> {playlist_name}"
                    )

                download_tasks[task_id]["status"] = "completed"
                download_tasks[task_id]["completed"] = 1
                download_tasks[task_id]["current_song"] = ""
            except asyncio.CancelledError:
                log.info(f"Download task cancelled: {task_id}")
                download_tasks[task_id]["status"] = "stopped"
                download_tasks[task_id]["current_song"] = "已停止"
            except Exception as e:
                log.exception(f"Download task error: {e}")
                download_tasks[task_id]["status"] = "failed"
                download_tasks[task_id]["current_song"] = str(e)

        asyncio.create_task(check_download_proc())
        return {"ret": "OK", "task_id": task_id}
    except Exception as e:
        log.exception(f"Execption {e}")
        if task_id in download_tasks:
            download_tasks[task_id]["status"] = "failed"
            download_tasks[task_id]["current_song"] = str(e)

    return {"ret": "Failed download", "task_id": task_id}


@router.get("/download_progress")
async def get_download_progress(task_id: str = ""):
    """获取下载任务进度

    Args:
        task_id: 任务ID，如果为空则返回所有任务

    Returns:
        dict: 下载任务进度信息
    """
    if task_id:
        # 返回指定任务
        if task_id in download_tasks:
            task = download_tasks[task_id]
            progress = 0
            if task["total"] > 0:
                progress = int((task["completed"] / task["total"]) * 100)

            return {
                "ret": "OK",
                "task_id": task_id,
                "total": task["total"],
                "completed": task["completed"],
                "progress": progress,
                "status": task["status"],
                "current_song": task["current_song"],
            }
        else:
            return {"ret": "Not found", "task_id": task_id}
    else:
        # 返回所有活跃任务
        active_tasks = {}
        current_time = asyncio.get_event_loop().time()

        for tid, task in list(download_tasks.items()):
            # 只返回未完成或最近5分钟完成的任务
            task_age = current_time - task.get("created_at", 0)
            if task["status"] in ["pending", "downloading"] or task_age < 300:
                progress = 0
                if task["total"] > 0:
                    progress = int((task["completed"] / task["total"]) * 100)

                active_tasks[tid] = {
                    "total": task["total"],
                    "completed": task["completed"],
                    "progress": progress,
                    "status": task["status"],
                    "current_song": task["current_song"],
                    "dirname": task.get("dirname", ""),
                }

        return {"ret": "OK", "tasks": active_tasks}


@router.post("/clear_completed_tasks")
async def clear_completed_tasks(Verifcation=Depends(verification)):
    """清理已完成的下载任务记录"""
    cleared_count = 0
    current_time = asyncio.get_event_loop().time()

    for task_id in list(download_tasks.keys()):
        task = download_tasks[task_id]
        task_age = current_time - task.get("created_at", 0)

        # 清理已完成超过5分钟的任务
        if task["status"] in ["completed", "failed", "stopped"] and task_age >= 300:
            del download_tasks[task_id]
            cleared_count += 1

    return {"ret": "OK", "cleared_count": cleared_count}


@router.post("/pause_download")
async def pause_download(task_id: str, Verifcation=Depends(verification)):
    """暂停下载任务

    Args:
        task_id: 任务ID

    Returns:
        dict: 操作结果
    """
    if task_id not in download_tasks:
        return {"ret": "Not found", "message": "任务不存在"}

    task = download_tasks[task_id]

    if task["status"] != "downloading":
        return {"ret": "Failed", "message": f"当前状态为{task['status']}，无法暂停"}

    try:
        # 暂停进程
        if "process" in task and task["process"]:
            import os
            import signal

            # Windows下使用CTRL_BREAK_EVENT，Unix下使用SIGSTOP
            if os.name == "nt":
                task["process"].send_signal(signal.CTRL_BREAK_EVENT)
            else:
                task["process"].send_signal(signal.SIGSTOP)

        task["status"] = "paused"
        task["current_song"] = "已暂停"

        log.info(f"Download task paused: {task_id}")
        return {"ret": "OK", "message": "已暂停下载"}
    except Exception as e:
        log.exception(f"Pause download failed: {e}")
        return {"ret": "Failed", "message": str(e)}


@router.post("/resume_download")
async def resume_download(task_id: str, Verifcation=Depends(verification)):
    """继续下载任务

    Args:
        task_id: 任务ID

    Returns:
        dict: 操作结果
    """
    if task_id not in download_tasks:
        return {"ret": "Not found", "message": "任务不存在"}

    task = download_tasks[task_id]

    if task["status"] != "paused":
        return {"ret": "Failed", "message": f"当前状态为{task['status']}，无法继续"}

    try:
        # 恢复进程
        if "process" in task and task["process"]:
            import os
            import signal

            # Windows下不支持SIGCONT，需要重新创建进程，这里简化处理
            if os.name != "nt":
                task["process"].send_signal(signal.SIGCONT)

        task["status"] = "downloading"
        task["current_song"] = "继续下载中..."

        log.info(f"Download task resumed: {task_id}")
        return {"ret": "OK", "message": "已继续下载"}
    except Exception as e:
        log.exception(f"Resume download failed: {e}")
        return {"ret": "Failed", "message": str(e)}


@router.post("/stop_download")
async def stop_download(task_id: str, Verifcation=Depends(verification)):
    """停止下载任务

    Args:
        task_id: 任务ID

    Returns:
        dict: 操作结果
    """
    if task_id not in download_tasks:
        return {"ret": "Not found", "message": "任务不存在"}

    task = download_tasks[task_id]

    if task["status"] in ["completed", "failed", "stopped"]:
        return {"ret": "Failed", "message": f"当前状态为{task['status']}，无法停止"}

    try:
        # 终止进程
        if "process" in task and task["process"]:
            try:
                task["process"].kill()
                await task["process"].wait()
            except Exception as e:
                log.warning(f"Kill process warning: {e}")

        task["status"] = "stopped"
        task["current_song"] = "已停止"

        log.info(f"Download task stopped: {task_id}")
        return {"ret": "OK", "message": "已停止下载"}
    except Exception as e:
        log.exception(f"Stop download failed: {e}")
        return {"ret": "Failed", "message": str(e)}


@router.post("/delete_download_task")
async def delete_download_task(task_id: str, Verifcation=Depends(verification)):
    """删除下载任务记录（仅针对已停止/完成/失败的任务）

    Args:
        task_id: 任务ID

    Returns:
        dict: 操作结果
    """
    if task_id not in download_tasks:
        return {"ret": "Not found", "message": "任务不存在"}

    task = download_tasks[task_id]

    # 只允许删除已停止、已完成或失败的任务
    if task["status"] in ["downloading", "paused", "pending"]:
        return {
            "ret": "Failed",
            "message": f"当前状态为{task['status']}，无法删除。请先停止任务。",
        }

    try:
        del download_tasks[task_id]
        log.info(f"Download task deleted: {task_id}")
        return {"ret": "OK", "message": "已删除任务记录"}
    except Exception as e:
        log.exception(f"Delete task failed: {e}")
        return {"ret": "Failed", "message": str(e)}


@router.post("/restart_download")
async def restart_download(task_id: str, Verifcation=Depends(verification)):
    """重新开始下载任务（仅针对已停止的任务）

    Args:
        task_id: 任务ID

    Returns:
        dict: 操作结果，包含新的task_id
    """
    if task_id not in download_tasks:
        return {"ret": "Not found", "message": "任务不存在"}

    old_task = download_tasks[task_id]

    # 只允许重新开始已停止的任务
    if old_task["status"] != "stopped":
        return {
            "ret": "Failed",
            "message": f"当前状态为{old_task['status']}，无法重新开始。",
        }

    try:
        task_type = old_task.get("task_type", "single")

        if task_type == "playlist":
            # 歌单下载：重新发起歌单下载请求
            from xiaomusic.api.models import DownloadPlayList

            data = DownloadPlayList(dirname=old_task["dirname"], url=old_task["url"])
            # 调用原有的下载函数
            result = await downloadplaylist(data, Verifcation)
            return result
        else:
            # 单曲下载：重新发起单曲下载请求
            from xiaomusic.api.models import DownloadOneMusic

            data = DownloadOneMusic(
                name=old_task.get("name", ""),
                url=old_task["url"],
                dirname=old_task.get("dirname", ""),
                playlist_name=old_task.get("playlist_name", ""),
            )
            # 调用原有的下载函数
            result = await downloadonemusic(data, Verifcation)
            return result

    except Exception as e:
        log.exception(f"Restart download failed: {e}")
        return {"ret": "Failed", "message": str(e)}


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
        dest_dir = config.music_path
        # 特殊歌单映射
        if playlist == "下载":
            dest_dir = config.download_path
        elif playlist == "其他":
            dest_dir = config.music_path
        else:
            # 如果播放列表中存在歌曲，从其中任意一首推断目录
            musics = xiaomusic.music_list.get(playlist, [])
            if musics and len(musics) > 0:
                first = musics[0]
                filepath = xiaomusic.music_library.all_music.get(first, "")
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
            xiaomusic.music_library.gen_all_music_list()
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

    # temp/ 前缀表示文件在 temp_path 中
    if file_path.startswith("temp/"):
        temp_file_name = file_path[5:]
        if config.temp_path.startswith("/"):
            temp_base = config.temp_path
        else:
            temp_base = os.path.abspath(config.temp_path)
        absolute_file_path = os.path.normpath(os.path.join(temp_base, temp_file_name))
        if not absolute_file_path.startswith(temp_base):
            raise HTTPException(status_code=404, detail="File not found")
        if not os.path.exists(absolute_file_path):
            raise HTTPException(status_code=404, detail="File not found")
    else:
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
            mp3_name = os.path.basename(temp_mp3_file)
            redirect = safe_redirect(f"/music/temp/{mp3_name}")
            if redirect:
                return redirect
        else:
            log.info(f"No ID3 tag remove needed: {absolute_file_path}")

    if config.convert_to_mp3 and not is_mp3(file_path):
        temp_mp3_file = convert_file_to_mp3(absolute_file_path, config)
        if temp_mp3_file:
            mp3_name = os.path.basename(temp_mp3_file)
            redirect = safe_redirect(f"/music/temp/{mp3_name}")
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


# bilibili CDN 精确域名后缀列表，避免 mcdn 等子串误伤其他插件
_BILI_CDN_SUFFIXES = ("bilivideo.com", "bilivideo.cn", "hdslb.com")


def _is_bili_cdn(netloc: str) -> bool:
    """精确匹配 bilibili CDN 域名（含子域名），不做宽泛子串匹配。

    注意 netloc 可能带端口（如 xy123.mcdn.bilivideo.cn:8082），匹配前需去掉端口。
    """
    host = (netloc or "").split(":", 1)[0].lower()
    return any(host == s or host.endswith("." + s) for s in _BILI_CDN_SUFFIXES)


async def _ffmpeg_mp3_stream(url: str, extra_headers: dict = None):
    """下载音视频流，pipe 给 FFmpeg stdin 转码为 MP3

    Args:
        url: 音视频直链 URL
        extra_headers: 附加请求头（如 bilibili 需要的 Referer/Origin）
    """
    import asyncio as _asyncio

    headers = {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    if extra_headers:
        headers.update(extra_headers)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        "pipe:0",
        "-vn",
        "-acodec",
        "libmp3lame",
        "-b:a",
        "128k",
        "-f",
        "mp3",
        "pipe:1",
    ]
    proc = await _asyncio.create_subprocess_exec(
        *cmd,
        stdin=_asyncio.subprocess.PIPE,
        stdout=_asyncio.subprocess.PIPE,
        stderr=_asyncio.subprocess.DEVNULL,
    )

    async def _feed_ffmpeg():
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=600, sock_read=60),
                connector=aiohttp.TCPConnector(ssl=True),
            ) as session:
                async with session.get(url, headers=headers) as resp:
                    async for chunk in resp.content.iter_chunked(65536):
                        if proc.stdin.is_closing():
                            break
                        proc.stdin.write(chunk)
                        await proc.stdin.drain()
        except Exception as _fe:
            log.exception(f"[bili-ffmpeg] _feed_ffmpeg error: {_fe}")
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass

    _asyncio.create_task(_feed_ffmpeg())

    async def _gen():
        try:
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                proc.kill()
            except Exception:
                pass
            await proc.wait()

    return StreamingResponse(
        _gen(),
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="output.mp3"'},
    )


async def _proxy_handler(urlb64: str, is_radio: bool):
    """代理处理核心逻辑

    Args:
        urlb64: Base64编码的URL
        is_radio: 是否为电台直播流

    Returns:
        Response: 代理响应
    """
    request_id = uuid.uuid4().hex[:8]
    try:
        # 将Base64编码的URL解码为字符串
        url_bytes = base64.b64decode(urlb64)
        url = url_bytes.decode("utf-8")
    except Exception as e:
        log.exception(
            f"[proxy:{request_id}] Base64解码失败 is_radio={is_radio} urlb64_prefix={urlb64[:80]!r}"
        )
        raise HTTPException(status_code=400, detail=f"Base64解码失败: {str(e)}") from e

    log.info(f"[proxy:{request_id}] start is_radio={is_radio} url={url[:500]}")

    parsed_url, url = xiaomusic.music_library.expand_self_url(url)
    log.info(
        f"[proxy:{request_id}] expand_self_url parsed={parsed_url} final_url={url[:500]}"
    )
    if not parsed_url.scheme or not parsed_url.netloc:
        invalid_url_exc = ValueError("URL缺少协议或域名")
        log.warning(
            f"[proxy:{request_id}] invalid url parsed={parsed_url} final_url={url[:500]}"
        )
        raise HTTPException(
            status_code=400, detail="无效的URL格式"
        ) from invalid_url_exc

    # bilibili CDN URL → FFmpeg 转码为 MP3，避免 LX06 固件格式不兼容
    # 使用精确域名后缀匹配，避免 mcdn 等子串误伤其他插件；电台流不走 FFmpeg
    if not is_radio and _is_bili_cdn(parsed_url.netloc):
        log.info(
            f"[proxy:{request_id}] direct bili cdn detected netloc={parsed_url.netloc} -> ffmpeg url={url[:500]}"
        )
        return await _ffmpeg_mp3_stream(
            url,
            extra_headers={
                "referer": "https://www.bilibili.com",
                "origin": "https://www.bilibili.com",
            },
        )

    # 直播流使用更长的超时时间（24小时），普通文件使用10分钟
    timeout_seconds = 86400 if is_radio else 600
    log.info(
        f"[proxy:{request_id}] mode={'radio' if is_radio else 'music'} timeout={timeout_seconds}s netloc={parsed_url.netloc}"
    )

    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout_seconds, sock_read=300),
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
        if parsed_url.netloc == config.get_self_netloc():
            headers["Authorization"] = config.get_basic_auth()
        # bilibili CDN 防盗链需要 Referer（精确匹配，避免误伤其他插件）
        if _is_bili_cdn(parsed_url.netloc):
            headers["referer"] = "https://www.bilibili.com"
            headers["origin"] = "https://www.bilibili.com"
        return headers

    async def close_session():
        if not session.closed:
            await session.close()

    try:
        # 复用download_file中的请求逻辑
        headers = gen_headers(parsed_url)
        safe_headers = {
            k: ("***" if k.lower() == "authorization" else v)
            for k, v in headers.items()
        }
        log.info(
            f"[proxy:{request_id}] initial GET url={url[:500]} headers={safe_headers}"
        )
        # 手动处理重定向，确保 bilibili CDN 重定向后仍携带 Referer
        resp = await session.get(url, headers=headers, allow_redirects=False)
        max_redirects = 5
        redirect_count = 0
        while (
            resp.status in (301, 302, 303, 307, 308) and redirect_count < max_redirects
        ):
            redirect_url = resp.headers.get("Location", "")
            log.info(
                f"[proxy:{request_id}] redirect#{redirect_count + 1} status={resp.status} from={resp.url} to={redirect_url[:500]}"
            )
            if not redirect_url:
                break
            await resp.release()
            redirect_count += 1
            import urllib.parse as _urlparse

            resolved_redirect_url = _urlparse.urljoin(str(resp.url), redirect_url)
            redirect_parsed = _urlparse.urlparse(resolved_redirect_url)
            redirect_headers = gen_headers(redirect_parsed)
            safe_redirect_headers = {
                k: ("***" if k.lower() == "authorization" else v)
                for k, v in redirect_headers.items()
            }
            log.info(
                f"[proxy:{request_id}] redirect target resolved={resolved_redirect_url[:500]} netloc={redirect_parsed.netloc} headers={safe_redirect_headers}"
            )
            # bilibili CDN 防盗链；LX06 固件不兼容 MP4/AAC，切换 FFmpeg 转码
            # 精确匹配域名后缀，电台流不走 FFmpeg
            if not is_radio and _is_bili_cdn(redirect_parsed.netloc):
                log.info(
                    f"[proxy:{request_id}] redirect to bili cdn detected -> ffmpeg redirect_url={resolved_redirect_url[:500]}"
                )
                await close_session()
                return await _ffmpeg_mp3_stream(
                    resolved_redirect_url,
                    extra_headers={
                        "referer": "https://www.bilibili.com",
                        "origin": "https://www.bilibili.com",
                    },
                )
            resp = await session.get(
                resolved_redirect_url, headers=redirect_headers, allow_redirects=False
            )

        log.info(
            f"[proxy:{request_id}] final response status={resp.status} resp_url={str(resp.url)[:500]} content_type={resp.headers.get('Content-Type', '')} content_length={resp.headers.get('Content-Length', '')}"
        )
        if resp.status not in (200, 206):
            await close_session()
            status_exc = ValueError(f"服务器返回状态码: {resp.status}")
            raise HTTPException(
                status_code=resp.status, detail=f"下载失败，状态码: {resp.status}"
            ) from status_exc

        # 后续逻辑以实际最终响应 URL 为准，避免相对跳转后仍沿用初始 URL
        import urllib.parse

        parsed_url = urllib.parse.urlparse(str(resp.url))
        url = str(resp.url)

        # 提取文件名，根据URL扩展名智能判断
        filename = parsed_url.path.split("/")[-1].split("?")[0]
        content_type = resp.headers.get("Content-Type", "").lower()

        # Content-Type 兜底：非 bilibili CDN 的 MP4/AAC 响应同样需要 FFmpeg 转码
        # （LX06 固件不支持 MP4/AAC 容器，需转为 MP3；电台流不转码）
        if not is_radio and not _is_bili_cdn(parsed_url.netloc):
            if any(
                ct in content_type for ct in ("video/mp4", "audio/mp4", "audio/aac")
            ):
                final_url = str(resp.url)
                await close_session()
                log.info(
                    f"[proxy:{request_id}] content-type fallback -> ffmpeg content_type={content_type} final_url={final_url[:500]}"
                )
                return await _ffmpeg_mp3_stream(final_url)

        # 判断是否为 m3u8 文件
        is_m3u8 = (
            url.lower().endswith(".m3u8")
            or "mpegurl" in content_type
            or "m3u8" in content_type
        )
        log.info(
            f"[proxy:{request_id}] filename={filename!r} is_m3u8={is_m3u8} parsed_netloc={parsed_url.netloc}"
        )

        if not filename:
            # 根据URL扩展名或Content-Type设置默认文件名
            path_lower = parsed_url.path.lower()
            if path_lower.endswith(".m3u8") or is_m3u8:
                filename = "stream.m3u8"
            elif path_lower.endswith(".m3u"):
                filename = "stream.m3u"
            else:
                filename = "output.mp3"

        # 如果是 m3u8 文件，需要处理内容，将相对路径替换为代理 URL
        if is_m3u8:
            try:
                # 读取完整的 m3u8 内容
                m3u8_content = await resp.text()
                await close_session()
                log.info(
                    f"[proxy:{request_id}] processing m3u8 len={len(m3u8_content)} base_url={url[:500]}"
                )

                # 处理 m3u8 内容，替换资源 URL
                processed_content = _process_m3u8_content(m3u8_content, url, is_radio)
                log.info(
                    f"[proxy:{request_id}] m3u8 processed len={len(processed_content)} filename={filename}"
                )

                # 返回处理后的内容
                return Response(
                    content=processed_content,
                    media_type="application/vnd.apple.mpegurl",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'},
                )
            except Exception as e:
                log.exception(f"[proxy:{request_id}] 处理 m3u8 文件失败: {e}")
                # 失败时返回原始内容
                await close_session()
                raise

        # 非 m3u8 文件，使用流式传输
        async def stream_generator():
            total_bytes = 0
            try:
                async for data in resp.content.iter_chunked(4096):
                    total_bytes += len(data)
                    yield data
            except Exception as e:
                log.exception(
                    f"[proxy:{request_id}] stream_generator error after {total_bytes} bytes: {e}"
                )
                raise
            finally:
                log.info(
                    f"[proxy:{request_id}] stream finished total_bytes={total_bytes} resp_url={str(resp.url)[:500]}"
                )
                await close_session()

        return StreamingResponse(
            stream_generator(),
            media_type=resp.headers.get("Content-Type", "audio/mpeg"),
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
            background=BackgroundTask(close_session),
        )

    except aiohttp.ClientConnectionError as e:
        log.exception(f"[proxy:{request_id}] ClientConnectionError: {e}")
        await close_session()
        raise HTTPException(status_code=502, detail=f"连接错误: {str(e)}") from e
    except asyncio.TimeoutError as e:
        log.exception(f"[proxy:{request_id}] TimeoutError: {e}")
        await close_session()
        raise HTTPException(status_code=504, detail="下载超时") from e
    except Exception as e:
        log.exception(f"[proxy:{request_id}] unhandled proxy error: {e}")
        await close_session()
        raise HTTPException(status_code=500, detail=f"发生错误: {str(e)}") from e


@router.get("/proxy/{type}", summary="类型化代理接口")
async def proxy_with_type(type: str, urlb64: str = "", token: str = ""):
    """支持路径参数的代理接口

    Args:
        type: 类型，music 或 radio
        urlb64: Base64编码的URL
    """
    if type not in ("music", "radio"):
        raise HTTPException(status_code=400, detail="type 参数必须是 music 或 radio")

    is_radio = type == "radio"

    # token 短链模式
    if token:
        cached = get_proxy_token(token)
        if cached is None:
            raise HTTPException(status_code=404, detail="token 已过期或不存在")
        real_url, is_radio = cached
        # 不删除 token，允许音箱和 ffprobe 多次请求同一首歌
        import base64 as _b64

        urlb64 = _b64.b64encode(real_url.encode("utf-8")).decode("utf-8")

    return await _proxy_handler(urlb64, is_radio=is_radio)


@router.get("/proxy", summary="基于正常下载逻辑的代理接口")
async def proxy(urlb64: str):
    """代理接口（向后兼容）

    Args:
        urlb64: Base64编码的URL
    """
    return await _proxy_handler(urlb64, is_radio=False)
