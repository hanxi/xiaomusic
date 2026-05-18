"""认证管理模块

本模块负责小米账号认证与会话管理，包括：
- 小米账号登录
- Cookie管理
- 会话维护
- 设备ID更新
"""

import asyncio
import json
import os
import time

from aiohttp import ClientSession
from miservice import MiAccount, MiIOService, MiNAService

from xiaomusic.config import Device
from xiaomusic.const import COOKIE_TEMPLATE
from xiaomusic.utils.system_utils import (
    get_random,
    parse_cookie_string,
    parse_cookie_string_to_dict,
)

LOGIN_COOLDOWN_SEC = 30
INIT_LOCK_TIMEOUT_SEC = 60


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

        self._init_lock = asyncio.Lock()
        self._last_login_time = 0
        self._last_login_ok = False

        self.mina_service = None
        self.miio_service = None
        self.login_acount = None
        self.login_password = None
        self.cookie_jar = None

        self._cur_did = None
        self.device_id = get_random(16).upper()
        self.mi_session = ClientSession()
        self.device_manager = device_manager

    async def init_all_data(self):
        try:
            async with asyncio.timeout(INIT_LOCK_TIMEOUT_SEC):
                async with self._init_lock:
                    await self._init_all_data_impl()
        except asyncio.TimeoutError:
            self.log.warning("init_all_data 超时，可能被其他调用持有锁")

    async def _init_all_data_impl(self):
        self.mi_token_home = os.path.join(self.config.conf_path, ".mi.token")
        is_need_login = await self.need_login()
        is_can_login = await self.can_login()
        if is_need_login and is_can_login:
            self.log.info("try login")
            login_ok = await self.login_miboy()
            if not login_ok:
                self.log.warning("登录失败，跳过本次初始化")
                return
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
        if os.path.isfile(os.path.join(self.config.conf_path, "auth.json")):
            return True
        self.log.warning("没有账号密码 或 cookies 无法登陆")
        return False

    async def need_login(self):
        if self.mina_service is None:
            return True
        if self.login_acount != self.config.account:
            return True
        if self.login_password != self.config.password:
            return True

        elapsed = time.time() - self._last_login_time
        if self._last_login_ok and elapsed < LOGIN_COOLDOWN_SEC:
            self.log.debug(
                f"最近登录成功且在冷却期内({elapsed:.0f}s/{LOGIN_COOLDOWN_SEC}s)，跳过登录检查"
            )
            return False

        try:
            await self.mina_service.device_list()
        except Exception as e:
            self.log.warning(f"可能登录失败. {e}")
            if self._last_login_ok and elapsed < LOGIN_COOLDOWN_SEC * 2:
                self.log.warning(
                    "最近登录成功但API调用失败，可能是临时网络问题，暂不重新登录"
                )
                return False
            return True
        return False

    async def login_miboy(self):
        try:
            mi_account = MiAccount(
                self.mi_session,
                self.config.account,
                self.config.password,
                str(self.mi_token_home),
            )
            self.set_token(mi_account)
            self._patch_account(mi_account)
            login_result = await mi_account.login("micoapi")
            if not login_result:
                self.mina_service = None
                self.miio_service = None
                self._last_login_ok = False
                self._last_login_time = time.time()
                self.log.warning("小米账号登录返回失败，请检查账号密码是否正确")
                return False
            self.mina_service = MiNAService(mi_account)
            self.miio_service = MiIOService(mi_account)
            self.login_acount = self.config.account
            self.login_password = self.config.password
            self._last_login_ok = True
            self._last_login_time = time.time()
            self.log.info(f"登录完成. {self.login_acount}")
            return True
        except KeyError as e:
            self.mina_service = None
            self.miio_service = None
            self._last_login_ok = False
            self._last_login_time = time.time()
            self.log.warning(
                f"登录失败，API响应格式错误: {e}。建议使用Cookie登录或访问小米官网验证"
            )
            return False
        except Exception as e:
            self.mina_service = None
            self.miio_service = None
            self._last_login_ok = False
            self._last_login_time = time.time()
            self.log.warning(f"可能登录失败. {e}")
            return False

    def _patch_account(self, mi_account):
        """修补 MiAccount.mi_request 的 401 重试逻辑

        原始 mi_request 在收到 401 时会 self.token = None，
        然后内部重新 login，但此时 passToken 已经丢失，
        对于二维码登录（无账号密码）的场景将永远无法恢复。

        修补方案：替换 mi_request，401 时从 auth.json 重新加载 passToken，
        然后再尝试 login。
        """
        original_mi_request = mi_account.mi_request
        auth_manager = self

        async def patched_mi_request(sid, url, data, headers, relogin=True):
            try:
                return await original_mi_request(sid, url, data, headers, relogin)
            except Exception:
                if not relogin:
                    raise
                auth_manager.log.warning(
                    "mi_request 401 重试失败，尝试从 auth.json 重新加载 passToken"
                )
                auth_manager.set_token(mi_account)
                if mi_account.token and "passToken" in mi_account.token:
                    try:
                        login_ok = await mi_account.login(sid)
                        if login_ok:
                            auth_manager.log.info(
                                "从 auth.json 恢复 passToken 后重新登录成功"
                            )
                            return await original_mi_request(
                                sid, url, data, headers, False
                            )
                    except Exception as e2:
                        auth_manager.log.warning(
                            f"恢复 passToken 后重新登录仍然失败: {e2}"
                        )
                raise

        mi_account.mi_request = patched_mi_request

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
                if device_id and hardware and did:
                    if not mi_dids or not mi_dids[0] or (did in mi_dids):
                        device = self.config.devices.get(did, Device())
                        device.did = did
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
        auth_path = os.path.join(self.config.conf_path, "auth.json")
        if os.path.isfile(auth_path):
            with open(auth_path, encoding="utf-8") as f:
                user_data = json.loads(f.read())
                self.device_id = user_data["deviceId"]
                account.token = {
                    "passToken": user_data["passToken"],
                    "userId": user_data["userId"],
                    "deviceId": self.device_id,
                }
        elif self.config.cookie:
            cookies_dict = parse_cookie_string_to_dict(self.config.cookie)
            account.token = {
                "passToken": cookies_dict["passToken"],
                "userId": cookies_dict["userId"],
                "deviceId": self.device_id,
            }
        else:
            return

    def get_cookie(self):
        if self.config.cookie:
            cookie_jar = parse_cookie_string(self.config.cookie)
            return cookie_jar

        if not os.path.exists(self.mi_token_home):
            self.log.warning(f"{self.mi_token_home} file not exist")
            cookie_jar = self._get_cookie_from_session()
            if cookie_jar:
                return cookie_jar
            return None

        try:
            with open(self.mi_token_home, encoding="utf-8") as f:
                user_data = json.loads(f.read())
            self.log.info("get_cookie user_data loaded")
            user_id = user_data.get("userId")
            service_token = user_data.get("micoapi")[1]
            device_id = self.config.get_one_device_id()
            cookie_string = COOKIE_TEMPLATE.format(
                device_id=device_id, service_token=service_token, user_id=user_id
            )
            return parse_cookie_string(cookie_string)
        except Exception as e:
            self.log.warning(f"读取token文件失败: {e}")
            cookie_jar = self._get_cookie_from_session()
            if cookie_jar:
                return cookie_jar
            return None

    def _get_cookie_from_session(self):
        if self.mina_service is None:
            return None
        account = self.mina_service.account
        if not account or not account.token:
            return None
        token = account.token
        micoapi_data = token.get("micoapi")
        if not micoapi_data or len(micoapi_data) < 2:
            self.log.warning("内存token中缺少micoapi数据")
            return None
        user_id = token.get("userId")
        service_token = micoapi_data[1]
        device_id = self.config.get_one_device_id()
        if not user_id or not service_token:
            self.log.warning("内存token中缺少userId或serviceToken")
            return None
        self.log.info("从内存token降级获取cookie成功")
        cookie_string = COOKIE_TEMPLATE.format(
            device_id=device_id, service_token=service_token, user_id=user_id
        )
        return parse_cookie_string(cookie_string)
