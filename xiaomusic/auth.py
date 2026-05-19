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
    """认证管理器"""

    def __init__(self, config, log, device_manager):
        self.config = config
        self.log = log
        self.mi_token_home = os.path.join(self.config.conf_path, ".mi.token")

        self._init_lock = asyncio.Lock()
        self._last_login_time = 0
        self._last_login_ok = False
        self._consecutive_failures = 0

        self.mina_service = None
        self.miio_service = None
        self.login_acount = None
        self.login_password = None
        self.cookie_jar = None

        self._cur_did = None
        self.device_id = get_random(16).upper()
        self.mi_session = ClientSession()
        self.device_manager = device_manager

    async def init_all_data(self, force_login=False):
        try:
            async with asyncio.timeout(INIT_LOCK_TIMEOUT_SEC):
                async with self._init_lock:
                    await self._init_all_data_impl(force_login)
        except asyncio.TimeoutError:
            self.log.warning("init_all_data 超时，可能被其他调用持有锁")

    async def _init_all_data_impl(self, force_login=False):
        self.mi_token_home = os.path.join(self.config.conf_path, ".mi.token")
        self.log.info(
            f"[AUTH] init_all_data 开始, "
            f"mina_service={'None' if self.mina_service is None else '已创建'}, "
            f"login_acount={self.login_acount}, "
            f"config.account={self.config.account}, "
            f"config.password={'***' if self.config.password else '(空)'}, "
            f"auth.json存在={os.path.isfile(os.path.join(self.config.conf_path, 'auth.json'))}, "
            f".mi.token存在={os.path.isfile(self.mi_token_home)}, "
            f"force_login={force_login}"
        )
        if force_login:
            is_need_login = True
            self.log.info("[AUTH] force_login=True，强制重新登录")
        else:
            is_need_login = await self.need_login()
        is_can_login = await self.can_login()
        self.log.info(f"[AUTH] need_login={is_need_login}, can_login={is_can_login}")
        if is_need_login and is_can_login:
            self.log.info("[AUTH] 需要登录，开始执行 login_miboy")
            login_ok = await self.login_miboy()
            if not login_ok:
                self.log.warning("[AUTH] 登录失败，本次初始化中止")
                return
        else:
            self.log.info(
                f"[AUTH] 无需登录 need_login:{is_need_login} can_login:{is_can_login}"
            )
        await self.device_manager.update_device_info(self)
        cookie_jar = self.get_cookie()
        if cookie_jar:
            self.mi_session.cookie_jar.update_cookies(cookie_jar)
            self.log.info("[AUTH] cookie 已更新到 session")
        else:
            self.log.warning("[AUTH] get_cookie 返回 None，cookie 未更新")
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
            self.log.info("[AUTH-NEED] mina_service 为 None，需要登录")
            return True
        if self.login_acount != self.config.account:
            self.log.info(
                "[AUTH-NEED] 账号变更，需要登录: "
                f"old={self.login_acount} new={self.config.account}"
            )
            return True
        if self.login_password != self.config.password:
            self.log.info("[AUTH-NEED] 密码变更，需要登录")
            return True

        elapsed = time.time() - self._last_login_time
        if self._last_login_ok and elapsed < LOGIN_COOLDOWN_SEC:
            self.log.debug(
                f"[AUTH-NEED] 冷却期内({elapsed:.0f}s/{LOGIN_COOLDOWN_SEC}s)，跳过"
            )
            return False

        self.log.debug("[AUTH-NEED] 检查 device_list() 是否可用...")
        try:
            result = await self.mina_service.device_list()
            self.log.debug(f"[AUTH-NEED] device_list() 成功，返回 {len(result)} 个设备")
        except Exception as e:
            error_str = str(e)
            is_70016 = "70016" in error_str or "登录验证失败" in error_str
            if is_70016:
                self.log.warning(
                    f"[AUTH-NEED] device_list() 返回 70016(登录验证失败): {e}"
                )
            else:
                self.log.warning(f"[AUTH-NEED] device_list() 异常: {e}")
            if self._last_login_ok and elapsed < LOGIN_COOLDOWN_SEC * 2:
                self.log.warning(
                    "[AUTH-NEED] 最近登录成功但API调用失败，"
                    "可能是临时网络问题，暂不重新登录"
                )
                return False
            return True
        return False

    async def login_miboy(self):
        self.log.info(
            f"[AUTH-LOGIN] 开始登录, account={self.config.account or '(空/扫码登录)'}"
        )
        try:
            mi_account = MiAccount(
                self.mi_session,
                self.config.account,
                self.config.password,
                str(self.mi_token_home),
            )

            self.set_token(mi_account)
            token_info = mi_account.token
            self.log.info(
                f"[AUTH-LOGIN] MiAccount 创建成功, "
                f"token keys={list(token_info.keys()) if token_info else 'None'}, "
                f"has_passToken={'passToken' in (token_info or {})}, "
                f".mi.token存在={os.path.isfile(self.mi_token_home)}"
            )

            login_result = await mi_account.login("micoapi")
            self.log.info(
                f"[AUTH-LOGIN] mi_account.login('micoapi') 返回: {login_result}"
            )

            if not login_result:
                self._consecutive_failures += 1
                self.log.warning(
                    f"[AUTH-LOGIN] login 返回 False "
                    f"(连续失败次数: {self._consecutive_failures})"
                )

                refreshed = await self._try_fresh_session_and_relogin(mi_account)
                if refreshed:
                    self.log.info("[AUTH-LOGIN] 使用全新 session 重新登录后成功")
                    return True
                else:
                    self.mina_service = None
                    self.miio_service = None
                    self._last_login_ok = False
                    self._last_login_time = time.time()
                    self.log.warning(
                        "[AUTH-LOGIN] 最终登录失败，"
                        "passToken 可能已过期或被吊销，"
                        "建议重新扫码登录或检查网络"
                    )
                    return False

            self._consecutive_failures = 0
            self.mina_service = MiNAService(mi_account)
            self.miio_service = MiIOService(mi_account)
            self._patch_account(mi_account)
            self.login_acount = self.config.account
            self.login_password = self.config.password
            self._last_login_ok = True
            self._last_login_time = time.time()
            self.log.info(f"[AUTH-LOGIN] 登录完成. account={self.login_acount}")
            return True

        except KeyError as e:
            self._consecutive_failures += 1
            self.mina_service = None
            self.miio_service = None
            self._last_login_ok = False
            self._last_login_time = time.time()
            self.log.warning(
                f"[AUTH-LOGIN] KeyError(API响应格式错误): {e}，"
                "建议使用Cookie登录或访问小米官网验证"
            )
            return False
        except Exception as e:
            self._consecutive_failures += 1
            error_str = str(e)
            is_70016 = "70016" in error_str or "登录验证失败" in error_str
            self.mina_service = None
            self.miio_service = None
            self._last_login_ok = False
            self._last_login_time = time.time()
            if is_70016:
                self.log.warning(
                    f"[AUTH-LOGIN] 70016 错误(登录验证失败): {e}，"
                    "passToken 在 micoapi 服务端可能已被吊销"
                )
            else:
                self.log.warning(f"[AUTH-LOGIN] 异常: {e}")
            return False

    async def _try_fresh_session_and_relogin(self, old_mi_account):
        self.log.info("[AUTH-FRESH] 尝试使用全新 session 重新登录...")
        try:
            old_session = self.mi_session
            new_session = ClientSession()

            new_account = MiAccount(
                new_session,
                self.config.account,
                self.config.password,
                str(self.mi_token_home),
            )
            self.set_token(new_account)

            new_token = new_account.token
            old_token = old_mi_account.token
            self.log.info(
                f"[AUTH-FRESH] 新 MiAccount token keys="
                f"{list(new_token.keys()) if new_token else 'None'}, "
                f"旧 token keys={list(old_token.keys()) if old_token else 'None'}"
            )

            result = await new_account.login("micoapi")
            self.log.info(f"[AUTH-FRESH] 新 session login 结果: {result}")

            if result:
                self.log.info("[AUTH-FRESH] 替换为新 session 和 account")
                await old_session.close()
                self.mi_session = new_session
                self.mina_service = MiNAService(new_account)
                self.miio_service = MiIOService(new_account)
                self._patch_account(new_account)
                self.login_acount = self.config.account
                self.login_password = self.config.password
                self._last_login_ok = True
                self._last_login_time = time.time()
                self._consecutive_failures = 0
                return True
            else:
                self.log.warning("[AUTH-FRESH] 新 session 也失败了，关闭新 session")
                await new_session.close()
                return False

        except Exception as e:
            self.log.warning(f"[AUTH-FRESH] 过程异常: {e}")
            return False

    def _patch_account(self, mi_account):
        original_mi_request = mi_account.mi_request
        auth_manager = self

        async def patched_mi_request(sid, url, data, headers, relogin=True):
            try:
                return await original_mi_request(sid, url, data, headers, relogin)
            except Exception as exc:
                if not relogin:
                    raise
                error_msg = str(exc)
                auth_manager.log.warning(
                    f"[PATCH-mi_request] mi_request 失败: {error_msg}, "
                    f"尝试从 auth.json 恢复 passToken 后重试..."
                )

                mi_account.session.cookie_jar.clear()
                auth_manager.log.info("[PATCH-mi_request] 已清理 session cookie jar")

                auth_manager.set_token(mi_account)
                if mi_account.token and "passToken" in mi_account.token:
                    try:
                        login_ok = await mi_account.login(sid)
                        if login_ok:
                            auth_manager.log.info(
                                "[PATCH-mi_request] 恢复 passToken 后重新登录成功，重试原始请求"
                            )
                            return await original_mi_request(
                                sid, url, data, headers, False
                            )
                        else:
                            auth_manager.log.warning(
                                "[PATCH-mi_request] 恢复 passToken 后 login 仍返回 False"
                            )
                    except Exception as e2:
                        auth_manager.log.warning(
                            f"[PATCH-mi_request] 恢复 passToken 后重新登录异常: {e2}"
                        )
                else:
                    auth_manager.log.warning(
                        "[PATCH-mi_request] auth.json 中无有效 passToken，无法恢复"
                    )
                raise

        mi_account.mi_request = patched_mi_request

    async def try_update_device_id(self):
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
            self.log.info(f"[AUTH] 选中的设备: {devices}")
            return devices
        except Exception as e:
            self.log.warning(f"[AUTH] try_update_device_id 失败: {e}")
            return {}

    def set_token(self, account):
        auth_path = os.path.join(self.config.conf_path, "auth.json")
        if os.path.isfile(auth_path):
            try:
                with open(auth_path, encoding="utf-8") as f:
                    user_data = json.loads(f.read())
                    self.device_id = user_data["deviceId"]
                    account.token = {
                        "passToken": user_data["passToken"],
                        "userId": user_data["userId"],
                        "deviceId": self.device_id,
                    }
                    self.log.debug(
                        f"[AUTH-set_token] 从 auth.json 加载 token, "
                        f"userId={user_data.get('userId')}, "
                        f"deviceId={self.device_id}"
                    )
            except Exception as e:
                self.log.error(f"[AUTH-set_token] 读取 auth.json 失败: {e}")
        elif self.config.cookie:
            cookies_dict = parse_cookie_string_to_dict(self.config.cookie)
            account.token = {
                "passToken": cookies_dict["passToken"],
                "userId": cookies_dict["userId"],
                "deviceId": self.device_id,
            }
            self.log.debug("[AUTH-set_token] 从 cookie 配置加载 token")
        else:
            self.log.warning(
                "[AUTH-set_token] 无 auth.json 且无 cookie 配置，无法设置 token"
            )

    def get_cookie(self):
        if self.config.cookie:
            cookie_jar = parse_cookie_string(self.config.cookie)
            return cookie_jar

        if not os.path.exists(self.mi_token_home):
            self.log.warning(f"[AUTH-get_cookie] {self.mi_token_home} 不存在")
            cookie_jar = self._get_cookie_from_session()
            if cookie_jar:
                return cookie_jar
            return None

        try:
            with open(self.mi_token_home, encoding="utf-8") as f:
                user_data = json.loads(f.read())
            self.log.info("[AUTH-get_cookie] .mi.token 文件加载成功")
            user_id = user_data.get("userId")
            service_token = user_data.get("micoapi")[1]
            device_id = self.config.get_one_device_id()
            cookie_string = COOKIE_TEMPLATE.format(
                device_id=device_id, service_token=service_token, user_id=user_id
            )
            return parse_cookie_string(cookie_string)
        except Exception as e:
            self.log.warning(f"[AUTH-get_cookie] 读取 .mi.token 失败: {e}")
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
            self.log.warning("[AUTH-get_cookie] 内存 token 中缺少 micoapi 数据")
            return None
        user_id = token.get("userId")
        service_token = micoapi_data[1]
        device_id = self.config.get_one_device_id()
        if not user_id or not service_token:
            self.log.warning(
                "[AUTH-get_cookie] 内存 token 中缺少 userId 或 serviceToken"
            )
            return None
        self.log.info("[AUTH-get_cookie] 从内存 token 降级获取 cookie")
        cookie_string = COOKIE_TEMPLATE.format(
            device_id=device_id, service_token=service_token, user_id=user_id
        )
        return parse_cookie_string(cookie_string)
