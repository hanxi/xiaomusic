import asyncio
import copy
import platform
import traceback
from datetime import datetime

import aiohttp
from ga4mp import GtagMP

from xiaomusic import __version__


class Analytics:
    def __init__(self, log, config):
        self.gtag = None
        self.current_date = None
        self.log = log
        self.config = config
        self.init()

    def init(self):
        if self.gtag is not None:
            return

        gtag = GtagMP(
            api_secret="sVRsf3T9StuWc-ZiWZxDVA",
            measurement_id="G-Z09NC1K7ZW",
            client_id="",
        )
        gtag.client_id = gtag.random_client_id()
        gtag.store.set_user_property(name="version", value=__version__)
        self.gtag = gtag
        self.log.info("analytics init ok")

    async def send_startup_event(self):
        event = self.gtag.create_new_event(name="startup")
        event.set_event_param(name="version", value=__version__)
        await self._send(event)

    async def send_daily_event(self):
        current_date = datetime.now().strftime("%Y-%m-%d")
        if self.current_date == current_date:
            return

        event = self.gtag.create_new_event(name="daily_active_user")
        event.set_event_param(name="version", value=__version__)
        event.set_event_param(name="date", value=current_date)
        await self._send(event)
        self.current_date = current_date

    async def send_play_event(self, name, sec, hardware):
        event = self.gtag.create_new_event(name="play")
        event.set_event_param(name="version", value=__version__)
        event.set_event_param(name="music", value=name)
        event.set_event_param(name="sec", value=sec)
        event.set_event_param(name="hardware", value=hardware)
        await self._send(event)

    async def _send(self, event):
        await self.post_to_umami(event)
        events = [event]
        await self.run_with_cancel(self._google_send, events)

    async def _google_send(self, events):
        try:
            self.gtag.send(events)
        except Exception as e:
            self.log.warning(f"google analytics run_with_cancel failed {e}")

    async def run_with_cancel(self, func, *args, **kwargs):
        try:
            asyncio.ensure_future(asyncio.to_thread(func, *args, **kwargs))
            self.log.info("analytics run_with_cancel success")
        except Exception as e:
            self.log.warning(f"analytics run_with_cancel failed {e}")
            return None

    async def post_to_umami(self, event):
        try:
            url = "https://umami.hanxi.cc/api/send"
            user_agent = self._get_user_agent()
            params = copy.copy(event.get_event_params())
            params["useragent"] = user_agent
            data = {
                "payload": {
                    "hostname": self.config.hostname,
                    "language": "zh-CN",
                    "referrer": "",
                    "screen": "430x932",
                    "title": "后端统计",
                    "url": "/backend",
                    "website": "7bfb0890-4115-4260-8892-b391513e7e99",
                    "name": event.get_event_name(),
                    "data": params,
                },
                "type": "event",
            }

            async with aiohttp.ClientSession() as session:
                headers = {
                    "User-Agent": user_agent,
                }
                # self.log.info(f"headers {headers}, {data}")
                async with session.post(url, json=data, headers=headers) as response:
                    self.log.info(f"umami Status: {response.status}")
                    await response.text()
        except Exception as e:
            self.log.exception(f"Execption {e}")

    def _get_user_agent(self):
        try:
            # 获取系统信息
            os_name = platform.system()  # 操作系统名称，如 'Windows', 'Linux', 'Darwin'
            os_version = platform.version()  # 操作系统版本号
            architecture = "unknow"
            try:
                architecture = platform.architecture()[0]  # '32bit' or '64bit'
            except Exception as e:
                architecture = f"Error {e}"
                pass
            machine = platform.machine()  # 机器类型，如 'x86_64', 'arm64'

            # 获取 Python 版本信息
            python_version = platform.python_version()  # Python 版本

            # 组合 User-Agent 字符串
            user_agent = (
                f"XiaoMusic/{__version__} "
                f"({os_name} {os_version}; {architecture}; {machine}) "
                f"Python/{python_version}"
            )
        except Exception as e:
            # 获取报错的堆栈信息
            error_info = traceback.format_exc()
            user_agent = f"Error: {e} {error_info}"

        return user_agent
