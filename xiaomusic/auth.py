"""认证管理模块

本模块负责小米账号认证与会话管理，包括：
- 小米账号登录
- Cookie管理
- 会话维护
- 设备ID更新
"""

import json
import os

from miservice import MiAccount, MiIOService, MiNAService

from xiaomusic.config import Device
from xiaomusic.const import COOKIE_TEMPLATE
from xiaomusic.utils.system_utils import (
    parse_cookie_string,
    parse_cookie_string_to_dict,
)


class AuthManager:
    """认证管理器

    负责处理小米账号的登录、认证和会话管理。
    """

    def __init__(self, config, log, mi_token_home):
        """初始化认证管理器

        Args:
            config: 配置对象
            log: 日志对象
            mi_token_home: token文件路径
        """
        self.config = config
        self.log = log
        self.mi_token_home = mi_token_home

        # 认证状态
        self.mina_service = None
        self.miio_service = None
        self.login_acount = None
        self.login_password = None
        self.cookie_jar = None

        # 当前设备DID（用于设备ID更新）
        self._cur_did = None

    async def init_all_data(self, session, device_manager):
        """初始化所有数据

        检查登录状态，如需要则登录，然后更新设备ID和Cookie。

        Args:
            session: aiohttp客户端会话
            device_manager: 设备管理器实例
        """
        self.mi_token_home = os.path.join(self.config.conf_path, ".mi.token")
        is_need_login = await self.need_login()
        if is_need_login:
            self.log.info("try login")
            await self.login_miboy(session)
        else:
            self.log.info("already logined")
        await device_manager.update_device_info(self)
        cookie_jar = self.get_cookie()
        if cookie_jar:
            session.cookie_jar.update_cookies(cookie_jar)
        self.cookie_jar = session.cookie_jar

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

    async def login_miboy(self, session):
        """登录小米账号

        使用配置的账号密码登录小米账号，并初始化相关服务。

        Args:
            session: aiohttp客户端会话
        """
        try:
            account = MiAccount(
                session,
                self.config.account,
                self.config.password,
                str(self.mi_token_home),
            )
            # Forced login to refresh to refresh token
            self.set_token(account)
            await account.login("micoapi")
            self.mina_service = MiNAService(account)
            self.miio_service = MiIOService(account)
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
        cookie_string = self.config.cookie
        cookie = SimpleCookie()
        cookie.load(cookie_string)
        cookies_dict = {k: m.value for k, m in cookie.items()}
        account.token["passToken"] = cookies_dict["passToken"]
        account.token["userId"] = self.config.account
        account.token["deviceId"] = get_random(16).upper()
        
    def save_token(self, cookie_str):
        """保存token到文件

        从请求数据中提取cookie并保存到.mi.token文件。

        Args:
            cookie_str: Cookie字符串
        """

        if cookie_str is None:
            return
        cookies_dict = parse_cookie_string_to_dict(cookie_str)

        with open(self.mi_token_home, "w") as f:
            json.dump(cookies_dict, f)

    def get_cookie(self):
        """获取Cookie

        从配置或token文件中获取Cookie。

        Returns:
            CookieJar: Cookie容器，失败返回None
        """
        if self.config.cookie:
            cookie_jar = parse_cookie_string(self.config.cookie)
            if not os.path.exists(self.mi_token_home):
                self.save_token(self.config.cookie)
            return cookie_jar

        if not os.path.exists(self.mi_token_home):
            self.log.warning(f"{self.mi_token_home} file not exist")
            return None

        with open(self.mi_token_home, encoding="utf-8") as f:
            user_data = json.loads(f.read())
        user_id = user_data.get("userId")
        service_token = user_data.get("micoapi")[1]
        device_id = self.config.get_one_device_id()
        cookie_string = COOKIE_TEMPLATE.format(
            device_id=device_id, service_token=service_token, user_id=user_id
        )
        return parse_cookie_string(cookie_string)
