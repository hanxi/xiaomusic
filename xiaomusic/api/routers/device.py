"""设备控制路由"""

import asyncio
import urllib.parse

from fastapi import (
    APIRouter,
    Depends,
)

from xiaomusic.api.dependencies import (
    log,
    verification,
    xiaomusic,
)
from xiaomusic.api.models import (
    Did,
    DidCmd,
    DidVolume,
)

router = APIRouter(dependencies=[Depends(verification)])


@router.get("/getvolume")
async def getvolume(did: str = ""):
    """获取音量"""
    if not xiaomusic.did_exist(did):
        return {"volume": 0}

    volume = await xiaomusic.get_volume(did=did)
    return {"volume": volume}


@router.post("/setvolume")
async def setvolume(data: DidVolume):
    """设置音量"""
    did = data.did
    volume = data.volume
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    log.info(f"set_volume {did} {volume}")
    await xiaomusic.set_volume(did=did, arg1=volume)
    return {"ret": "OK", "volume": volume}


@router.post("/cmd")
async def do_cmd(data: DidCmd):
    """执行命令"""
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


@router.get("/cmdstatus")
async def cmd_status():
    """命令状态"""
    finish = await xiaomusic.is_task_finish()
    if finish:
        return {"ret": "OK", "status": "finish"}
    return {"ret": "OK", "status": "running"}


@router.get("/playurl")
async def playurl(did: str, url: str):
    """播放 URL"""
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}
    decoded_url = urllib.parse.unquote(url)
    log.info(f"playurl did: {did} url: {decoded_url}")
    return await xiaomusic.play_url(did=did, arg1=decoded_url)


@router.get("/playtts")
async def playtts(did: str, text: str):
    """播放 TTS"""
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    log.info(f"tts {did} {text}")
    await xiaomusic.do_tts(did=did, value=text)
    return {"ret": "OK"}


@router.post("/device/stop")
async def stop(data: Did):
    """关机"""
    did = data.did
    log.info(f"stop did:{did}")
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    try:
        await xiaomusic.stop(did, "notts")
    except Exception as e:
        log.warning(f"Execption {e}")
    return {"ret": "OK"}
