#!/usr/bin/env python3
import asyncio
import functools
import http.server
import io
import json
import logging
import os
import random
import re
import shutil
import socket
import socketserver
import tempfile
import threading
import time
import urllib.parse
import traceback
import mutagen.mp3

from pathlib import Path

from aiohttp import ClientSession, ClientTimeout
from miservice import MiAccount, MiIOService, MiNAService, miio_command
from rich import print
from rich.logging import RichHandler

from xiaomusic.config import (
    COOKIE_TEMPLATE,
    LATEST_ASK_API,
    KEY_WORD_DICT,
    Config,
)
from xiaomusic.utils import (
    calculate_tts_elapse,
    parse_cookie_string,
)

EOF = object()

PLAY_TYPE_ONE = 0 # 单曲循环
PLAY_TYPE_ALL = 1 # 全部循环

class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass


class HTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    logger = logging.getLogger("xiaomusic")

    def log_message(self, format, *args):
        self.logger.debug(f"{self.address_string()} - {format}", *args)

    def log_error(self, format, *args):
        self.logger.error(f"{self.address_string()} - {format}", *args)

    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (socket.error, ConnectionResetError, BrokenPipeError):
            # ignore this or TODO find out why the error later
            pass

class XiaoMusic:
    def __init__(self, config: Config):
        self.config = config

        self.mi_token_home = Path.home() / ".mi.token"
        self.last_timestamp = int(time.time() * 1000)  # timestamp last call mi speaker
        self.last_record = None
        self.cookie_jar = None
        self.device_id = ""
        self.mina_service = None
        self.miio_service = None
        self.polling_event = asyncio.Event()
        self.new_record_event = asyncio.Event()

        self.music_path = config.music_path
        self.hostname = config.hostname
        self.port = config.port
        self.proxy = config.proxy

        # 下载对象
        self.download_proc = None
        # 单曲循环，全部循环
        self.play_type = PLAY_TYPE_ONE
        self.cur_music = ""
        self._next_timer = None
        self._timeout = 0

        # setup logger
        self.log = logging.getLogger("xiaomusic")
        self.log.setLevel(logging.DEBUG if config.verbose else logging.INFO)
        self.log.addHandler(RichHandler())
        self.log.debug(config)

    async def poll_latest_ask(self):
        async with ClientSession() as session:
            session._cookie_jar = self.cookie_jar
            while True:
                self.log.debug(
                    "Listening new message, timestamp: %s", self.last_timestamp
                )
                await self.get_latest_ask_from_xiaoai(session)
                start = time.perf_counter()
                self.log.debug("Polling_event, timestamp: %s", self.last_timestamp)
                await self.polling_event.wait()
                if (d := time.perf_counter() - start) < 1:
                    # sleep to avoid too many request
                    self.log.debug("Sleep %f, timestamp: %s", d, self.last_timestamp)
                    await asyncio.sleep(1 - d)

    async def init_all_data(self, session):
        await self.login_miboy(session)
        await self._init_data_hardware()
        session.cookie_jar.update_cookies(self.get_cookie())
        self.cookie_jar = session.cookie_jar
        self.start_http_server()

    async def login_miboy(self, session):
        account = MiAccount(
            session,
            self.config.account,
            self.config.password,
            str(self.mi_token_home),
        )
        # Forced login to refresh to refresh token
        await account.login("micoapi")
        self.mina_service = MiNAService(account)
        self.miio_service = MiIOService(account)

    async def _init_data_hardware(self):
        if self.config.cookie:
            # if use cookie do not need init
            return
        hardware_data = await self.mina_service.device_list()
        # fix multi xiaoai problems we check did first
        # why we use this way to fix?
        # some videos and articles already in the Internet
        # we do not want to change old way, so we check if miotDID in `env` first
        # to set device id

        for h in hardware_data:
            if did := self.config.mi_did:
                if h.get("miotDID", "") == str(did):
                    self.device_id = h.get("deviceID")
                    break
                else:
                    continue
            if h.get("hardware", "") == self.config.hardware:
                self.device_id = h.get("deviceID")
                break
        else:
            raise Exception(
                f"we have no hardware: {self.config.hardware} please use `micli mina` to check"
            )
        if not self.config.mi_did:
            devices = await self.miio_service.device_list()
            try:
                self.config.mi_did = next(
                    d["did"]
                    for d in devices
                    if d["model"].endswith(self.config.hardware.lower())
                )
            except StopIteration:
                raise Exception(
                    f"cannot find did for hardware: {self.config.hardware} "
                    "please set it via MI_DID env"
                )

    def get_cookie(self):
        if self.config.cookie:
            cookie_jar = parse_cookie_string(self.config.cookie)
            # set attr from cookie fix #134
            cookie_dict = cookie_jar.get_dict()
            self.device_id = cookie_dict["deviceId"]
            return cookie_jar
        else:
            with open(self.mi_token_home) as f:
                user_data = json.loads(f.read())
            user_id = user_data.get("userId")
            service_token = user_data.get("micoapi")[1]
            cookie_string = COOKIE_TEMPLATE.format(
                device_id=self.device_id, service_token=service_token, user_id=user_id
            )
            return parse_cookie_string(cookie_string)

    async def get_latest_ask_from_xiaoai(self, session):
        retries = 3
        for i in range(retries):
            try:
                timeout = ClientTimeout(total=15)
                r = await session.get(
                    LATEST_ASK_API.format(
                        hardware=self.config.hardware,
                        timestamp=str(int(time.time() * 1000)),
                    ),
                    timeout=timeout,
                )
            except Exception as e:
                self.log.warning(
                    "Execption when get latest ask from xiaoai: %s", str(e)
                )
                continue
            try:
                data = await r.json()
            except Exception:
                self.log.warning("get latest ask from xiaoai error, retry")
                if i == 2:
                    # tricky way to fix #282 #272 # if it is the third time we re init all data
                    self.log.info("Maybe outof date trying to re init it")
                    await self.init_all_data(self.session)
            else:
                return self._get_last_query(data)

    def _get_last_query(self, data):
        if d := data.get("data"):
            records = json.loads(d).get("records")
            if not records:
                return
            last_record = records[0]
            timestamp = last_record.get("time")
            if timestamp > self.last_timestamp:
                self.last_timestamp = timestamp
                self.last_record = last_record
                self.new_record_event.set()

    async def do_tts(self, value, wait_for_finish=False):
        self.log.info("do_tts: %s", value)
        if not self.config.use_command:
            try:
                await self.mina_service.text_to_speech(self.device_id, value)
            except Exception:
                pass
        else:
            await miio_command(
                self.miio_service,
                self.config.mi_did,
                f"{self.config.tts_command} {value}",
            )
        if wait_for_finish:
            elapse = calculate_tts_elapse(value)
            await asyncio.sleep(elapse)
            await self.wait_for_tts_finish()

    async def wait_for_tts_finish(self):
        while True:
            if not await self.get_if_xiaoai_is_playing():
                break
            await asyncio.sleep(1)

    def start_http_server(self):
        # create the server
        handler = functools.partial(HTTPRequestHandler, directory=self.music_path)
        httpd = ThreadedHTTPServer(("", self.port), handler)
        # start the server in a new thread
        server_thread = threading.Thread(target=httpd.serve_forever)
        server_thread.daemon = True
        server_thread.start()

        self.log.info(f"Serving on {self.hostname}:{self.port}")

    async def get_if_xiaoai_is_playing(self):
        playing_info = await self.mina_service.player_get_status(self.device_id)
        # WTF xiaomi api
        is_playing = (
            json.loads(playing_info.get("data", {}).get("info", "{}")).get("status", -1)
            == 1
        )
        return is_playing

    async def stop_if_xiaoai_is_playing(self):
        is_playing = await self.get_if_xiaoai_is_playing()
        if is_playing:
            # stop it
            await self.mina_service.player_pause(self.device_id)

    async def wakeup_xiaoai(self):
        return await miio_command(
            self.miio_service,
            self.config.mi_did,
            f"{self.config.wakeup_command} {WAKEUP_KEYWORD} 0",
        )

    # 是否在下载中
    def is_downloading(self):
        if not self.download_proc:
            return False
        if self.download_proc.returncode != None \
            and self.download_proc.returncode < 0:
            return False
        return True

    # 下载歌曲
    async def download(self, name):
        if self.download_proc:
            try:
                self.download_proc.kill()
            except ProcessLookupError:
                pass

        sbp_args = (
            "yt-dlp", f"ytsearch:{name}",
            "-x", "--audio-format", "mp3",
            "--paths", self.music_path,
            "-o", f"{name}.mp3",
            "--ffmpeg-location", "./ffmpeg/bin")

        if self.proxy:
            sbp_args += ("--proxy", f"{self.proxy}")

        self.download_proc = await asyncio.create_subprocess_exec(*sbp_args)
        await self.do_tts(f"正在下载歌曲{name}")

    def get_filename(self, name):
        filename = os.path.join(self.music_path, f"{name}.mp3")
        return filename

    # 本地是否存在歌曲
    def local_exist(self, name):
        filename = self.get_filename(name)
        self.log.debug("local_exist. filename:%s", filename)
        return os.path.exists(filename)

    # 获取歌曲播放地址
    def get_file_url(self, name):
        encoded_name = urllib.parse.quote(os.path.basename(name))
        return f"http://{self.hostname}:{self.port}/{encoded_name}.mp3"

    # 随机获取一首音乐
    def random_music(self):
        files = os.listdir(self.music_path)
        # 过滤 mp3 文件
        mp3_files = [file for file in files if file.endswith(".mp3")]
        if len(mp3_files) == 0:
            self.log.warning(f"没有随机到歌曲")
            return ""
        # 随机选择一个文件
        mp3_file = random.choice(mp3_files)
        name = mp3_file[:-4]
        self.log.info(f"随机到歌曲{name}")
        return name

    # 获取mp3文件播放时长
    def get_mp3_duration(self, name):
        filename = self.get_filename(name)
        audio = mutagen.mp3.MP3(filename)
        return audio.info.length

    # 设置下一首歌曲的播放定时器
    def set_next_music_timeout(self):
        sec = int(self.get_mp3_duration(self.cur_music))
        self.log.info(f"歌曲{self.cur_music}的时长{sec}秒")
        if self._next_timer:
            self._next_timer.cancel()
            self.log.info(f"定时器已取消")
        self._timeout = sec

        async def _do_next():
            await asyncio.sleep(self._timeout)
            try:
                await self.play_next()
            except Exception as e:
                self.log.warning(f"执行出错 {str(e)}\n{traceback.format_exc()}")

        self._next_timer = asyncio.ensure_future(_do_next())
        self.log.info(f"{sec}秒后将会播放下一首")

    async def run_forever(self):
        async with ClientSession() as session:
            self.session = session
            await self.init_all_data(session)
            task = asyncio.create_task(self.poll_latest_ask())
            assert task is not None  # to keep the reference to task, do not remove this
            self.log.info(f"Running xiaomusic now, 用`{'/'.join(KEY_WORD_DICT.keys())}`开头来控制")
            while True:
                self.polling_event.set()
                await self.new_record_event.wait()
                self.new_record_event.clear()
                new_record = self.last_record
                self.polling_event.clear()  # stop polling when processing the question
                query = new_record.get("query", "").strip()
                self.log.debug("收到消息:%s", query)

                # 匹配命令
                match = re.match(rf"^({'|'.join(KEY_WORD_DICT.keys())})", query)
                if not match:
                    await asyncio.sleep(1)
                    continue

                if self.config.mute_xiaoai:
                    await self.stop_if_xiaoai_is_playing()
                else:
                    # waiting for xiaoai speaker done
                    await asyncio.sleep(8)

                opkey = match.groups()[0]
                opvalue = KEY_WORD_DICT[opkey]
                oparg = query[len(opkey):]
                self.log.info("收到指令:%s %s", opkey, oparg)

                try:
                    func = getattr(self, opvalue)
                    await func(name = oparg)
                except Exception as e:
                    self.log.warning(f"执行出错 {str(e)}\n{traceback.format_exc()}")

    # 播放歌曲
    async def play(self, **kwargs):
        name = kwargs["name"]
        if name == "":
            await self.play_next()
            return

        await self.do_tts(f"即将播放{name}")
        if not self.local_exist(name):
            await self.download(name)
            self.log.info("正在下载中 %s", name)
            await self.download_proc.wait()

        self.cur_music = name
        url = self.get_file_url(name)
        self.log.info("播放 %s", url)
        await self.stop_if_xiaoai_is_playing()
        await self.mina_service.play_by_url(self.device_id, url)
        self.log.info("已经开始播放了")
        # 设置下一首歌曲的播放定时器
        self.set_next_music_timeout()

    # 下一首
    async def play_next(self, **kwargs):
        self.log.info("下一首")
        name = self.cur_music
        if self.play_type == PLAY_TYPE_ALL or name == "":
            name = self.random_music()
        if name == "":
            await self.do_tts(f"本地没有歌曲")
            return
        await self.play(name=name)

    # 单曲循环
    async def set_play_type_one(self, **kwargs):
        self.play_type = PLAY_TYPE_ONE
        await self.do_tts(f"已经设置为单曲循环")

    # 全部循环
    async def set_play_type_all(self, **kwargs):
        self.play_type = PLAY_TYPE_ALL
        await self.do_tts(f"已经设置为全部循环")

    async def stop(self, **kwargs):
        if self._next_timer:
            self._next_timer.cancel()
            self.log.info(f"定时器已取消")
        await self.stop_if_xiaoai_is_playing()
