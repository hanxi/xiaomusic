async def code1(arg1):
    global log, xiaomusic
    log.info(f"code1:{arg1}")
    await xiaomusic.do_tts("你好，我是自定义的测试口令")
