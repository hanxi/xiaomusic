import asyncio
from datetime import datetime

from ga4mp import GtagMP

from xiaomusic import __version__


class Analytics:
    def __init__(self, log):
        self.gtag = None
        self.current_date = None
        self.log = log
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

    async def run_with_timeout(self, func, *args, **kwargs):
        try:
            return await asyncio.wait_for(func(*args, **kwargs), 3)
        except asyncio.TimeoutError as e:
            self.log.warning(f"analytics run_with_timeout failed {e}")
            return None

    async def send_startup_event(self):
        try:
            await self.run_with_timeout(self._send_startup_event)
        except Exception as e:
            self.log.warning(f"analytics send_startup_event failed {e}")
            self.init()

    async def _send_startup_event(self):
        event = self.gtag.create_new_event(name="startup")
        event.set_event_param(name="version", value=__version__)
        event_list = [event]
        self.gtag.send(events=event_list)

    async def send_daily_event(self):
        try:
            await self.run_with_timeout(self._send_daily_event)
        except Exception as e:
            self.log.warning(f"analytics send_daily_event failed {e}")
            self.init()

    async def _send_daily_event(self):
        current_date = datetime.now().strftime("%Y-%m-%d")
        if self.current_date == current_date:
            return

        event = self.gtag.create_new_event(name="daily_active_user")
        event.set_event_param(name="version", value=__version__)
        event.set_event_param(name="date", value=current_date)
        event_list = [event]
        self.gtag.send(events=event_list)
        self.current_date = current_date

    async def send_play_event(self, name, sec):
        try:
            await self.run_with_timeout(self._send_play_event, name, sec)
        except Exception as e:
            self.log.warning(f"analytics send_play_event failed {e}")
            self.init()

    async def _send_play_event(self, name, sec):
        event = self.gtag.create_new_event(name="play")
        event.set_event_param(name="version", value=__version__)
        event.set_event_param(name="music", value=name)
        event.set_event_param(name="sec", value=sec)
        event_list = [event]
        self.gtag.send(events=event_list)
