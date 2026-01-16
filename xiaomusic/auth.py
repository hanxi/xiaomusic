"""认证管理模块

本模块负责小米账号认证与会话管理，包括：
- 小米账号登录
- Cookie管理
- 会话维护
- 设备ID更新
"""

import json
import os

from aiohttp import ClientSession
from miservice import MiAccount, MiIOService, MiNAService

from xiaomusic.config import Device
from xiaomusic.const import COOKIE_TEMPLATE
from xiaomusic.utils.system_utils import (
    get_random,
    parse_cookie_string,
    parse_cookie_string_to_dict,
)


class AuthManager:
    """认证管理器

    负责处理小米账号的登录、认证和会话管理。
    """

    def __init__(self, config, log, device_manager):
        """初始化认证管理器

        Args:
            config: 配置对象
            log: 日志对象
        """
        self.config = config
        self.log = log
        self.mi_token_home = os.path.join(self.config.conf_path, ".mi.token")

        # 认证状态
        self.mina_service = None
        self.miio_service = None
        self.login_acount = None
        self.login_password = None
        self.cookie_jar = None

        # 当前设备DID（用于设备ID更新）
        self._cur_did = None
        self.device_id = get_random(16).upper()
        self.mi_session = ClientSession()
        self.device_manager = device_manager

    async def init_all_data(self):
        """初始化所有数据

        检查登录状态，如需要则登录，然后更新设备ID和Cookie。

        """
        self.mi_token_home = os.path.join(self.config.conf_path, ".mi.token")
        is_need_login = await self.need_login()
        is_can_login = await self.can_login()
        if is_need_login and is_can_login:
            self.log.info("try login")
            await self.login_miboy()
        else:
            self.log.info(
                f"Maybe already logined is_need_login:{is_need_login} is_can_login:{is_can_login}"
            )
        await self.device_manager.update_device_info(self)
        cookie_jar = self.get_cookie()
        if cookie_jar:
            self.mi_session.cookie_jar.update_cookies(cookie_jar)
        self.cookie_jar = self.mi_session.cookie_jar

    async def can_login(self):
        if self.config.account and self.config.password:
            return True
        if self.get_cookie():
            return True
        self.log.warning("没有账号密码 或 cookies 无法登陆")
        return False

    async def need_login(self):
        """检查是否需要登录

        Returns:
            bool: True表示需要登录，False表示已登录
        """
        if self.mina_service is None:
            return True
        if self.login_acount != self.config.account:
            return True
        if self.login_password != self.config.password:
            return True

        try:
            await self.mina_service.device_list()
        except Exception as e:
            self.log.warning(f"可能登录失败. {e}")
            return True
        return False

    async def login_miboy(self):
        """登录小米账号

        使用配置的账号密码登录小米账号，并初始化相关服务。
        """
        try:
            mi_account = MiAccount(
                self.mi_session,
                self.config.account,
                self.config.password,
                str(self.mi_token_home),
            )
            # Forced login to refresh to refresh token
            self.set_token(mi_account)
            await mi_account.login("micoapi")
            self.mina_service = MiNAService(mi_account)
            self.miio_service = MiIOService(mi_account)
            self.login_acount = self.config.account
            self.login_password = self.config.password
            self.log.info(f"登录完成. {self.login_acount}")
        except Exception as e:
            self.mina_service = None
            self.miio_service = None
            self.log.warning(f"可能登录失败. {e}")

    async def try_update_device_id(self):
        """更新设备ID

        从小米服务获取设备列表，更新配置中的设备信息。

        Returns:
            dict: 更新后的设备字典 {did: Device}
        """
        try:
            mi_dids = self.config.mi_did.split(",")
            hardware_data = await self.mina_service.device_list()
            devices = {}
            for h in hardware_data:
                device_id = h.get("deviceID", "")
                hardware = h.get("hardware", "")
                did = h.get("miotDID", "")
                name = h.get("alias", "")
                if not name:
                    name = h.get("name", "未知名字")
                if device_id and hardware and did and (did in mi_dids):
                    device = self.config.devices.get(did, Device())
                    device.did = did
                    # 将did存一下 方便其他地方调用
                    self._cur_did = did
                    device.device_id = device_id
                    device.hardware = hardware
                    device.name = name
                    devices[did] = device
            self.config.devices = devices
            self.log.info(f"选中的设备: {devices}")
            return devices
        except Exception as e:
            self.log.warning(f"可能登录失败. {e}")
            return {}

    def set_token(self, account):
        """
        设置token到account
        """
        if not self.config.cookie:
            return
        cookies_dict = parse_cookie_string_to_dict(self.config.cookie)
        account.token = {
            "passToken": cookies_dict["passToken"],
            "userId": cookies_dict["userId"],
            "deviceId": self.device_id,
        }
        self.log.info(f"设置token到account:{account.token}")

    def get_cookie(self):
        """获取Cookie

        从配置或token文件中获取Cookie。

        Returns:
            CookieJar: Cookie容器，失败返回None
        """
        if self.config.cookie:
            cookie_jar = parse_cookie_string(self.config.cookie)
            return cookie_jar

        if not os.path.exists(self.mi_token_home):
            self.log.warning(f"{self.mi_token_home} file not exist")
            return None

        with open(self.mi_token_home, encoding="utf-8") as f:
            user_data = json.loads(f.read())
        self.log.info(f"get_cookie user_data:{user_data}")
        user_id = user_data.get("userId")
        service_token = user_data.get("micoapi")[1]
        device_id = self.config.get_one_device_id()
        cookie_string = COOKIE_TEMPLATE.format(
            device_id=device_id, service_token=service_token, user_id=user_id
        )
        return parse_cookie_string(cookie_string)
