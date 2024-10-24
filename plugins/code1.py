async def code1(arg1):
    global log, xiaomusic
    log.info(f"code1:{arg1}")
    did = xiaomusic._cur_did
    await xiaomusic.do_tts(did, "你好，我是自定义的测试口令")

    last_record = xiaomusic.last_record
    query = last_record.get("query", "").strip()
    await xiaomusic.do_tts(did, f"你说的是: {query}")
