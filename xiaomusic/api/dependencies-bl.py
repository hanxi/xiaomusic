"""依赖注入和认证相关功能"""

import hashlib
import secrets
from typing import (
    TYPE_CHECKING,
    Annotated,
)

from fastapi import (
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.security import (
    HTTPBasic,
    HTTPBasicCredentials,
)
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    import logging

    from xiaomusic.config import Config
    from xiaomusic.xiaomusic import XiaoMusic

security = HTTPBasic()


class _AppStateProxy:
    """应用状态代理类

    提供类似全局变量的访问方式，但实际上是动态获取的。
    这样既保持了代码的简洁性，又避免了真正的全局变量。
    """

    def __init__(self):
        self._xiaomusic: XiaoMusic | None = None
        self._config: Config | None = None
        self._log: logging.Logger | None = None

    def initialize(self, xiaomusic_instance: "XiaoMusic"):
        """初始化应用状态

        Args:
            xiaomusic_instance: XiaoMusic 实例
        """
        self._xiaomusic = xiaomusic_instance
        self._config = xiaomusic_instance.config
        self._log = xiaomusic_instance.log

    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._xiaomusic is not None


# 创建内部状态管理器
_state = _AppStateProxy()


class _LazyProxy:
    """延迟代理类，用于模拟全局变量"""

    def __init__(self, attr_name: str):
        self._attr_name = attr_name

    def __getattr__(self, name):
        """代理所有属性访问"""
        obj = getattr(_state, self._attr_name)
        if obj is None:
            raise RuntimeError(
                f"{self._attr_name} not initialized. Call initialize() first."
            )
        return getattr(obj, name)

    def __call__(self, *args, **kwargs):
        """代理函数调用"""
        obj = getattr(_state, self._attr_name)
        if obj is None:
            raise RuntimeError(
                f"{self._attr_name} not initialized. Call initialize() first."
            )
        return obj(*args, **kwargs)

    def __bool__(self):
        """支持布尔判断"""
        obj = getattr(_state, self._attr_name)
        return obj is not None and bool(obj)

    def __repr__(self):
        obj = getattr(_state, self._attr_name)
        return repr(obj) if obj is not None else f"<Uninitialized {self._attr_name}>"


# 创建代理对象，可以像普通变量一样使用
# 添加类型注解以支持 IDE 代码跳转和补全
xiaomusic: "XiaoMusic" = _LazyProxy("_xiaomusic")  # type: ignore
config: "Config" = _LazyProxy("_config")  # type: ignore
log: "logging.Logger" = _LazyProxy("_log")  # type: ignore


def verification(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
):
    """HTTP Basic 认证"""
    current_username_bytes = credentials.username.encode("utf8")
    correct_username_bytes = config.httpauth_username.encode("utf8")
    is_correct_username = secrets.compare_digest(
        current_username_bytes, correct_username_bytes
    )
    current_password_bytes = credentials.password.encode("utf8")
    correct_password_bytes = config.httpauth_password.encode("utf8")
    is_correct_password = secrets.compare_digest(
        current_password_bytes, correct_password_bytes
    )
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


def no_verification():
    """无认证模式"""
    return True


def access_key_verification(file_path: str, key: str, code: str) -> bool:
    """访问密钥验证"""
    if config.disable_httpauth:
        return True

    log.debug(f"访问限制接收端[{file_path}, {key}, {code}]")
    if key is not None:
        current_key_bytes = key.encode("utf8")
        correct_key_bytes = (
            config.httpauth_username + config.httpauth_password
        ).encode("utf8")
        is_correct_key = secrets.compare_digest(correct_key_bytes, current_key_bytes)
        if is_correct_key:
            return True

    if code is not None:
        current_code_bytes = code.encode("utf8")
        correct_code_bytes = (
            hashlib.sha256(
                (
                    file_path + config.httpauth_username + config.httpauth_password
                ).encode("utf-8")
            )
            .hexdigest()
            .encode("utf-8")
        )
        is_correct_code = secrets.compare_digest(correct_code_bytes, current_code_bytes)
        if is_correct_code:
            return True

    return False


class AuthStaticFiles(StaticFiles):
    """需要认证的静态文件服务"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send) -> None:
        request = Request(scope, receive)
        if not config.disable_httpauth:
            assert verification(await security(request))
        await super().__call__(scope, receive, send)


def reset_http_server(app):
    """重置 HTTP 服务器配置"""
    log.info(f"disable_httpauth:{config.disable_httpauth}")
    if config.disable_httpauth:
        app.dependency_overrides[verification] = no_verification
    else:
        app.dependency_overrides = {}
