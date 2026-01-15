"""WebSocket 相关功能"""

import asyncio
import json
import secrets
import time

import jwt
from fastapi import (
    APIRouter,
    Depends,
    WebSocket,
    WebSocketDisconnect,
)

from xiaomusic.api.dependencies import (
    verification,
    xiaomusic,
)

router = APIRouter()

# JWT 配置
# 使用固定的 secret 避免重启后 token 失效
# 在生产环境中应该从环境变量或配置文件读取
JWT_SECRET = secrets.token_urlsafe(32)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = 60 * 5  # 5 分钟有效期（足够前端连接和重连）


@router.get("/generate_ws_token")
def generate_ws_token(
    did: str = "",
    _: bool = Depends(verification),  # 复用 HTTP Basic 验证
):
    # 允许空 did，用于全局监控
    payload = {
        "did": did,
        "exp": time.time() + JWT_EXPIRE_SECONDS,
        "iat": time.time(),
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    return {
        "token": token,
        "expire_in": JWT_EXPIRE_SECONDS,
    }


@router.websocket("/ws/playingmusic")
async def ws_playingmusic(websocket: WebSocket):
    """WebSocket 播放状态推送"""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="Missing token")
        return

    try:
        # 解码 JWT（自动校验签名 + 是否过期）
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        did = payload.get("did", "")

        # 允许空 did（用于全局监控），但需要检查设备是否存在
        if did and not xiaomusic.did_exist(did):
            await websocket.close(code=1003, reason="Did not exist")
            return

        await websocket.accept()

        # 开始推送状态
        while True:
            is_playing = xiaomusic.isplaying(did)
            cur_music = xiaomusic.playingmusic(did)
            cur_playlist = xiaomusic.get_cur_play_list(did)
            offset, duration = xiaomusic.get_offset_duration(did)

            await websocket.send_text(
                json.dumps(
                    {
                        "ret": "OK",
                        "is_playing": is_playing,
                        "cur_music": cur_music,
                        "cur_playlist": cur_playlist,
                        "offset": offset,
                        "duration": duration,
                    }
                )
            )
            await asyncio.sleep(1)

    except jwt.ExpiredSignatureError:
        await websocket.close(code=1008, reason="Token expired")
    except jwt.InvalidTokenError:
        await websocket.close(code=1008, reason="Invalid token")
    except WebSocketDisconnect:
        print(f"WebSocket disconnected: {did}")
    except Exception as e:
        print(f"Error: {e}")
        await websocket.close()
