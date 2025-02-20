async def setmyvolume(arg1):
    global log, xiaomusic
    log.info(f"code1:{arg1}")
    did = xiaomusic._cur_did
    await xiaomusic.set_myvolume(did, arg1)
