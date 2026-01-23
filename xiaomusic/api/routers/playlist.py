"""播放列表路由"""

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
    DidPlayMusicList,
    PlayListMusicObj,
    PlayListObj,
    PlayListUpdateObj,
)

router = APIRouter(dependencies=[Depends(verification)])


@router.get("/curplaylist")
async def curplaylist(did: str = ""):
    """当前播放列表"""
    if not xiaomusic.did_exist(did):
        return ""
    return xiaomusic.get_cur_play_list(did)


@router.post("/playmusiclist")
async def playmusiclist(data: DidPlayMusicList):
    """播放音乐列表"""
    did = data.did
    listname = data.listname
    musicname = data.musicname
    if not xiaomusic.did_exist(did):
        return {"ret": "Did not exist"}

    log.info(f"playmusiclist {did} listname:{listname} musicname:{musicname}")
    await xiaomusic.do_play_music_list(did, listname, musicname)
    return {"ret": "OK"}


@router.post("/playlistadd")
async def playlistadd(data: PlayListObj):
    """新增歌单"""
    ret = xiaomusic.music_library.play_list_add(data.name)
    if ret:
        return {"ret": "OK"}
    return {"ret": "Add failed, may be already exist."}


@router.post("/playlistdel")
async def playlistdel(data: PlayListObj):
    """移除歌单"""
    ret = xiaomusic.music_library.play_list_del(data.name)
    if ret:
        return {"ret": "OK"}
    return {"ret": "Del failed, may be not exist."}


@router.post("/playlistupdatename")
async def playlistupdatename(data: PlayListUpdateObj):
    """修改歌单名字"""
    ret = xiaomusic.music_library.play_list_update_name(data.oldname, data.newname)
    if ret:
        return {"ret": "OK"}
    return {"ret": "Update failed, may be not exist."}


@router.get("/playlistnames")
async def getplaylistnames():
    """获取所有自定义歌单"""
    names = xiaomusic.music_library.get_play_list_names()
    log.info(f"names {names}")
    return {
        "ret": "OK",
        "names": names,
    }


@router.post("/playlistaddmusic")
async def playlistaddmusic(data: PlayListMusicObj):
    """歌单新增歌曲"""
    ret = xiaomusic.music_library.play_list_add_music(data.name, data.music_list)
    if ret:
        return {"ret": "OK"}
    return {"ret": "Add failed, may be playlist not exist."}


@router.post("/playlistdelmusic")
async def playlistdelmusic(data: PlayListMusicObj):
    """歌单移除歌曲"""
    ret = xiaomusic.music_library.play_list_del_music(data.name, data.music_list)
    if ret:
        return {"ret": "OK"}
    return {"ret": "Del failed, may be playlist not exist."}


@router.post("/playlistupdatemusic")
async def playlistupdatemusic(data: PlayListMusicObj):
    """歌单更新歌曲"""
    ret = xiaomusic.music_library.play_list_update_music(data.name, data.music_list)
    if ret:
        return {"ret": "OK"}
    return {"ret": "Del failed, may be playlist not exist."}


@router.get("/playlistmusics")
async def getplaylist(name: str):
    """获取歌单中所有歌曲"""
    ret, musics = xiaomusic.music_library.play_list_musics(name)
    return {
        "ret": "OK",
        "musics": musics,
    }
