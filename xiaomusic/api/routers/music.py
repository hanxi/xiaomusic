"""音乐管理路由"""

import json
import urllib.parse

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)

from xiaomusic.api.dependencies import (
    log,
    verification,
    xiaomusic,
)
from xiaomusic.api.models import (
    DidPlayMusic,
    MusicInfoObj,
    MusicItem,
)

router = APIRouter()


@router.get("/searchmusic")
def searchmusic(name: str = "", Verifcation=Depends(verification)):
    """搜索音乐"""
    return xiaomusic.searchmusic(name)


@router.get("/api/search/online")
async def search_online_music(
    keyword: str = Query(..., description="搜索关键词"),
    plugin: str = Query("all", description="指定插件名称，all表示搜索所有插件"),
    page: int = Query(1, description="页码"),
    limit: int = Query(20, description="每页数量"),
    Verifcation=Depends(verification),
):
    """在线音乐搜索API"""
    try:
        if not keyword:
            return {"success": False, "error": "Keyword required"}

        return await xiaomusic.get_music_list_online(
            keyword=keyword, plugin=plugin, page=page, limit=limit
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/proxy/real-music-url")
async def get_real_music_url(
    url: str = Query(..., description="音乐下载URL"), Verifcation=Depends(verification)
):
    """通过服务端代理获取真实的音乐播放URL，避免CORS问题"""
    try:
        # 获取真实的音乐播放URL
        return await xiaomusic.get_real_url_of_openapi(url)

    except Exception as e:
        log.error(f"获取真实音乐URL失败: {e}")
        # 如果代理获取失败，仍然返回原始URL
        return {"success": False, "realUrl": url, "error": str(e)}


@router.post("/api/play/getMediaSource")
async def get_media_source(request: Request, Verifcation=Depends(verification)):
    """获取音乐真实播放URL"""
    try:
        # 获取请求数据
        data = await request.json()
        # 调用公共函数处理
        return await xiaomusic.get_media_source_url(data)
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/play/getLyric")
async def get_media_lyric(request: Request, Verifcation=Depends(verification)):
    """获取音乐歌词"""
    try:
        # 获取请求数据
        data = await request.json()
        # 调用公共函数处理
        return await xiaomusic.get_media_lyric(data)
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/play/online")
async def play_online_music(request: Request, Verifcation=Depends(verification)):
    """设备端在线播放插件音乐"""
    try:
        # 获取请求数据
        data = await request.json()
        did = data.get("did")
        openapi_info = xiaomusic.js_plugin_manager.get_openapi_info()
        if openapi_info.get("enabled", False):
            media_source = await xiaomusic.get_real_url_of_openapi(data.get("url"))
        else:
            # 调用公共函数处理,获取音乐真实播放URL
            media_source = await xiaomusic.get_media_source_url(data)
        if not media_source or not media_source.get("url"):
            return {"success": False, "error": "Failed to get media source URL"}
        url = media_source.get("url")
        decoded_url = urllib.parse.unquote(url)
        return await xiaomusic.play_url(did=did, arg1=decoded_url)
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/playingmusic")
def playingmusic(did: str = "", Verifcation=Depends(verification)):
    """当前播放音乐"""
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


@router.get("/musiclist")
async def musiclist(Verifcation=Depends(verification)):
    """音乐列表"""
    return xiaomusic.get_music_list()


@router.get("/musicinfo")
async def musicinfo(
    name: str, musictag: bool = False, Verifcation=Depends(verification)
):
    """音乐信息"""
    url, _ = await xiaomusic.get_music_url(name)
    info = {
        "ret": "OK",
        "name": name,
        "url": url,
    }
    if musictag:
        info["tags"] = xiaomusic.get_music_tags(name)
    return info


@router.get("/musicinfos")
async def musicinfos(
    name: list[str] = Query(None),
    musictag: bool = False,
    Verifcation=Depends(verification),
):
    """批量音乐信息"""
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


@router.post("/setmusictag")
async def setmusictag(info: MusicInfoObj, Verifcation=Depends(verification)):
    """设置音乐标签"""
    ret = xiaomusic.set_music_tag(info.musicname, info)
    return {"ret": ret}


@router.post("/delmusic")
async def delmusic(data: MusicItem, Verifcation=Depends(verification)):
    """删除音乐"""
    log.info(data)
    await xiaomusic.del_music(data.name)
    return "success"


@router.post("/playmusic")
async def playmusic(data: DidPlayMusic, Verifcation=Depends(verification)):
    """播放音乐"""
    did = data.did
    musicname = data.musicname
    searchkey = data.searchkey
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    log.info(f"playmusic {did} musicname:{musicname} searchkey:{searchkey}")
    await xiaomusic.do_play(did, musicname, searchkey)
    return {"ret": "OK"}


@router.post("/refreshmusictag")
async def refreshmusictag(Verifcation=Depends(verification)):
    """刷新音乐标签"""
    xiaomusic.refresh_music_tag()
    return {
        "ret": "OK",
    }


@router.post("/debug_play_by_music_url")
async def debug_play_by_music_url(request: Request, Verifcation=Depends(verification)):
    """调试播放音乐URL"""
    try:
        data = await request.body()
        data_dict = json.loads(data.decode("utf-8"))
        log.info(f"data:{data_dict}")
        return await xiaomusic.debug_play_by_music_url(arg1=data_dict)
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON") from err
