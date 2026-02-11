import asyncio
import json
import locale
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union
from urllib import parse

import requests
import tzlocal
from qrcode import QRCode

import base64
import hashlib
import random
import time
from gzip import GzipFile
from io import BytesIO

from Crypto.Cipher import ARC4


def gen_nonce():
    millis = int(round(time.time() * 1000))
    b = (random.getrandbits(64) - 2 ** 63).to_bytes(8, "big", signed=True)
    part2 = int(millis / 60000)
    b += part2.to_bytes(((part2.bit_length() + 7) // 8), "big")
    return base64.b64encode(b).decode("utf-8")


def get_signed_nonce(ssecret, nonce):
    m = hashlib.sha256()
    m.update(base64.b64decode(bytes(ssecret, "utf-8")))
    m.update(base64.b64decode(bytes(nonce, "utf-8")))
    base64_bytes = base64.b64encode(m.digest())
    return base64_bytes.decode("utf-8")


def gen_enc_signature(uri, method, signed_nonce, params):
    signature_params = [
        str(method).upper(),
        uri,
    ]

    for k, v in params.items():
        signature_params.append(f"{k}={v}")

    signature_params.append(signed_nonce)
    signature_string = "&".join(signature_params)
    return base64.b64encode(
        hashlib.sha1(signature_string.encode("utf-8")).digest()
    ).decode()


def generate_enc_params(uri, method, signed_nonce, nonce, params, ssecurity):
    params["rc4_hash__"] = gen_enc_signature(uri, method, signed_nonce, params)

    for k, v in params.items():
        params[k] = encrypt_rc4(signed_nonce, v)

    params.update(
        {
            "signature": gen_enc_signature(uri, method, signed_nonce, params),
            "ssecurity": ssecurity,
            "_nonce": nonce,
        }
    )
    return params


def encrypt_rc4(password, payload):
    r = ARC4.new(base64.b64decode(password))
    r.encrypt(bytes(1024))
    return base64.b64encode(r.encrypt(payload.encode())).decode()


def decrypt_rc4(password, payload):
    r = ARC4.new(base64.b64decode(password))
    r.encrypt(bytes(1024))
    return r.encrypt(base64.b64decode(payload))


def decrypt(ssecurity, nonce, payload):
    decrypted = decrypt_rc4(get_signed_nonce(ssecurity, nonce), payload)
    try:
        return decrypted.decode("utf-8")
    except UnicodeDecodeError:
        compressed_file = BytesIO(decrypted)
        return GzipFile(fileobj=compressed_file, mode="rb").read().decode("utf-8")


class MiJiaAPI:
    def __init__(self, auth_data_path: Optional[str] = None):
        self.locale = locale.getlocale()[0] if locale.getlocale()[0] else "zh_CN"
        if "_" not in self.locale:  # #57, make sure locale is in correct format
            self.locale = "zh_CN"
        self.api_base_url = "https://api.mijia.tech/app"
        self.login_url = "https://account.xiaomi.com/longPolling/loginUrl"
        self.service_login_url = f"https://account.xiaomi.com/pass/serviceLogin?_json=true&sid=mijia&_locale={self.locale}"

        if auth_data_path is None:
            self.auth_data_path = Path.home() / ".config" / "mijia-api" / "auth.json"
        elif Path(auth_data_path).is_dir():
            self.auth_data_path = Path(auth_data_path) / "auth.json"
        else:
            self.auth_data_path = Path(auth_data_path)

        self._available_cache = None
        self._available_cache_time = 0

        if self.auth_data_path.exists():
            with open(self.auth_data_path, "r") as f:
                self.auth_data = json.load(f)
            self._init_session()
        else:
            self.auth_data = {}

    def _init_session(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "accept-encoding": "identity",
                "Content-Type": "application/x-www-form-urlencoded",
                "miot-accept-encoding": "GZIP",
                "miot-encrypt-algorithm": "ENCRYPT-RC4",
                "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
                "Cookie": f"cUserId={self.auth_data['cUserId']};"
                          f"yetAnotherServiceToken={self.auth_data['serviceToken']};"
                          f"serviceToken={self.auth_data['serviceToken']};"
                          f"timezone_id={tzlocal.get_localzone_name()};"
                          f"timezone=GMT{datetime.now().astimezone().strftime('%z')[:3]}:{datetime.now().astimezone().strftime('%z')[3:]};"
                          f"is_daylight={time.daylight};"
                          f"dst_offset={time.localtime().tm_isdst * 60 * 60 * 1000};"
                          f"channel=MI_APP_STORE;"
                          f"countryCode={self.locale.split('_')[1] if self.locale else 'CN'};"
                          f"PassportDeviceId={self.device_id};"
                          f"locale={self.locale}",
            }
        )

    @property
    def available(self) -> bool:
        if not self.auth_data:
            return False
        if any(
                key not in self.auth_data
                for key in ["ua", "ssecurity", "userId", "cUserId", "serviceToken"]
        ):
            return False

        current_time = int(time.time())
        if current_time - self._available_cache_time < 60:
            print(f"使用缓存的available结果: {self._available_cache}")
            return self._available_cache

        try:
            self.check_new_msg(refresh_token=False)
        except Exception:
            self._available_cache = None
            self._available_cache_time = 0
            return False

        self._available_cache = True
        self._available_cache_time = current_time
        return True

    @property
    def pass_o(self) -> str:
        if "pass_o" in self.auth_data:
            return self.auth_data["pass_o"]
        self.auth_data["pass_o"] = "".join(random.choices("0123456789abcdef", k=16))
        return self.auth_data["pass_o"]

    @property
    def user_agent(self) -> str:
        if "ua" in self.auth_data:
            return self.auth_data["ua"]
        ua_id1 = "".join(random.choices("0123456789ABCDEF", k=40))
        ua_id2 = "".join(random.choices("0123456789ABCDEF", k=32))
        ua_id3 = "".join(random.choices("0123456789ABCDEF", k=32))
        ua_id4 = "".join(random.choices("0123456789ABCDEF", k=40))
        self.auth_data["ua"] = (
            f"Android-15-11.0.701-Xiaomi-23046RP50C-OS2.0.212.0.VMYCNXM-"
            f"{ua_id1}-{self.locale.split('_')[1] if self.locale else 'CN'}-"
            f"{ua_id3}-{ua_id2}-SmartHome-MI_APP_STORE-{ua_id1}|{ua_id4}|{self.pass_o}-64"
        )
        return self.auth_data["ua"]

    @property
    def device_id(self) -> str:
        if "deviceId" in self.auth_data:
            return self.auth_data["deviceId"]
        self.auth_data["deviceId"] = "".join(
            random.choices(
                "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-", k=16
            )
        )
        return self.auth_data["deviceId"]

    def _parse_service_ret(self, service_ret: requests.Response) -> dict:
        text = service_ret.text.replace("&&&START&&&", "")
        service_data = json.loads(text)
        return service_data

    def _handle_ret(
            self, fetch_ret: requests.Response, verify_code: bool = True
    ) -> dict:
        if fetch_ret.status_code != 200:
            raise ValueError(
                f"请求失败，状态码: {fetch_ret.status_code}, 响应: {fetch_ret.text}"
            )
        fetch_data = self._parse_service_ret(fetch_ret)
        if verify_code and fetch_data.get("code", 0) != 0:
            raise ValueError(
                f"验证码错误，状态码: {fetch_data['code']}, 响应: {fetch_data.get('desc', '未知错误')}"
            )
        return fetch_data

    @staticmethod
    def _print_qr(loginurl: str, box_size: int = 10):
        print(f"请使用米家APP扫描下方二维码: {loginurl}")

        qr = QRCode(border=1, box_size=box_size)
        qr.add_data(loginurl)
        try:
            qr.print_ascii(invert=True, tty=True)
        except OSError:
            qr.print_ascii(invert=True, tty=False)
            print(
                "如果无法扫描二维码，"
                "请更改终端字体，"
                "如`Maple Mono`、`Fira Code`等。"
            )

    def _save_auth_data(self):
        self.auth_data["saveTime"] = int(time.time() * 1000)
        self.auth_data_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.auth_data_path, "w") as f:
            json.dump(self.auth_data, f, indent=2, ensure_ascii=False)
        print(f"已保存认证数据到 {self.auth_data_path}")
        print(f"认证数据: {self.auth_data}")

    def _get_location(self) -> dict:
        headers = {
            "User-Agent": self.user_agent,
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": f"deviceId={self.device_id};"
                      f"pass_o={self.pass_o};"
                      f"passToken={self.auth_data.get('passToken', '')};"
                      f"userId={self.auth_data.get('userId', '')};"
                      f"cUserId={self.auth_data.get('cUserId', '')};"
                      f"uLocale={self.locale};",
        }
        service_ret = requests.get(self.service_login_url, headers=headers)
        service_data = self._handle_ret(service_ret, verify_code=False)
        location = service_data["location"]
        if service_data["code"] == 0:
            ret = self.session.get(location)
            if ret.status_code == 200 and ret.text == "ok":
                cookies = self.session.cookies.get_dict()
                self.auth_data.update(cookies)
                self.auth_data["ssecurity"] = service_data["ssecurity"]
                return {"code": 0, "message": "刷新Token成功"}
        location_data = parse.parse_qs(parse.urlparse(location).query)
        return {k: v[0] for k, v in location_data.items()}

    def _refresh_token(self) -> dict:
        if self.available:
            print("Token 有效，无需刷新")
            return self.auth_data
        location_data = self._get_location()
        if (
                location_data.get("code", -1) == 0
                and location_data.get("message", "") == "刷新Token成功"
        ):
            self._save_auth_data()
            self._init_session()
            print("刷新Token成功")
            return self.auth_data
        else:
            raise ValueError("刷新Token失败，请重新登录")

    def get_qrcode(self):
        # Step 1: 从 serviceLogin 获取登录链接参数
        location_data = self._get_location()
        if (
                location_data.get("code", -1) == 0
                and location_data.get("message", "") == "刷新Token成功"
        ):
            self._save_auth_data()
            self._init_session()
            print("刷新Token成功，无需登录")
            return False

        # Step 2: 获取并打印二维码
        location_data.update(
            {
                "theme": "",
                "bizDeviceType": "",
                "_hasLogo": "false",
                "_qrsize": "240",
                "_dc": str(int(time.time() * 1000)),
            }
        )
        url = self.login_url + "?" + parse.urlencode(location_data)
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip",
            "Content-Type": "application/x-www-form-urlencoded",
            "Connection": "keep-alive",
        }
        login_ret = requests.get(url, headers=headers)
        return self._handle_ret(login_ret)

    def get_logint_status(self, status_url):
        # Step 3: 轮询等待扫码登录
        session = requests.Session()
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip",
            "Content-Type": "application/x-www-form-urlencoded",
            "Connection": "keep-alive",
        }
        try:
            lp_ret = session.get(status_url, headers=headers, timeout=120)
            lp_data = self._handle_ret(lp_ret)
        except requests.exceptions.Timeout:
            raise ValueError("超时，请重试")

        # Step 4: 处理登录结果
        auth_keys = [
            "psecurity",
            "nonce",
            "ssecurity",
            "passToken",
            "userId",
            "cUserId",
        ]
        for key in auth_keys:
            self.auth_data[key] = lp_data[key]
        callback_url = lp_data["location"]
        session.get(callback_url, headers=headers)
        cookies = session.cookies.get_dict()
        self.auth_data.update(cookies)
        self.auth_data.update(
            {
                "expireTime": int(
                    (datetime.now() + timedelta(days=30)).timestamp() * 1000
                ),
            }
        )
        self._save_auth_data()
        print("登录成功")
        self._init_session()

    def qr_login(self) -> dict:
        """
        二维码登录方法

        通过米家账号二维码登录，使用米家APP扫描二维码完成身份验证。
        如果Token有效，会直接返回并保存认证数据。

        参数:
            无

        返回值:
            dict: 包含认证信息的字典，包括以下关键字段: ["psecurity", "nonce", "ssecurity", "passToken", "userId", "cUserId", "serviceToken", "expireTime", ...]

        异常:
            LoginError: 当登录超时或服务器返回错误时抛出
        """
        # Step 1: 从 serviceLogin 获取登录链接参数
        location_data = self._get_location()
        if (
                location_data.get("code", -1) == 0
                and location_data.get("message", "") == "刷新Token成功"
        ):
            self._save_auth_data()
            self._init_session()
            print("刷新Token成功，无需登录")
            return self.auth_data

        # Step 2: 获取并打印二维码
        location_data.update(
            {
                "theme": "",
                "bizDeviceType": "",
                "_hasLogo": "false",
                "_qrsize": "240",
                "_dc": str(int(time.time() * 1000)),
            }
        )
        url = self.login_url + "?" + parse.urlencode(location_data)
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip",
            "Content-Type": "application/x-www-form-urlencoded",
            "Connection": "keep-alive",
        }
        login_ret = requests.get(url, headers=headers)
        login_data = self._handle_ret(login_ret)
        self._print_qr(login_data["loginUrl"])
        print(f"也可以访问链接查看二维码图片: {login_data['qr']}")

        # Step 3: 轮询等待扫码登录
        session = requests.Session()
        try:
            lp_ret = session.get(login_data["lp"], headers=headers, timeout=120)
            lp_data = self._handle_ret(lp_ret)
        except requests.exceptions.Timeout:
            raise ValueError("超时，请重试")

        # Step 4: 处理登录结果
        auth_keys = [
            "psecurity",
            "nonce",
            "ssecurity",
            "passToken",
            "userId",
            "cUserId",
        ]
        for key in auth_keys:
            self.auth_data[key] = lp_data[key]
        callback_url = lp_data["location"]
        session.get(callback_url, headers=headers)
        cookies = session.cookies.get_dict()
        self.auth_data.update(cookies)
        self.auth_data.update(
            {
                "expireTime": int(
                    (datetime.now() + timedelta(days=30)).timestamp() * 1000
                ),
            }
        )
        self._save_auth_data()
        print("登录成功")
        self._init_session()
        return self.auth_data

    def _request(self, uri: str, data: dict, refresh_token: bool = True) -> dict:
        print(f"请求 URI: {uri}，数据: {data}")
        if refresh_token:
            self._refresh_token()
        url = self.api_base_url + uri
        params = {"data": json.dumps(data, separators=(",", ":"))}
        nonce = gen_nonce()
        signed_nonce = get_signed_nonce(self.auth_data["ssecurity"], nonce)
        params = generate_enc_params(
            uri, "POST", signed_nonce, nonce, params, self.auth_data["ssecurity"]
        )
        ret = self.session.post(url, data=params)
        try:
            ret_data = json.loads(ret.text)
        except json.JSONDecodeError:
            dec_data = decrypt(self.auth_data["ssecurity"], nonce, ret.text)
            ret_data = json.loads(dec_data)
        print(f"响应数据: {ret_data}")
        if ret_data.get("code", 0) != 0 or "result" not in ret_data:
            raise ValueError(
                f"API错误，状态码: {ret_data['code']}, 响应: {ret_data.get('message', ret_data.get('desc', '未知错误'))}"
            )
        return ret_data["result"]

    def check_new_msg(
            self, begin_at: int = int(time.time()) - 3600, refresh_token: bool = True
    ) -> dict:
        uri = "/v2/message/v2/check_new_msg"
        data = {"begin_at": begin_at}
        return self._request(uri, data, refresh_token=refresh_token)


if __name__ == "__main__":
    mi_jia_api = MiJiaAPI()
    mi_jia_api.qr_login()
