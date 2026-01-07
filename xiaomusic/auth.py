"""认证管理模块

本模块负责小米账号认证与会话管理，包括：
- 小米账号登录
- Cookie管理
- 会话维护
- 设备ID更新
"""

import json
import os

from miservice import (
    MiAccount,
    MiIOService,
    MiNAService,
)

from xiaomusic.config import Device
from xiaomusic.const import COOKIE_TEMPLATE
from xiaomusic.utils import parse_cookie_string


class AuthManager:
    """认证管理器

    负责处理小米账号的登录、认证和会话管理。
    """

    def __init__(self, config, log, mi_token_home, get_one_device_id_func):
        """初始化认证管理器

        Args:
            config: 配置对象
            log: 日志对象
            mi_token_home: token文件路径
            get_one_device_id_func: 获取一个设备ID的函数
        """
        self.config = config
        self.log = log
        self.mi_token_home = mi_token_home
        self.get_one_device_id = get_one_device_id_func

        # 认证状态
        self.mina_service = None
        self.miio_service = None
        self.login_acount = None
        self.login_password = None
        self.cookie_jar = None

        # 当前设备DID（用于设备ID更新）
        self._cur_did = None

    async def init_all_data(self, session, try_update_device_id_func):
        """初始化所有数据

        检查登录状态，如需要则登录，然后更新设备ID和Cookie。

        Args:
            session: aiohttp客户端会话
            try_update_device_id_func: 更新设备ID的函数（来自device_manager）
        """
        self.mi_token_home = os.path.join(self.config.conf_path, ".mi.token")
        is_need_login = await self.need_login()
        if is_need_login:
            self.log.info("try login")
            await self.login_miboy(session)
        else:
            self.log.info("already logined")
        await try_update_device_id_func()
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
        user_id = user_data.get("userId")
        service_token = user_data.get("micoapi")[1]
        device_id = self.get_one_device_id()
        cookie_string = COOKIE_TEMPLATE.format(
            device_id=device_id, service_token=service_token, user_id=user_id
        )
        return parse_cookie_string(cookie_string)
