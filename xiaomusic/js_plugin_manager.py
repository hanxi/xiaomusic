#!/usr/bin/env python3
"""
JS 插件管理器
负责加载、管理和运行 MusicFree JS 插件
"""

import asyncio
import base64
import json
import logging
import os
import random
import shutil
import subprocess
import threading
import time
from typing import Any


class JSPluginManager:
    """JS 插件管理器"""

    def __init__(self, xiaomusic):
        self.xiaomusic = xiaomusic
        base_path = self.xiaomusic.config.conf_path
        self.log = logging.getLogger(__name__)
        # JS插件文件夹：
        self.plugins_dir = os.path.join(base_path, "js_plugins")
        # 插件配置Json：
        self.plugins_config_path = os.path.join(base_path, "plugins-config.json")
        self.plugins = {}  # 插件状态信息
        self.node_process = None
        self.message_queue = []
        self.response_handlers = {}
        self._lock = threading.Lock()
        self.request_id = 0
        self.pending_requests = {}
        self._is_shutting_down = False  # 添加关闭标志

        # 进程重启控制
        self._restart_count = 0  # 重启计数器
        self._last_restart_time = 0  # 上次重启时间戳
        self._restart_window = 60  # 重启时间窗口（秒）
        self._max_restarts_in_window = 1  # 时间窗口内最大重启次数

        # ... 配置文件相关 ...
        self._config_cache = None
        self._config_cache_time = 0
        self._config_cache_ttl = 3 * 60  # 缓存有效期5秒，可根据需要调整

        # 自动转换定时任务
        self._auto_convert_task = None
        self._auto_convert_interval = 30  # 定时任务间隔（秒）

        # 启动 Node.js 子进程
        self._start_node_process()

        # 启动消息处理线程
        self._start_message_handler()

        # 加载插件
        self._load_plugins()

    def _start_node_process(self):
        """启动 Node.js 子进程"""
        runner_path = os.path.join(os.path.dirname(__file__), "js_plugin_runner.js")

        try:
            self.node_process = subprocess.Popen(
                ["node", "--max-old-space-size=128", runner_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,  # 行缓冲
            )

            self.log.info("Node.js process started successfully")

            # 启动进程监控线程
            threading.Thread(target=self._monitor_node_process, daemon=True).start()

        except Exception as e:
            self.log.error(f"Failed to start Node.js process: {e}")
            raise

    def _monitor_node_process(self):
        """监控 Node.js 进程状态"""
        while True:
            if self._is_shutting_down:
                break
            if self.node_process and self.node_process.poll() is not None:
                if not self._is_shutting_down:
                    self._attempt_restart_node_process()
            time.sleep(5)

    def _attempt_restart_node_process(self):
        """尝试重启 Node.js 进程，带有限制机制"""
        current_time = time.time()

        # 检查是否在重启时间窗口内
        if current_time - self._last_restart_time < self._restart_window:
            # 在时间窗口内，检查重启次数
            if self._restart_count >= self._max_restarts_in_window:
                self.log.error(
                    f"Node.js process restart limit exceeded: {self._restart_count} restarts in {self._restart_window} seconds. "
                    "Manual intervention required."
                )
                return False
        else:
            # 超出时间窗口，重置计数器
            self._restart_count = 0

        # 执行重启
        self._restart_count += 1
        self._last_restart_time = current_time

        remaining_attempts = self._max_restarts_in_window - self._restart_count
        self.log.warning(
            f"Node.js process died, attempting restart ({self._restart_count}/{self._max_restarts_in_window}). "
            f"Remaining attempts in current window: {remaining_attempts}"
        )

        try:
            self._start_node_process()
            return True
        except Exception as e:
            self.log.error(f"Failed to restart Node.js process: {e}")
            return False

    def _start_message_handler(self):
        """启动消息处理线程"""

        def stdout_handler():
            while True:
                if self.node_process and self.node_process.stdout:
                    try:
                        line = self.node_process.stdout.readline()
                        if line:
                            response = json.loads(line.strip())
                            self._handle_response(response)
                    except json.JSONDecodeError as e:
                        # 捕获非 JSON 输出（可能是插件的调试信息或错误信息）
                        self.log.warning(
                            f"Non-JSON output from Node.js process: {line.strip()}, error: {e}"
                        )
                    except Exception as e:
                        self.log.error(f"Message handler error: {e}")
                time.sleep(0.1)

        def stderr_handler():
            """处理 Node.js 进程的错误输出"""
            while True:
                if self.node_process and self.node_process.stderr:
                    try:
                        error_line = self.node_process.stderr.readline()
                        if error_line:
                            self.log.error(
                                f"Node.js process error output: {error_line.strip()}"
                            )
                    except Exception as e:
                        self.log.error(f"Error handler error: {e}")
                time.sleep(0.1)

        threading.Thread(target=stdout_handler, daemon=True).start()
        threading.Thread(target=stderr_handler, daemon=True).start()

    def _send_message(
        self, message: dict[str, Any], timeout: int = 30
    ) -> dict[str, Any]:
        """发送消息到 Node.js 子进程"""
        with self._lock:
            # 检查进程状态，必要时尝试重启
            if not self.node_process or self.node_process.poll() is not None:
                self.log.warning(
                    "Node.js process not available, checking restart possibility..."
                )
                # 尝试重启进程
                if not self._attempt_restart_node_process():
                    raise Exception("Node.js process not available and restart failed")

                # 等待进程稳定
                time.sleep(1)

                # 再次检查进程状态
                if not self.node_process or self.node_process.poll() is not None:
                    raise Exception(
                        "Node.js process not available after restart attempt"
                    )

            message_id = f"msg_{int(time.time() * 1000)}"
            message["id"] = message_id

            # 记录发送的消息
            self.log.info(
                f"JS Plugin Manager sending message: {message.get('action', 'unknown')} for plugin: {message.get('pluginName', 'unknown')}"
            )
            if "params" in message:
                self.log.info(f"JS Plugin Manager search params: {message['params']}")
            elif "musicItem" in message:
                self.log.info(f"JS Plugin Manager music item: {message['musicItem']}")

            # 发送消息
            self.node_process.stdin.write(json.dumps(message) + "\n")
            self.node_process.stdin.flush()

            # 等待响应
            response = self._wait_for_response(message_id, timeout)
            self.log.info(
                f"JS Plugin Manager received response for message {message_id}: {response.get('success', 'unknown')}"
            )
            return response

    def _wait_for_response(self, message_id: str, timeout: int) -> dict[str, Any]:
        """等待特定消息的响应"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if message_id in self.response_handlers:
                response = self.response_handlers.pop(message_id)
                return response
            time.sleep(0.1)

        raise TimeoutError(f"Message {message_id} timeout")

    def _handle_response(self, response: dict[str, Any]):
        """处理 Node.js 进程的响应"""
        message_id = response.get("id")
        self.log.debug(
            f"JS Plugin Manager received raw response: {response}"
        )  # 添加原始响应日志

        # 添加更严格的数据验证
        if not isinstance(response, dict):
            self.log.error(
                f"JS Plugin Manager received invalid response type: {type(response)}, value: {response}"
            )
            return

        if "id" not in response:
            self.log.error(
                f"JS Plugin Manager received response without id: {response}"
            )
            return

        # 确保 success 字段存在
        if "success" not in response:
            self.log.warning(
                f"JS Plugin Manager received response without success field: {response}"
            )
            response["success"] = False

        # 如果有 result 字段，验证其结构
        if "result" in response and response["result"] is not None:
            result = response["result"]
            if isinstance(result, dict):
                # 对搜索结果进行特殊处理
                if "data" in result and not isinstance(result["data"], list):
                    self.log.warning(
                        f"JS Plugin Manager received result with invalid data type: {type(result['data'])}, setting to empty list"
                    )
                    result["data"] = []

        if message_id:
            self.response_handlers[message_id] = response

    def get_aiapi_info(self) -> dict[str, Any]:
        """获取AI接口配置信息
        Returns:
            Dict[str, Any]: 包含 OpenAPI 配置信息的字典，包括启用状态和搜索 URL
        """
        try:
            # 读取配置文件中的 OpenAPI 配置信息
            config_data = self._get_config_data()
            if config_data:
                return config_data.get("aiapi_info", {})
            else:
                return {"enabled": False}
        except Exception as e:
            self.log.error(f"Failed to read AI info from config: {e}")
            return {}

    def get_advanced_config(self) -> dict[str, Any]:
        """获取高级配置信息
        Returns:
            Dict[str, Any]: 包含高级配置信息的字典
        """
        try:
            config_data = self._get_config_data()
            if config_data:
                return {
                    "auto_add_song": config_data.get("auto_add_song", False),
                    "auto_convert": config_data.get("auto_convert", False),
                    "aiapi_info": config_data.get("aiapi_info", {}),
                    "voice_playlist_strategy": self.get_voice_playlist_strategy(),
                }
            else:
                return {
                    "auto_add_song": False,
                    "auto_convert": False,
                    "aiapi_info": {"enabled": False, "api_key": ""},
                    "voice_playlist_strategy": "default",
                }
        except Exception as e:
            self.log.error(f"Failed to read advanced config: {e}")
            return {
                "auto_add_song": False,
                "auto_convert": False,
                "aiapi_info": {"enabled": False, "api_key": ""},
                "voice_playlist_strategy": "default",
            }

    def update_advanced_config(
        self,
        auto_add_song: bool = None,
        auto_convert: bool = None,
        aiapi_info: dict = None,
        voice_playlist_strategy: str = None,
    ) -> dict[str, Any]:
        """更新高级配置信息
        Args:
            auto_add_song: 自动添加歌曲开关
            auto_convert: 自动转换洛雪歌单开关
            aiapi_info: AI接口配置信息
            voice_playlist_strategy: 语音搜索歌单获取策略
        Returns:
            更新结果字典
        """
        try:
            if os.path.exists(self.plugins_config_path):
                with open(self.plugins_config_path, encoding="utf-8") as f:
                    config_data = json.load(f)

                if auto_add_song is not None:
                    config_data["auto_add_song"] = auto_add_song

                if auto_convert is not None:
                    config_data["auto_convert"] = auto_convert

                if aiapi_info is not None:
                    config_data["aiapi_info"] = aiapi_info

                if voice_playlist_strategy is not None:
                    config_data["voice_playlist_strategy"] = {
                        "desc": "语音搜单策略: default(首条), max_songs(歌曲最多), max_plays(播放最多), random(随机)",
                        "value": voice_playlist_strategy
                    }

                with open(self.plugins_config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)
                self._invalidate_config_cache()

                if auto_convert is not None:
                    self.restart_auto_convert()

                return {"success": True}
            else:
                return {"success": False, "error": "Config file not found"}
        except Exception as e:
            self.log.error(f"Failed to update advanced config: {e}")
            return {"success": False, "error": str(e)}

    def get_back_conf_info(self) -> dict[str, Any]:
        """获取lxServer接口配置信息
        Returns:
            Dict[str, Any]: 包含 lxServer接口 配置信息的字典，包括启用状态和搜索 URL
        """
        try:
            # 读取配置文件中的 LX Server 配置信息
            config_data = self._get_config_data()
            if config_data:
                # 返回 back_conf_info 配置项
                return config_data.get("back_conf_info", {})
            else:
                return {"enabled": False}
        except Exception as e:
            self.log.error(f"Failed to read LX Server info from config: {e}")
            return {}

    def update_back_conf_api_type(self, api_type: int) -> dict[str, Any]:
        """更新后台类型配置
        Args:
            api_type: API类型，1=MusicFree插件，2=LXServer接口
        Returns:
            更新结果字典
        """
        try:
            if os.path.exists(self.plugins_config_path):
                with open(self.plugins_config_path, encoding="utf-8") as f:
                    config_data = json.load(f)

                back_conf_info = config_data.get("back_conf_info", {})
                back_conf_info["api_type"] = api_type
                config_data["back_conf_info"] = back_conf_info

                with open(self.plugins_config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)
                self._invalidate_config_cache()
                return {"success": True}
            else:
                return {"success": False, "error": "Config file not found"}
        except Exception as e:
            self.log.error(f"Failed to update back_conf_api_type: {e}")
            return {"success": False, "error": str(e)}

    """------------------------------LX Server接口相关函数----------------------------------------"""

    def _build_lx_server_headers(
        self, lx_server_info: dict[str, Any]
    ) -> dict[str, str] | None:
        """构建 LX Server 认证头

        Args:
            lx_server_info: LX Server 配置信息

        Returns:
            包含认证信息的请求头，如果未配置则返回 None
        """
        user_name = lx_server_info.get("x-user-name", "")
        user_token = lx_server_info.get("x-user-token", "")
        if user_name and user_token and user_name != "" and user_token != "":
            return {
                "x-user-name": user_name,
                "x-user-token": user_token,
            }
        return None

    async def test_lx_server(self) -> dict[str, Any]:
        """测试lxServer接口
        Returns:
            Dict[str, Any]: 包含 lxServer接口 配置信息的字典，包括启用状态和搜索 URL
        """
        try:
            lx_server_info = self.get_lx_server_info()
            if lx_server_info.get("base_url", "") != "":
                headers = self._build_lx_server_headers(lx_server_info)
                result_data = await self.simple_async_get(
                    url=lx_server_info.get("base_url") + "/music/config",
                    headers=headers,
                )
                if (
                    result_data
                    and "player.enableAuth" in result_data
                    and "user.enablePublicRestriction" in result_data
                ):
                    return {"success": True, "data": "LX Server接口正常！"}
                else:
                    return {
                        "success": False,
                        "error": "不是合法的LX Server接口，请确认后重新配置！",
                    }
            else:
                return {"success": False, "error": "LX Server接口未配置！"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_local_lxserver_user_list(self) -> dict[str, Any]:
        """获取本地的LXServer用户歌单数据

        Returns:
            Dict[str, Any]: 本地缓存的歌单数据
        """
        try:
            lx_server_info = self.get_lx_server_info()
            raw_playlist = lx_server_info.get("music_list_json", "")

            if not raw_playlist:
                return {"success": False, "error": "请先点击「同步LX歌单」获取歌单数据"}

            playlist_data = json.loads(raw_playlist)
            return {"success": True, "data": playlist_data}

        except Exception as e:
            self.log.error(f"获取本地LXServer歌单失败: {e}")
            return {"success": False, "error": str(e)}

    def get_lx_server_info(self) -> dict[str, Any]:
        """获取lxServer接口配置信息
        Returns:
            Dict[str, Any]: 包含 lxServer接口 配置信息的字典，包括启用状态和搜索 URL
        """
        try:
            # 读取配置文件中的 LX Server 配置信息
            config_data = self._get_config_data()
            if config_data:
                # 返回 LX Server_info 配置项
                return config_data.get("lx_server_info", {})
            else:
                return {"enabled": False}
        except Exception as e:
            self.log.error(f"Failed to read LX Server info from config: {e}")
            return {}

    def toggle_openapi(self) -> dict[str, Any]:
        """切换开放接口配置状态"""
        try:
            if os.path.exists(self.plugins_config_path):
                with open(self.plugins_config_path, encoding="utf-8") as f:
                    config_data = json.load(f)

                openapi_info = config_data.get("lx_server_info", {})
                current_enabled = openapi_info.get("enabled", False)
                openapi_info["enabled"] = not current_enabled
                config_data["lx_server_info"] = openapi_info

                with open(self.plugins_config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)
                # 使缓存失效
                self._invalidate_config_cache()
                return {"success": True}
            else:
                return {"success": False}
        except Exception as e:
            self.log.error(f"Failed to toggle OpenAPI config: {e}")
            return {"success": False, "error": str(e)}

    def update_openapi_url(self, openapi_url: str) -> dict[str, Any]:
        """更新开放接口地址"""
        try:
            if os.path.exists(self.plugins_config_path):
                with open(self.plugins_config_path, encoding="utf-8") as f:
                    config_data = json.load(f)

                openapi_info = config_data.get("lx_server_info", {})
                openapi_info["base_url"] = openapi_url
                config_data["lx_server_info"] = openapi_info

                with open(self.plugins_config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)

                # 使缓存失效
                self._invalidate_config_cache()
                return {"success": True}
            else:
                return {"success": False}
        except Exception as e:
            self.log.error(f"Failed to update OpenAPI config: {e}")
            return {"success": False, "error": str(e)}

    def update_lxserver_platforms(self, platforms: dict[str, str]) -> dict[str, Any]:
        """更新LXServer平台配置
        Args:
            platforms: 平台字典，格式 {key: name}，如 {"tx": "QQ音乐"}
        Returns:
            更新结果字典
        """
        try:
            if os.path.exists(self.plugins_config_path):
                with open(self.plugins_config_path, encoding="utf-8") as f:
                    config_data = json.load(f)

                lx_server_info = config_data.get("lx_server_info", {})
                lx_server_info["platforms"] = platforms
                config_data["lx_server_info"] = lx_server_info

                with open(self.plugins_config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)

                self._invalidate_config_cache()
                return {"success": True}
            else:
                return {"success": False, "error": "Config file not found"}
        except Exception as e:
            self.log.error(f"Failed to update LXServer platforms: {e}")
            return {"success": False, "error": str(e)}

    def update_lxserver_auth(self, username: str, token: str) -> dict[str, Any]:
        """更新LXServer认证信息
        Args:
            username: 用户名
            token: 认证Token
        Returns:
            更新结果字典
        """
        try:
            if os.path.exists(self.plugins_config_path):
                with open(self.plugins_config_path, encoding="utf-8") as f:
                    config_data = json.load(f)

                lx_server_info = config_data.get("lx_server_info", {})
                lx_server_info["x-user-name"] = username
                lx_server_info["x-user-token"] = token
                config_data["lx_server_info"] = lx_server_info

                with open(self.plugins_config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)

                self._invalidate_config_cache()

                config_data = self._get_config_data()
                auto_convert = (
                    config_data.get("auto_convert", False) if config_data else False
                )
                if auto_convert and username and token:
                    self.restart_auto_convert()

                return {"success": True}
            else:
                return {"success": False, "error": "Config file not found"}
        except Exception as e:
            self.log.error(f"Failed to update LXServer auth: {e}")
            return {"success": False, "error": str(e)}

    def get_box_play_platform_preference(self) -> str:
        """获取用户配置的口令搜索偏好"""
        try:
            config_data = self._get_config_data()
            if self.is_lx_server():
                lx_server_info = config_data.get("lx_server_info", {})
                return lx_server_info.get("box_play_platform", "all")
            else:
                music_free_info = config_data.get("music_free_info", {})
                return music_free_info.get("box_play_platform", "all")
        except Exception:
            return "all"

    def update_box_play_platform(self, platform: str) -> dict[str, Any]:
        """更新平台偏好设置
        Args:
            platform: 偏好的平台标识，"all"表示聚合搜索
        Returns:
            dict: 更新结果字典
        """
        try:
            if os.path.exists(self.plugins_config_path):
                with open(self.plugins_config_path, encoding="utf-8") as f:
                    config_data = json.load(f)

                if self.is_lx_server():
                    lx_server_info = config_data.get("lx_server_info", {})
                    lx_server_info["box_play_platform"] = platform
                    config_data["lx_server_info"] = lx_server_info
                else:
                    music_free_info = config_data.get("music_free_info", {})
                    music_free_info["box_play_platform"] = platform
                    config_data["music_free_info"] = music_free_info

                with open(self.plugins_config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)

                self._invalidate_config_cache()
                return {"success": True}
            else:
                return {"success": False, "error": "Config file not found"}
        except Exception as e:
            self.log.error(f"Failed to update box play platform: {e}")
            return {"success": False, "error": str(e)}

    def get_plugin_source(self) -> dict[str, Any]:
        """获取插件源配置信息
        Returns:
            Dict[str, Any]: 包含 OpenAPI 配置信息的字典，包括启用状态和搜索 URL
        """
        try:
            # 读取配置文件中的 OpenAPI 配置信息
            config_data = self._get_config_data()
            if config_data:
                # 返回 openapi_info 配置项
                music_free_info = config_data.get("music_free_info", {})
                return music_free_info.get("plugin_source", {})
            else:
                return {"enabled": False}
        except Exception as e:
            self.log.error(f"Failed to read plugin source info from config: {e}")
            return {}

    def refresh_plugin_source(self) -> dict[str, Any]:
        """更新订阅源"""
        try:
            if os.path.exists(self.plugins_config_path):
                with open(self.plugins_config_path, encoding="utf-8") as f:
                    config_data = json.load(f)
                music_free_info = config_data.get("music_free_info", {})
                plugin_source = music_free_info.get("plugin_source", {})
                source_url = plugin_source.get("source_url", "")
                if source_url:
                    import requests

                    # 请求源地址
                    response = requests.get(source_url, timeout=30)
                    response.raise_for_status()  # 抛出HTTP错误
                    # 解析响应JSON
                    json_data = response.json()
                    # 校验响应格式 - 检查是否包含 plugins 数组
                    if not isinstance(json_data, dict) or "plugins" not in json_data:
                        return {"success": False, "error": "无效订阅源！"}
                    plugins_array = json_data["plugins"]
                    if not isinstance(plugins_array, list):
                        return {"success": False, "error": "无效订阅源！"}
                    # 写入插件文本
                    self.download_and_save_plugin(plugins_array)
                    # 使缓存失效
                    self._invalidate_config_cache()
                    self.reload_plugins()
                    return {"success": True}
                else:
                    return {"success": False, "error": "未找到配置订阅源！"}
            else:
                return {"success": False}
        except Exception as e:
            self.log.error(f"Failed to toggle OpenAPI config: {e}")
            return {"success": False, "error": str(e)}

    def download_and_save_plugin(self, plugins_array: list) -> bool:
        """下载并保存插件数组中的所有插件

        Args:
            plugins_array: 插件信息列表，格式如 [{"name": "plugin_name", "url": "plugin_url", "version": "version"}, ...]

        Returns:
            bool: 所有插件下载保存是否全部成功
        """
        if not plugins_array or not isinstance(plugins_array, list):
            self.log.warning("Empty or invalid plugins array provided")
            return False

        all_success = True

        for plugin_info in plugins_array:
            if (
                not isinstance(plugin_info, dict)
                or "name" not in plugin_info
                or "url" not in plugin_info
            ):
                self.log.warning(f"Invalid plugin entry: {plugin_info}")
                all_success = False
                continue

            plugin_name = plugin_info["name"]
            plugin_url = plugin_info["url"]

            if not plugin_name or not plugin_url:
                self.log.warning(f"Invalid plugin entry: {plugin_name} -> {plugin_url}")
                all_success = False
                continue

            # 调用单个插件下载方法
            success = self.download_single_plugin(plugin_name, plugin_url)
            if not success:
                all_success = False
                self.log.error(f"Failed to download plugin: {plugin_name}")

        return all_success

    def download_single_plugin(self, plugin_name: str, plugin_url: str) -> bool:
        """下载并保存单个插件

        Args:
            plugin_name: 插件名称
            plugin_url: 插件下载URL

        Returns:
            bool: 下载保存是否成功
        """
        import requests

        # 检查插件名称是否合法
        sys_files = ["ALL", "all", "OpenAPI", "OPENAPI"]
        if plugin_name in sys_files:
            self.log.error(f"Plugin name {plugin_name} is reserved and cannot be used")
            return False

        # 创建插件目录
        os.makedirs(self.plugins_dir, exist_ok=True)

        # 生成文件路径
        plugin_filename = f"{plugin_name}.js"
        file_path = os.path.join(self.plugins_dir, plugin_filename)

        # 检查是否已存在同名插件
        if os.path.exists(file_path):
            self.log.warning(f"Plugin {plugin_name} already exists, will overwrite")

        try:
            # 下载插件内容
            response = requests.get(plugin_url, timeout=30)
            response.raise_for_status()

            # 验证下载的内容是否为有效的JS代码（简单检查是否以有意义的JS字符开头）
            content = response.text.strip()
            if not content:
                self.log.error(f"Downloaded plugin {plugin_name} has empty content")
                return False

            # 保存插件文件
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            self.log.info(f"Successfully downloaded and saved plugin: {plugin_name}")

            # 更新插件配置
            self.update_plugin_config(plugin_name, plugin_filename)
            return True

        except requests.exceptions.RequestException as e:
            self.log.error(
                f"Failed to download plugin {plugin_name} from {plugin_url}: {e}"
            )
            return False
        except Exception as e:
            self.log.error(f"Failed to save plugin {plugin_name}: {e}")
            return False

    def update_plugin_source_url(self, source_url: str) -> dict[str, Any]:
        """更新开放接口地址"""
        try:
            if os.path.exists(self.plugins_config_path):
                with open(self.plugins_config_path, encoding="utf-8") as f:
                    config_data = json.load(f)

                if "music_free_info" not in config_data:
                    config_data["music_free_info"] = {}
                music_free_info = config_data["music_free_info"]
                plugin_source = music_free_info.get("plugin_source", {})
                plugin_source["source_url"] = source_url
                music_free_info["plugin_source"] = plugin_source
                config_data["music_free_info"] = music_free_info

                with open(self.plugins_config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)

                # 使缓存失效
                self._invalidate_config_cache()
                return {"success": True}
            else:
                return {"success": False}
        except Exception as e:
            self.log.error(f"Failed to update plugin source config: {e}")
            return {"success": False, "error": str(e)}

    """----------------------------------------------------------------------"""

    def _get_config_data(self):
        """获取配置数据，使用缓存机制"""
        current_time = time.time()
        # 检查缓存是否有效
        if (
            self._config_cache is not None
            and current_time - self._config_cache_time < self._config_cache_ttl
        ):
            return self._config_cache

        # 重新读取配置文件
        if os.path.exists(self.plugins_config_path):
            with open(self.plugins_config_path, encoding="utf-8") as f:
                config_data = json.load(f)
        else:
            config_data = {}

        # 更新缓存
        self._config_cache = config_data
        self._config_cache_time = current_time
        return config_data

    def _invalidate_config_cache(self):
        """使配置缓存失效"""
        self._config_cache = None
        self._config_cache_time = 0

    def _merge_config_with_template(self):
        """合并模板配置到当前配置文件"""
        example_config_path = os.path.join(
            os.path.dirname(__file__), "plugins-config-example.json"
        )

        if not os.path.exists(example_config_path):
            self.log.error("找不到 plugins-config-example.json 配置文件！")
            return False

        try:
            with open(example_config_path, encoding="utf-8") as f:
                template_config = json.load(f)

            with open(self.plugins_config_path, encoding="utf-8") as f:
                current_config = json.load(f)

            merged = False
            for key, value in template_config.items():
                if key not in current_config:
                    current_config[key] = value
                    merged = True
                    self.log.info(f"从模板追加配置项: {key}")

            if merged:
                with open(self.plugins_config_path, "w", encoding="utf-8") as f:
                    json.dump(current_config, f, ensure_ascii=False, indent=2)
                self.log.info("配置文件已更新，追加了新的配置项")
            else:
                self.log.debug("配置文件已是最新，无需更新")

            return True
        except Exception as e:
            self.log.error(f"合并配置失败: {e}")
            return False

    def _load_plugins(self):
        """加载所有插件"""
        if not os.path.exists(self.plugins_dir):
            os.makedirs(self.plugins_dir)

        example_config_path = os.path.join(
            os.path.dirname(__file__), "plugins-config-example.json"
        )

        if not os.path.exists(self.plugins_config_path):
            if os.path.exists(example_config_path):
                shutil.copy2(example_config_path, self.plugins_config_path)
                self.log.info(f"从模板复制创建配置文件: {self.plugins_config_path}")
            else:
                self.log.error("找不到 plugins-config-example.json 配置文件！")
        else:
            self._merge_config_with_template()

        self.log.info(f"Plugins directory: {self.plugins_dir}")
        self.log.info(f"Plugins config file: {self.plugins_config_path}")
        # 只加载指定的插件，避免加载所有插件导致超时
        # enabled_plugins = ['kw', 'qq-yuanli']  # 可以根据需要添加更多
        # 读取配置文件配置
        enabled_plugins = self.get_enabled_plugins()
        for filename in os.listdir(self.plugins_dir):
            if filename.endswith(".js"):
                plugin_name = os.path.splitext(filename)[0]
                try:
                    # 如果是重要插件或没有指定重要插件列表，则加载
                    if not enabled_plugins or plugin_name in enabled_plugins:
                        try:
                            self.log.info(f"Loading plugin: {plugin_name}")
                            self.load_plugin(plugin_name)
                        except Exception as e:
                            self.log.error(
                                f"Failed to load important plugin {plugin_name}: {e}"
                            )
                            # 即使加载失败也记录插件信息
                            self.plugins[plugin_name] = {
                                "name": plugin_name,
                                "enabled": False,
                                "loaded": False,
                                "error": str(e),
                            }
                    else:
                        self.log.debug(
                            f"Skipping plugin (not in important list): {plugin_name}"
                        )
                        # 标记为未加载但可用
                        self.plugins[plugin_name] = {
                            "name": plugin_name,
                            "enabled": False,
                            "loaded": False,
                            "error": "Not loaded (not in important plugins list)",
                        }
                except Exception as e:
                    self.log.error(f"Failed to load plugin {filename}: {e}")
                    # 即使加载失败也记录插件信息
                    self.plugins[plugin_name] = {
                        "name": plugin_name,
                        "enabled": False,
                        "loaded": False,
                        "error": str(e),
                    }

    def load_plugin(self, plugin_name: str) -> bool:
        """加载单个插件"""
        plugin_file = os.path.join(self.plugins_dir, f"{plugin_name}.js")

        if not os.path.exists(plugin_file):
            raise FileNotFoundError(f"Plugin file not found: {plugin_file}")

        try:
            with open(plugin_file, encoding="utf-8") as f:
                js_code = f.read()

            response = self._send_message(
                {"action": "load", "name": plugin_name, "code": js_code}
            )

            if response["success"]:
                self.plugins[plugin_name] = {
                    "status": "loaded",
                    "load_time": time.time(),
                    "enabled": True,
                }
                self.log.info(f"Loaded JS plugin: {plugin_name}")
                return True
            else:
                self.log.error(
                    f"Failed to load JS plugin {plugin_name}: {response['error']}"
                )
                return False

        except Exception as e:
            self.log.error(f"Failed to load JS plugin {plugin_name}: {e}")
            return False

    def refresh_plugin_list(self) -> list[dict[str, Any]]:
        """刷新插件列表，强制重新加载配置数据"""
        # 强制使缓存失效，重新加载配置
        self._invalidate_config_cache()
        self.reload_plugins()
        # 返回最新的插件列表
        return self.get_plugin_list()

    def get_plugin_list(self) -> list[dict[str, Any]]:
        """获取启用的插件列表"""
        result = []
        try:
            # 读取配置文件中的启用插件列表
            config_data = self._get_config_data()
            if config_data:
                music_free_info = config_data.get("music_free_info", {})
                plugin_infos = music_free_info.get("plugins_info", [])
                enabled_plugins = music_free_info.get("enabled_plugins", [])

                # 创建一个映射，用于快速查找插件在 enabled_plugins 中的位置
                enabled_order = {name: i for i, name in enumerate(enabled_plugins)}

                # 先按 enabled 属性排序（True 在前）
                # 再按 enabled_plugins 顺序排序（启用的插件才参与此排序）
                def sort_key(plugin_info):
                    name = plugin_info["name"]
                    is_enabled = plugin_info.get("enabled", False)
                    order = (
                        enabled_order.get(name, len(enabled_plugins))
                        if is_enabled
                        else len(enabled_plugins)
                    )
                    # (-is_enabled) 将 True(1) 放到前面，False(0) 放到后面
                    # order 控制启用插件间的相对顺序
                    return -is_enabled, order

                result = sorted(plugin_infos, key=sort_key)
        except Exception as e:
            self.log.error(f"Failed to read enabled plugins from config: {e}")
        return result

    def _get_api_type(self) -> int:
        """获取接口类型：1=mf_plugins，2=lx_server"""
        try:
            config_data = self._get_config_data()
            if config_data:
                back_conf_info = config_data.get("back_conf_info", {})
                return back_conf_info.get("api_type", 1)
            return 1
        except Exception:
            return 1

    def is_lx_server(self, context_info=None) -> bool:
        """判定是否使用lx_server接口"""
        if context_info and isinstance(context_info, dict):
            # 目前判断：有 _raw 就是 LX
            if "_raw" in context_info:
                return True
            # 没有就是MusicFree
            return False
        return self._get_api_type() == 2

    def get_platforms(self) -> dict[Any, Any]:
        """获取音乐平台列表"""
        try:
            self._invalidate_config_cache()
            api_type = self._get_api_type()
            config_data = self._get_config_data()
            if config_data:
                if api_type == 2:
                    lx_server_info = config_data.get("lx_server_info", {})
                    platforms = lx_server_info.get("platforms", {})
                else:
                    music_free_info = config_data.get("music_free_info", {})
                    enabled_plugins = music_free_info.get("enabled_plugins", [])
                    platforms = {plugin: plugin for plugin in enabled_plugins}
                return platforms
            else:
                return {}
        except Exception as e:
            self.log.error(f"Failed to read platforms from config: {e}")
            return {}

    def get_enabled_plugins(self) -> list[str]:
        """获取启用的插件列表"""
        try:
            # 读取配置文件中的启用插件列表
            config_data = self._get_config_data()
            if config_data:
                music_free_info = config_data.get("music_free_info", {})
                enabled_plugins = music_free_info.get("enabled_plugins", [])
                # 追加开放接口名称
                openapi_info = config_data.get("openapi_info", {})
                enabled_openapi = openapi_info.get("enabled", False)
                if enabled_openapi and "OpenAPI" not in enabled_plugins:
                    enabled_plugins.insert(0, "OpenAPI")
                return enabled_plugins
            else:
                return []
        except Exception as e:
            self.log.error(f"Failed to read enabled plugins from config: {e}")
            return []

    def get_auto_add_song(self) -> bool:
        """获取是否启用自动添加歌曲"""
        try:
            # 读取配置文件
            config_data = self._get_config_data()
            if config_data:
                return config_data.get("auto_add_song", False)
            else:
                return False
        except Exception as e:
            self.log.error(f"Failed to read enabled plugins from config: {e}")
            return False

    def search(self, plugin_name: str, keyword: str, page: int = 1, limit: int = 20, type_: str = "music"):
        """搜索音乐/歌单"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.info(
            f"JS Plugin Manager starting search in plugin {plugin_name} for keyword: {keyword}, type: {type_}"
        )
        response = self._send_message(
            {
                "action": "search",
                "pluginName": plugin_name,
                # 把 type_ 参数传给底层 JS
                "params": {"keywords": keyword, "page": page, "limit": limit, "type": type_},
            }
        )

        self.log.debug(
            f"JS Plugin Manager search response: {response}"
        )  # 使用 debug 级别，减少日志量

        if not response["success"]:
            self.log.error(
                f"JS Plugin Manager search failed in plugin {plugin_name}: {response['error']}"
            )
            # 添加详细的错误信息
            self.log.error(f"JS Plugin Manager full error response: {response}")
            raise Exception(f"Search failed: {response['error']}")
        else:
            # 检查返回的数据结构
            result_data = response["result"]
            self.log.debug(
                f"JS Plugin Manager search raw result: {result_data}"
            )  # 使用 debug 级别
            data_list = result_data.get("data", [])
            is_end = result_data.get("isEnd", True)
            self.log.info(
                f"JS Plugin Manager search completed in plugin {plugin_name}, isEnd: {is_end}, found {len(data_list)} results"
            )
            # 检查数据类型是否正确
            if not isinstance(data_list, list):
                self.log.error(
                    f"JS Plugin Manager search returned invalid data type: {type(data_list)}, value: {data_list}"
                )
            else:
                self.log.debug(
                    f"JS Plugin Manager search data sample: {data_list[:2] if len(data_list) > 0 else 'No results'}"
                )
        return result_data

    async def _http_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        timeout: int = 10,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """统一的异步 HTTP 请求封装

        Args:
            method: HTTP 方法 (GET/POST)
            url: 请求地址
            params: URL 查询参数
            json_data: JSON 请求体
            timeout: 超时时间（秒）
            headers: 自定义请求头

        Returns:
            dict: 包含 success、data/status、error 字段的响应字典
        """
        import aiohttp

        connector = aiohttp.TCPConnector(ssl=False)
        client_timeout = aiohttp.ClientTimeout(total=timeout)

        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                if method.upper() == "GET":
                    async with session.get(
                        url, params=params, timeout=client_timeout, headers=headers
                    ) as response:
                        response.raise_for_status()
                        return {
                            "success": True,
                            "status": response.status,
                            "data": await response.json()
                            if "application/json"
                            in response.headers.get("Content-Type", "")
                            else await response.text(),
                        }
                else:
                    async with session.post(
                        url, json=json_data, timeout=client_timeout, headers=headers
                    ) as response:
                        response.raise_for_status()
                        return {
                            "success": True,
                            "status": response.status,
                            "data": await response.json(),
                        }

        except aiohttp.ClientResponseError as e:
            self.log.error(f"HTTP Error at {url}: {e.status} {e.message}")
            return {"success": False, "error": f"HTTP {e.status}: {e.message}"}
        except asyncio.TimeoutError:
            self.log.error(f"Request timeout at {url}")
            return {"success": False, "error": "Request timeout"}
        except Exception as e:
            self.log.error(f"Request error at {url}: {str(e)}")
            return {"success": False, "error": str(e)}

    async def simple_async_get(self, url: str, headers: dict[str, str] | None = None):
        """基础的异步 GET 请求封装

        Args:
            url (str): 请求地址
            headers (dict): 自定义请求头

        Returns:
            Any: 如果响应是 JSON 则返回 dict/list，否则返回响应文本字符串。
        """
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=10)
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    url, timeout=timeout, headers=headers
                ) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("Content-Type", "")
                    if "application/json" in content_type:
                        return await response.json()
                    else:
                        return await response.text()

        except aiohttp.ClientResponseError as e:
            self.log.error(f"HTTP Error occurred at {url}: {e.status} {e.message}")
            raise
        except aiohttp.ClientError as e:
            self.log.error(f"Client Error occurred at {url}: {str(e)}")
            raise
        except Exception as e:
            self.log.error(f"Unexpected error occurred at {url}: {str(e)}")

    def _format_lx_songs(self, raw_songs: list, source: str) -> list:
        """将 LX Server 返回的原始歌曲列表统一转换为前端标准格式"""
        if not isinstance(raw_songs, list):
            return []
        return [
            {
                "_raw": item,
                "id": item.get("songmid", ""),
                "title": item.get("name", ""),
                "duration": item.get("interval", ""),
                "artist": item.get("singer", ""),
                "album": item.get("albumName", ""),
                "platform": source,
                "artwork": item.get("img", ""),
                "lrc": item.get("lrc", ""),
                "lrcUrl": item.get("lrcUrl", ""),
            }
            for item in raw_songs
        ]

    async def lx_server_search(
        self,
        url: str,
        keyword: str,
        artist: str,
        source: str = "tx",
        limit: int = 20,
        page: int = 1,
        lx_server_info: dict[str, Any] | None = None,
    ):
        """直接调用LX Server接口进行音乐搜索

        Args:
            source (str): 搜索平台code,默认为tx
            url (str): 在线搜索接口地址
            keyword (str): 搜索关键词，歌名/歌手名
            artist (str): 搜索的歌手名，可能为空
            limit (int): 每页数量，默认为20
            page (int): 页码，默认为1
            lx_server_info (dict): LX Server 配置信息
        Returns:
            Dict[str, Any]: 搜索结果，数据结构与search函数一致
        """
        params = {"source": source, "name": keyword, "limit": limit, "page": page}
        self.log.info(f"Calling LX Server API: {url} with params: {params}")
        headers = (
            self._build_lx_server_headers(lx_server_info) if lx_server_info else None
        )

        result = await self._http_request("GET", url, params=params, headers=headers)
        if not result["success"]:
            return {
                "success": False,
                "error": result["error"],
                "data": [],
                "total": 0,
                "page": page,
                "limit": limit,
            }

        raw_data = result["data"]
        self.log.info(f"LX Server接口 - {source} 返回原始Json: {raw_data}")

        if not isinstance(raw_data, list):
            return {
                "success": False,
                "error": f"API request failed: {raw_data}",
                "data": [],
                "total": 0,
                "page": page,
                "limit": limit,
            }

        # LX格式转换成XiaoMusic格式
        converted_data = self._format_lx_songs(raw_data, source)

        unified_result = {"data": converted_data}
        optimized_result = self.optimize_search_results(
            unified_result, search_keyword=keyword, limit=limit, search_artist=artist
        )
        results = optimized_result.get("data", [])

        return {
            "success": True,
            "data": results,
            "total": len(results),
            "page": page,
            "limit": limit,
        }

    async def lx_server_playlist_search(
        self,
        url: str,
        keyword: str,
        source: str = "tx",
        limit: int = 20,
        page: int = 1,
        lx_server_info: dict[str, Any] | None = None,
    ):
        """直接调用 LX Server 接口进行歌单搜索

        Args:
            url (str): 歌单搜索接口地址
            keyword (str): 搜索关键词
            source (str): 搜索平台 code
            limit (int): 每页数量
            page (int): 页码
            lx_server_info (dict): LX Server 配置信息
        Returns:
            Dict[str, Any]: 歌单搜索结果列表
        """
        # 将前端传来的 keyword 转换为 LX 认识的 text
        params = {"source": source, "text": keyword, "limit": limit, "page": page}
        self.log.info(f"正在向 LX Server 请求歌单搜索: {url} 参数: {params}")

        # 复用现成的认证头构建逻辑
        headers = (
            self._build_lx_server_headers(lx_server_info) if lx_server_info else None
        )

        # 发起 HTTP GET 请求
        result = await self._http_request("GET", url, params=params, headers=headers)

        if not result["success"]:
            return {"success": False, "error": result["error"], "list": [], "total": 0}

        # 直接透传 LX Server 返回的原始 JSON 结构
        return result["data"]

    async def lx_server_playlist_detail(
        self,
        url: str,
        id: str,
        source: str,
        lx_server_info: dict[str, Any] | None = None,
    ):
        """直接调用 LX Server 接口获取歌单详情（全量歌曲）"""
        params = {"source": source, "id": id}
        self.log.info(f"正在向 LX Server 请求歌单详情: {url} 参数: {params}")

        headers = (
            self._build_lx_server_headers(lx_server_info) if lx_server_info else None
        )

        result = await self._http_request("GET", url, params=params, headers=headers)
        if not result["success"]:
            return {"success": False, "error": result["error"], "data": [], "total": 0}

        raw_data = result["data"]

        # 柔性脱壳并转换为标准格式
        actual_songs = (
            raw_data.get("list", []) if isinstance(raw_data, dict) else raw_data
        )

        # LX格式转换成XiaoMusic格式
        converted_data = self._format_lx_songs(actual_songs, source)

        return {"success": True, "data": converted_data, "total": len(converted_data)}

    async def lx_server_music_url(
        self,
        url: str,
        song_info: dict[str, Any],
        quality: str = "320k",
        lx_server_info: dict[str, Any] | None = None,
    ):
        """直接调用LX Server接口获取音乐URL

        Args:
            url (str): 在线搜索接口地址
            song_info (dict[str, Any]): 歌曲信息
            quality (str): 音质，默认为320k
            lx_server_info (dict): LX Server 配置信息

        Returns:
            Dict[str, Any]: 包含音乐URL的响应
        """
        json_data = {"songInfo": song_info, "quality": quality}
        headers = (
            self._build_lx_server_headers(lx_server_info) if lx_server_info else None
        )
        result = await self._http_request(
            "POST", url, json_data=json_data, headers=headers
        )

        if not result["success"]:
            return {"success": False, "error": result["error"], "data": {}}

        raw_data = result["data"]
        self.log.info(f"LX Server接口返回原始Json: {raw_data}")

        if not isinstance(raw_data, dict):
            return {
                "success": False,
                "error": f"API request failed: {raw_data}",
                "data": {},
            }
        return raw_data

    async def lx_server_music_lyric(
        self,
        url: str,
        song_info: dict[str, Any],
        lx_server_info: dict[str, Any] | None = None,
    ):
        """直接调用 LX Server 接口获取歌词

        Args:
            url (str): 在线搜索接口地址
            song_info (dict[str, Any]): 歌曲信息字典，包含 source、songmid、name 等字段
            lx_server_info (dict): LX Server 配置信息

        Returns:
            Dict[str, Any]: 歌词数据
        """
        params = {**song_info}
        params.pop("types", None)
        params.pop("_types", None)
        params = {
            k: v
            for k, v in params.items()
            if v is not None and not (isinstance(v, (dict, list)) and not v)
        }

        self.log.info(f"LX Server 歌词接口请求参数：{params}")
        headers = (
            self._build_lx_server_headers(lx_server_info) if lx_server_info else None
        )

        result = await self._http_request("GET", url, params=params, headers=headers)
        if not result["success"]:
            return {"success": False, "error": result["error"], "data": {}}

        raw_data = result["data"]
        self.log.info(f"LX Server 接口返回原始 Json: {raw_data}")

        if not isinstance(raw_data, dict):
            return {
                "success": False,
                "error": f"API request failed: {raw_data}",
                "data": {},
            }

        if "lyric" in raw_data:
            raw_data["rawLrc"] = raw_data.pop("lyric")
            raw_data["success"] = True
            return raw_data
        else:
            return {"success": False, "error": "Lyric field not found in response"}

    async def lx_server_user_list(
        self,
        lx_server_info: dict[str, Any] | None = None,
    ):
        """直接调用 LX Server 接口获取用户歌单

        Args:
            lx_server_info (dict): LX Server 配置信息

        Returns:
            Dict[str, Any]: 用户歌单数据，包含 defaultList、loveList、userList
        """
        if not lx_server_info or not lx_server_info.get("base_url"):
            return {"success": False, "error": "LX Server未配置"}

        headers = self._build_lx_server_headers(lx_server_info)
        if not headers:
            return {"success": False, "error": "LX Server认证信息未配置"}

        url = lx_server_info.get("base_url") + "/user/list"
        self.log.info(f"Calling LX Server user list API: {url}")

        result = await self._http_request("GET", url, headers=headers)
        if not result["success"]:
            return {"success": False, "error": result["error"]}

        raw_data = result["data"]
        self.log.info(f"LX Server 用户歌单返回原始Json: {raw_data}")

        if not isinstance(raw_data, dict):
            return {"success": False, "error": f"API request failed: {raw_data}"}

        return {"success": True, "data": raw_data}

    async def pull_lxserver_playlist(self) -> dict[str, Any]:
        """拉取LXServer用户歌单到plugins-config.json

        Returns:
            Dict[str, Any]: 同步结果
        """
        try:
            lx_server_info = self.get_lx_server_info()
            if not lx_server_info.get("base_url"):
                return {"success": False, "error": "LX Server未配置"}

            headers = self._build_lx_server_headers(lx_server_info)
            if not headers:
                return {"success": False, "error": "LX Server认证信息未配置"}

            url = lx_server_info.get("base_url") + "/user/list"
            self.log.info(f"同步LXServer歌单: {url}")

            result = await self._http_request("GET", url, headers=headers)
            if not result["success"]:
                return {"success": False, "error": result["error"]}

            playlist_data = result["data"]
            if not isinstance(playlist_data, dict):
                return {
                    "success": False,
                    "error": f"API request failed: {playlist_data}",
                }

            love_list = playlist_data.get("loveList")
            if love_list is None or (
                isinstance(love_list, list) and len(love_list) == 0
            ):
                playlist_data.pop("loveList", None)

            default_list = playlist_data.get("defaultList")
            if default_list is None or (
                isinstance(default_list, list) and len(default_list) == 0
            ):
                playlist_data.pop("defaultList", None)

            if "userList" in playlist_data:
                filtered_user_list = []
                for lst in playlist_data["userList"]:
                    song_list = (
                        lst.get("list")
                        or lst.get("musicList")
                        or lst.get("songs")
                        or []
                    )
                    song_count = len(song_list) if isinstance(song_list, list) else 0
                    lst["songCount"] = song_count
                    if song_count > 0:
                        filtered_user_list.append(lst)
                    else:
                        self.log.info(
                            f"过滤空歌单: {lst.get('name', 'unknown')}, 歌曲数量: {song_count}"
                        )
                playlist_data["userList"] = filtered_user_list

            if not os.path.exists(self.plugins_config_path):
                return {"success": False, "error": "配置文件不存在"}

            with open(self.plugins_config_path, encoding="utf-8") as f:
                config_data = json.load(f)

            lx_server_info["music_list_json"] = json.dumps(
                playlist_data, ensure_ascii=False
            )
            config_data["lx_server_info"] = lx_server_info

            with open(self.plugins_config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)

            self._invalidate_config_cache()

            synced_count = 0
            log_parts = []
            if playlist_data.get("loveList"):
                synced_count += 1
                love_count = len(playlist_data.get("loveList", []))
                log_parts.append(f"我喜欢的音乐({love_count}首)")
            if playlist_data.get("defaultList"):
                synced_count += 1
                default_count = len(playlist_data.get("defaultList", []))
                log_parts.append(f"默认歌单({default_count}首)")
            if playlist_data.get("userList"):
                user_lists = playlist_data.get("userList", [])
                synced_count += len(user_lists)
                for lst in user_lists:
                    song_list = (
                        lst.get("list")
                        or lst.get("musicList")
                        or lst.get("songs")
                        or []
                    )
                    song_count = len(song_list) if isinstance(song_list, list) else 0
                    log_parts.append(f"{lst.get('name', 'unknown')}({song_count}首)")

            self.log.info(
                f"LXServer歌单拉取完成，共 {synced_count} 个歌单: {', '.join(log_parts)}"
            )
            return {
                "success": True,
                "message": f"拉取成功，共 {synced_count} 个歌单",
            }

        except Exception as e:
            self.log.error(f"拉取LXServer歌单失败: {e}")
            return {"success": False, "error": str(e)}

    def convert_lxserver_playlist(
        self, target_playlists: list[str] | None = None
    ) -> dict[str, Any]:
        """将LXServer歌单转换为xiaomusic格式并保存到setting.json

        Args:
            target_playlists: 指定要转换的歌单名称列表，为None时全量转换。
                              可选值：我喜欢的音乐、默认歌单、或userList中的歌单名称

        Returns:
            Dict[str, Any]: 转换结果
        """
        try:
            lx_server_info = self.get_lx_server_info()
            raw_playlist = lx_server_info.get("music_list_json", "")

            if not raw_playlist:
                return {"success": False, "error": "请先点击「同步LX歌单」获取歌单数据"}

            playlist_data = json.loads(raw_playlist)

            setting_path = os.path.join(self.xiaomusic.config.conf_path, "setting.json")
            if not os.path.exists(setting_path):
                return {"success": False, "error": "setting.json配置文件不存在"}

            with open(setting_path, encoding="utf-8") as f:
                setting_data = json.load(f)

            music_list_json = setting_data.get("music_list_json", "")
            if music_list_json:
                try:
                    music_lists = json.loads(music_list_json)
                except json.JSONDecodeError:
                    music_lists = []
            else:
                music_lists = []

            music_lists = [
                lst for lst in music_lists if not lst["name"].startswith("_online_lx_")
            ]

            converted_count = 0

            def should_convert(name: str) -> bool:
                if target_playlists is None:
                    return True
                return name in target_playlists

            love_list = playlist_data.get("loveList", [])
            if love_list and should_convert("我喜欢的音乐"):
                list_name = "_online_lx_我喜欢的音乐"
                musics = self._convert_lxserver_songs(love_list, "我喜欢的音乐")
                music_lists.append({"name": list_name, "musics": musics})
                converted_count += 1

            default_list = playlist_data.get("defaultList", [])
            if default_list and should_convert("默认歌单"):
                list_name = "_online_lx_默认歌单"
                musics = self._convert_lxserver_songs(default_list, "默认歌单")
                music_lists.append({"name": list_name, "musics": musics})
                converted_count += 1

            user_lists = playlist_data.get("userList", [])
            for user_list in user_lists:
                list_name = user_list.get("name", "")
                if not list_name:
                    continue
                if should_convert(list_name):
                    full_name = f"_online_lx_{list_name}"
                    songs = user_list.get("list", [])
                    musics = self._convert_lxserver_songs(songs, list_name)
                    music_lists.append({"name": full_name, "musics": musics})
                    converted_count += 1

            setting_data["music_list_json"] = json.dumps(
                music_lists, ensure_ascii=False
            )

            with open(setting_path, "w", encoding="utf-8") as f:
                json.dump(setting_data, f, ensure_ascii=False, indent=2)

            self.xiaomusic.config.music_list_json = setting_data["music_list_json"]

            if self.xiaomusic and hasattr(self.xiaomusic, "music_library"):
                self.xiaomusic.music_library.gen_all_music_list()

            convert_type = "全量" if target_playlists is None else "指定"
            self.log.info(
                f"LXServer歌单{convert_type}转换完成，共转换 {converted_count} 个歌单"
            )
            return {
                "success": True,
                "message": f"LXServer歌单{convert_type}转换完成，共转换 {converted_count} 个歌单",
                "converted_count": converted_count,
                "target_playlists": target_playlists,
            }

        except Exception as e:
            self.log.error(f"转换LXServer歌单失败: {e}")
            return {"success": False, "error": str(e)}

    async def _auto_convert_loop(self):
        """自动转换定时任务循环"""
        while True:
            await asyncio.sleep(self._auto_convert_interval)
            try:
                config_data = self._get_config_data()
                auto_convert = (
                    config_data.get("auto_convert", False) if config_data else False
                )

                if not auto_convert:
                    self.log.info("自动转换已关闭，停止定时任务")
                    break

                lx_server_info = self.get_lx_server_info()
                user_name = lx_server_info.get("x-user-name", "")
                user_token = lx_server_info.get("x-user-token", "")

                if not user_name or not user_token:
                    self.log.debug("LXServer认证信息未配置，跳过本次同步")
                    continue

                self.log.info("开始自动同步LXServer歌单...")
                pull_result = await self.pull_lxserver_playlist()
                if not pull_result.get("success"):
                    self.log.warning(f"自动拉取歌单失败: {pull_result.get('error')}")
                    continue

                self.log.info("开始自动转换歌单...")
                convert_result = self.convert_lxserver_playlist()
                if convert_result.get("success"):
                    self.log.info("自动转换完成")
                else:
                    self.log.warning(f"自动转换失败: {convert_result.get('error')}")

            except asyncio.CancelledError:
                self.log.info("自动转换任务已取消")
                raise
            except Exception as e:
                self.log.error(f"自动转换任务异常: {e}")

    def start_auto_convert(self):
        """启动自动转换定时任务"""
        if self._auto_convert_task is not None and not self._auto_convert_task.done():
            self.log.info("自动转换任务已在运行中")
            return

        config_data = self._get_config_data()
        auto_convert = config_data.get("auto_convert", False) if config_data else False

        if not auto_convert:
            self.log.info("自动转换未启用，不启动定时任务")
            return

        lx_server_info = self.get_lx_server_info()
        user_name = lx_server_info.get("x-user-name", "")
        user_token = lx_server_info.get("x-user-token", "")

        if not user_name or not user_token:
            self.log.info("LXServer认证信息未配置，不启动定时任务")
            return

        self.log.info("启动自动转换定时任务，每30秒拉取一次")
        self._auto_convert_task = asyncio.create_task(self._auto_convert_loop())

    def stop_auto_convert(self):
        """停止自动转换定时任务"""
        if self._auto_convert_task is not None and not self._auto_convert_task.done():
            self._auto_convert_task.cancel()
            self.log.info("已停止自动转换定时任务")

    def restart_auto_convert(self):
        """重启自动转换定时任务"""
        self.stop_auto_convert()
        self.start_auto_convert()

    def delete_lxserver_playlists(
        self, delete_list: list[str], user_list_indexes: list[int]
    ) -> dict[str, Any]:
        """删除LXServer歌单

        Args:
            delete_list: 要删除的歌单类型列表，如 ["loveList", "defaultList"]
            user_list_indexes: 要删除的用户歌单索引列表

        Returns:
            Dict[str, Any]: 删除结果
        """
        try:
            if not os.path.exists(self.plugins_config_path):
                return {"success": False, "error": "配置文件不存在"}

            with open(self.plugins_config_path, encoding="utf-8") as f:
                config_data = json.load(f)

            lx_server_info = config_data.get("lx_server_info", {})
            raw_playlist = lx_server_info.get("music_list_json", "")

            if not raw_playlist:
                return {"success": False, "error": "没有可删除的歌单数据"}

            playlist_data = json.loads(raw_playlist)
            deleted_count = 0

            if "loveList" in delete_list:
                playlist_data.pop("loveList", None)
                deleted_count += 1

            if "defaultList" in delete_list:
                playlist_data.pop("defaultList", None)
                deleted_count += 1

            if user_list_indexes and "userList" in playlist_data:
                user_lists = playlist_data["userList"]
                for index in sorted(user_list_indexes, reverse=True):
                    if 0 <= index < len(user_lists):
                        user_lists.pop(index)
                        deleted_count += 1

            lx_server_info["music_list_json"] = json.dumps(
                playlist_data, ensure_ascii=False
            )
            config_data["lx_server_info"] = lx_server_info

            with open(self.plugins_config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)

            self._invalidate_config_cache()

            self.log.info(f"LXServer歌单删除完成，共删除 {deleted_count} 个歌单")
            return {
                "success": True,
                "message": f"删除成功，共删除 {deleted_count} 个歌单",
            }

        except Exception as e:
            self.log.error(f"删除LXServer歌单失败: {e}")
            return {"success": False, "error": str(e)}

    def clear_xiaomusic_playlists(self) -> dict[str, Any]:
        """清空xiaomusic中所有_online_lx_前缀的歌单

        Returns:
            Dict[str, Any]: 清空结果
        """
        try:
            setting_path = os.path.join(self.xiaomusic.config.conf_path, "setting.json")
            if not os.path.exists(setting_path):
                return {"success": False, "error": "setting.json配置文件不存在"}

            with open(setting_path, encoding="utf-8") as f:
                setting_data = json.load(f)

            music_list_json = setting_data.get("music_list_json", "")
            if music_list_json:
                try:
                    music_lists = json.loads(music_list_json)
                except json.JSONDecodeError:
                    music_lists = []
            else:
                music_lists = []

            original_count = len(
                [lst for lst in music_lists if lst["name"].startswith("_online_lx_")]
            )
            music_lists = [
                lst for lst in music_lists if not lst["name"].startswith("_online_lx_")
            ]

            setting_data["music_list_json"] = json.dumps(
                music_lists, ensure_ascii=False
            )

            if "devices" in setting_data:
                for device_did, device_info in setting_data["devices"].items():
                    if "playlist2music" in device_info:
                        playlist2music = device_info["playlist2music"]
                        keys_to_remove = [
                            key
                            for key in playlist2music
                            if key.startswith("_online_lx_")
                        ]
                        for key in keys_to_remove:
                            del playlist2music[key]
                        if device_info.get("cur_playlist", "").startswith(
                            "_online_lx_"
                        ):
                            device_info["cur_playlist"] = ""
                            device_info["cur_music"] = ""

            with open(setting_path, "w", encoding="utf-8") as f:
                json.dump(setting_data, f, ensure_ascii=False, indent=2)

            self.xiaomusic.config.music_list_json = setting_data["music_list_json"]

            if self.xiaomusic and hasattr(self.xiaomusic, "music_library"):
                self.xiaomusic.music_library.gen_all_music_list()

            self.log.info(f"清空xiaomusic歌单完成，共清空 {original_count} 个歌单")
            return {
                "success": True,
                "message": f"清空成功，共清空 {original_count} 个歌单",
            }

        except Exception as e:
            self.log.error(f"清空xiaomusic歌单失败: {e}")
            return {"success": False, "error": str(e)}

    def _convert_lxserver_songs(self, songs: list[dict], list_name: str) -> list[dict]:
        """将LXServer歌曲格式转换为xiaomusic在线歌单格式

        Args:
            songs: LXServer歌曲列表
            list_name: 歌单名称（用于日志）

        Returns:
            list: 转换后的歌曲列表
        """
        import base64
        import json as json_module

        converted = []
        for song in songs:
            try:
                meta = song.get("meta", {})
                source = song.get("source", "")
                name = song.get("name", "")
                singer = song.get("singer", "")
                interval = song.get("interval", "")
                albumId = song.get("albumId", "") or meta.get("albumId", "")
                albumName = song.get("albumName", "") or meta.get("albumName", "")
                copyrightId = song.get("copyrightId", "") or meta.get("copyrightId", "")
                img = (
                    song.get("img", "") or meta.get("picUrl", "") or meta.get("img", "")
                )

                # 改成获取内层的songId。tx的内层是id
                songmid = meta.get("songId", "") or meta.get("id", "")

                types = song.get("types", []) or meta.get("qualitys", []) or []
                _types = song.get("_types", {}) or meta.get("_qualitys", {}) or {}

                if not name:
                    continue

                raw_info = {
                    "singer": singer,
                    "name": name,
                    "albumName": albumName,
                    "albumId": albumId,
                    "songmid": songmid,
                    "copyrightId": copyrightId,
                    "source": source,
                    "interval": interval,
                    "img": img,
                    "lrc": None,
                    "lrcUrl": "",
                    "types": types,
                    "_types": _types,
                    "typeUrl": {},
                }

                #  kg还需要加hash
                song_hash = meta.get("hash", "")
                if song_hash:
                    raw_info["hash"] = song_hash

                song_info = {
                    "_raw": raw_info,
                    "id": songmid,
                    "title": name,
                    "duration": interval,
                    "artist": singer,
                    "album": albumName,
                    "platform": source,
                    "artwork": img,
                }

                origin_data = json_module.dumps(song_info, ensure_ascii=False)
                datab64 = base64.b64encode(origin_data.encode("utf-8")).decode("utf-8")
                proxy_url = f"self:///api/proxy/plugin-url?data={datab64}"

                converted.append(
                    {
                        "url": proxy_url,
                        "name": f"{name}-{singer}" if singer else name,
                        "type": "music",
                    }
                )
            except Exception as e:
                self.log.warning(
                    f"转换歌曲失败: {song.get('name', 'unknown')}, error: {e}"
                )
                continue

        self.log.info(f"歌单 [{list_name}] 转换完成，共 {len(converted)} 首歌曲")
        return converted

    def optimize_search_results(
        self,
        result_data: dict[str, Any],  # 搜索结果数据，字典类型，包含任意类型的值
        search_keyword: str = "",  # 搜索关键词，默认为空字符串
        search_artist: str = "",  # 搜索歌手名，默认为空字符串
        limit: int = 1,  # 返回结果数量限制，默认为1
    ) -> dict[str, Any]:  # 返回优化后的搜索结果，字典类型，包含任意类型的值
        """
        优化搜索结果，根据关键词、歌手名和平台权重对结果进行排序
        参数:
            result_data: 原始搜索结果数据
            search_keyword: 搜索的关键词
            search_artist: 搜索的歌手名
            limit: 返回结果的最大数量
        返回:
            优化后的搜索结果数据，已根据匹配度和平台权重排序
        """
        if not result_data or "data" not in result_data or not result_data["data"]:
            return result_data

        # 清理搜索关键词和歌手名，去除首尾空格
        search_keyword = search_keyword.strip()
        search_artist = search_artist.strip()

        # 如果关键词和歌手名都为空，则不进行排序
        if not search_keyword and not search_artist:
            return result_data  # 两者都空才不排序

        # 获取待处理的数据列表
        data_list = result_data["data"]
        # 预计算平台权重，启用插件列表中的前9个插件有权重，排名越靠前权重越高
        enabled_plugins = self.get_enabled_plugins()
        plugin_weights = {p: 9 - i for i, p in enumerate(enabled_plugins[:9])}

        def calculate_match_score(item):
            """
            计算单个搜索结果的匹配分数
            参数:
                item: 单个搜索结果项
            返回:
                匹配分数，包含标题匹配分、艺术家匹配分和平台加分
            """
            # 获取并标准化标题、艺术家和平台信息
            title = item.get("title", "").lower()
            artist = item.get("artist", "").lower()
            platform = item.get("platform", "")

            # 标准化搜索关键词和艺术家名
            kw = search_keyword.lower()
            ar = search_artist.lower()

            # 歌名匹配分
            title_score = 0
            if kw:
                if kw == title:
                    title_score = 400
                elif title.startswith(kw):
                    title_score = 300
                elif kw in title:
                    title_score = 200

            # 歌手匹配分
            artist_score = 0
            if ar:
                if ar == artist:
                    artist_score = 1000
                elif artist.startswith(ar):
                    artist_score = 800
                elif ar in artist:
                    artist_score = 600
            platform_bonus = plugin_weights.get(platform, 0)
            return title_score + artist_score + platform_bonus

        sorted_data = sorted(data_list, key=calculate_match_score, reverse=True)
        self.log.info(f"排序后列表信息：：{sorted_data}")
        if 0 < limit < len(sorted_data):
            sorted_data = sorted_data[:limit]
        result_data["data"] = sorted_data
        return result_data

    def get_media_source(self, plugin_name: str, music_item: dict[str, Any], quality):
        """获取媒体源"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(
            f"JS Plugin Manager getting media source in plugin {plugin_name} for item: {music_item.get('title', 'unknown')} by {music_item.get('artist', 'unknown')}"
        )
        response = self._send_message(
            {
                "action": "getMediaSource",
                "pluginName": plugin_name,
                "musicItem": music_item,
                "quality": quality,
            }
        )

        if not response["success"]:
            self.log.error(
                f"JS Plugin Manager getMediaSource failed in plugin {plugin_name}: {response['error']}"
            )
            raise Exception(f"getMediaSource failed: {response['error']}")
        else:
            self.log.debug(
                f"JS Plugin Manager getMediaSource completed in plugin {plugin_name}, URL length: {len(response['result'].get('url', '')) if response['result'] else 0}"
            )

        return response["result"]

    def get_lyric(self, plugin_name: str, music_item: dict[str, Any]):
        """获取歌词"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(
            f"JS Plugin Manager getting lyric in plugin {plugin_name} for music: {music_item.get('title', 'unknown')}"
        )
        response = self._send_message(
            {"action": "getLyric", "pluginName": plugin_name, "musicItem": music_item}
        )

        if not response["success"]:
            self.log.error(
                f"JS Plugin Manager getLyric failed in plugin {plugin_name}: {response['error']}"
            )
            raise Exception(f"getLyric failed: {response['error']}")

        return response["result"]

    def get_music_info(self, plugin_name: str, music_item: dict[str, Any]):
        """获取音乐详情"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(
            f"JS Plugin Manager getting music info in plugin {plugin_name} for music: {music_item.get('title', 'unknown')}"
        )
        response = self._send_message(
            {
                "action": "getMusicInfo",
                "pluginName": plugin_name,
                "musicItem": music_item,
            }
        )

        if not response["success"]:
            self.log.error(
                f"JS Plugin Manager getMusicInfo failed in plugin {plugin_name}: {response['error']}"
            )
            raise Exception(f"getMusicInfo failed: {response['error']}")

        return response["result"]

    def get_album_info(
        self, plugin_name: str, album_info: dict[str, Any], page: int = 1
    ):
        """获取专辑详情"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(
            f"JS Plugin Manager getting album info in plugin {plugin_name} for album: {album_info.get('title', 'unknown')}"
        )
        response = self._send_message(
            {
                "action": "getAlbumInfo",
                "pluginName": plugin_name,
                "albumInfo": album_info,
            }
        )

        if not response["success"]:
            self.log.error(
                f"JS Plugin Manager getAlbumInfo failed in plugin {plugin_name}: {response['error']}"
            )
            raise Exception(f"getAlbumInfo failed: {response['error']}")

        return response["result"]

    def get_music_sheet_info(
        self, plugin_name: str, playlist_info: dict[str, Any], page: int = 1
    ):
        """获取歌单详情"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(
            f"JS Plugin Manager getting music sheet info in plugin {plugin_name} for playlist: {playlist_info.get('title', 'unknown')}"
        )
        response = self._send_message(
            {
                "action": "getMusicSheetInfo",
                "pluginName": plugin_name,
                "playlistInfo": playlist_info,
            }
        )

        if not response["success"]:
            self.log.error(
                f"JS Plugin Manager getMusicSheetInfo failed in plugin {plugin_name}: {response['error']}"
            )
            raise Exception(f"getMusicSheetInfo failed: {response['error']}")

        return response["result"]

    def get_artist_works(
        self,
        plugin_name: str,
        artist_item: dict[str, Any],
        page: int = 1,
        type_: str = "music",
    ):
        """获取作者作品"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(
            f"JS Plugin Manager getting artist works in plugin {plugin_name} for artist: {artist_item.get('title', 'unknown')}"
        )
        response = self._send_message(
            {
                "action": "getArtistWorks",
                "pluginName": plugin_name,
                "artistItem": artist_item,
                "page": page,
                "type": type_,
            }
        )

        if not response["success"]:
            self.log.error(
                f"JS Plugin Manager getArtistWorks failed in plugin {plugin_name}: {response['error']}"
            )
            raise Exception(f"getArtistWorks failed: {response['error']}")

        return response["result"]

    def import_music_item(self, plugin_name: str, url_like: str):
        """导入单曲"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(
            f"JS Plugin Manager importing music item in plugin {plugin_name} from: {url_like}"
        )
        response = self._send_message(
            {
                "action": "importMusicItem",
                "pluginName": plugin_name,
                "urlLike": url_like,
            }
        )

        if not response["success"]:
            self.log.error(
                f"JS Plugin Manager importMusicItem failed in plugin {plugin_name}: {response['error']}"
            )
            raise Exception(f"importMusicItem failed: {response['error']}")

        return response["result"]

    def import_music_sheet(self, plugin_name: str, url_like: str):
        """导入歌单"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(
            f"JS Plugin Manager importing music sheet in plugin {plugin_name} from: {url_like}"
        )
        response = self._send_message(
            {
                "action": "importMusicSheet",
                "pluginName": plugin_name,
                "urlLike": url_like,
            }
        )

        if not response["success"]:
            self.log.error(
                f"JS Plugin Manager importMusicSheet failed in plugin {plugin_name}: {response['error']}"
            )
            raise Exception(f"importMusicSheet failed: {response['error']}")

        return response["result"]

    def get_top_lists(self, plugin_name: str):
        """获取榜单列表"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(f"JS Plugin Manager getting top lists in plugin {plugin_name}")
        response = self._send_message(
            {"action": "getTopLists", "pluginName": plugin_name}
        )

        if not response["success"]:
            self.log.error(
                f"JS Plugin Manager getTopLists failed in plugin {plugin_name}: {response['error']}"
            )
            raise Exception(f"getTopLists failed: {response['error']}")

        return response["result"]

    def get_top_list_detail(
        self, plugin_name: str, top_list_item: dict[str, Any], page: int = 1
    ):
        """获取榜单详情"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(
            f"JS Plugin Manager getting top list detail in plugin {plugin_name} for list: {top_list_item.get('title', 'unknown')}"
        )
        response = self._send_message(
            {
                "action": "getTopListDetail",
                "pluginName": plugin_name,
                "topListItem": top_list_item,
                "page": page,
            }
        )

        if not response["success"]:
            self.log.error(
                f"JS Plugin Manager getTopListDetail failed in plugin {plugin_name}: {response['error']}"
            )
            raise Exception(f"getTopListDetail failed: {response['error']}")

        return response["result"]

    # 启用插件
    def enable_plugin(self, plugin_name: str) -> bool:
        if plugin_name in self.plugins:
            self.plugins[plugin_name]["enabled"] = True
            # 读取、修改 插件配置json文件：① 将plugins_info属性中对于的插件状态改为禁用、2：将 enabled_plugins中对应插件移除
            # 同步更新配置文件
            try:
                # 使用自定义的配置文件路径
                config_file_path = self.plugins_config_path

                # 读取现有配置
                if os.path.exists(config_file_path):
                    with open(config_file_path, encoding="utf-8") as f:
                        config_data = json.load(f)

                    # 确保 music_free_info 存在
                    if "music_free_info" not in config_data:
                        config_data["music_free_info"] = {}
                    music_free_info = config_data["music_free_info"]

                    # 更新plugins_info中对应插件的状态
                    plugins_info = music_free_info.get("plugins_info", [])
                    for plugin_info in plugins_info:
                        if plugin_info.get("name") == plugin_name:
                            plugin_info["enabled"] = True

                    # 添加到enabled_plugins中（如果不存在）
                    if "enabled_plugins" not in music_free_info:
                        music_free_info["enabled_plugins"] = []

                    if plugin_name not in music_free_info["enabled_plugins"]:
                        # 追加到list的第一个
                        music_free_info["enabled_plugins"].insert(0, plugin_name)

                    # 更新回 config_data
                    config_data["music_free_info"] = music_free_info

                    # 写回配置文件
                    with open(config_file_path, "w", encoding="utf-8") as f:
                        json.dump(config_data, f, ensure_ascii=False, indent=2)

                    # 清空缓存：
                    self._invalidate_config_cache()
                    self.log.info(
                        f"Plugin config updated for enabled plugin {plugin_name}"
                    )
                    # 更新插件引擎
                    self.reload_plugins()

            except Exception as e:
                self.log.error(
                    f"Failed to update plugin config when enabling {plugin_name}: {e}"
                )
            return True
        return False

    # 禁用插件
    def disable_plugin(self, plugin_name: str) -> bool:
        # 读取、修改 插件配置json文件：① 将plugins_info属性中对于的插件状态改为禁用、2：将 enabled_plugins中对应插件移除
        if plugin_name in self.plugins:
            self.plugins[plugin_name]["enabled"] = False
        # 同步更新配置文件
        try:
            # 使用自定义的配置文件路径
            config_file_path = self.plugins_config_path

            # 读取现有配置
            if os.path.exists(config_file_path):
                with open(config_file_path, encoding="utf-8") as f:
                    config_data = json.load(f)

                # 确保 music_free_info 存在
                if "music_free_info" not in config_data:
                    config_data["music_free_info"] = {}
                music_free_info = config_data["music_free_info"]

                # 更新plugins_info中对应插件的状态
                plugins_info = music_free_info.get("plugins_info", [])
                for plugin_info in plugins_info:
                    if plugin_info.get("name") == plugin_name:
                        plugin_info["enabled"] = False

                # 添加到enabled_plugins中（如果不存在）
                if "enabled_plugins" not in music_free_info:
                    music_free_info["enabled_plugins"] = []

                if plugin_name in music_free_info["enabled_plugins"]:
                    # 移除对应的插件名
                    music_free_info["enabled_plugins"].remove(plugin_name)

                # 更新回 config_data
                config_data["music_free_info"] = music_free_info

                # 写回配置文件
                with open(config_file_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)
                # 清空缓存：
                self._invalidate_config_cache()
                self.log.info(f"Plugin config updated for enabled plugin {plugin_name}")
                # 更新插件引擎
                self.reload_plugins()
        except Exception as e:
            self.log.error(
                f"Failed to update plugin config when enabling {plugin_name}: {e}"
            )
            return False
        return True

    # 卸载插件
    def uninstall_plugin(self, plugin_name: str) -> bool:
        """卸载插件：移除配置信息并删除插件文件"""
        if plugin_name in self.plugins:
            try:
                # 从内存中移除插件
                self.plugins.pop(plugin_name)

                # 使用自定义的配置文件路径
                config_file_path = self.plugins_config_path

                # 读取现有配置
                if os.path.exists(config_file_path):
                    with open(config_file_path, encoding="utf-8") as f:
                        config_data = json.load(f)

                    # 确保 music_free_info 存在
                    if "music_free_info" not in config_data:
                        config_data["music_free_info"] = {}
                    music_free_info = config_data["music_free_info"]

                    # 移除plugins_info属性中对应的插件项目
                    if "plugins_info" in music_free_info:
                        music_free_info["plugins_info"] = [
                            plugin_info
                            for plugin_info in music_free_info["plugins_info"]
                            if plugin_info.get("name") != plugin_name
                        ]

                    # 从enabled_plugins中移除插件（如果存在）
                    if (
                        "enabled_plugins" in music_free_info
                        and plugin_name in music_free_info["enabled_plugins"]
                    ):
                        music_free_info["enabled_plugins"].remove(plugin_name)

                    # 更新回 config_data
                    config_data["music_free_info"] = music_free_info

                    # 回写配置文件
                    with open(config_file_path, "w", encoding="utf-8") as f:
                        json.dump(config_data, f, ensure_ascii=False, indent=2)
                    # 清空缓存：
                    self._invalidate_config_cache()
                    self.log.info(
                        f"Plugin config updated for uninstalled plugin {plugin_name}"
                    )

                # 删除插件文件夹中的指定插件文件
                plugin_file_path = os.path.join(self.plugins_dir, f"{plugin_name}.js")
                if os.path.exists(plugin_file_path):
                    os.remove(plugin_file_path)
                    self.log.info(f"Plugin file removed: {plugin_file_path}")
                else:
                    self.log.warning(f"Plugin file not found: {plugin_file_path}")

                return True
            except Exception as e:
                self.log.error(f"Failed to uninstall plugin {plugin_name}: {e}")
                return False
        return False

    def reload_plugins(self):
        """重新加载所有插件"""
        self.log.info("Reloading all plugins...")
        # 清空现有插件状态
        self.plugins.clear()
        # 重新加载插件
        self._load_plugins()
        self.log.info(f"最新插件信息：{self.plugins}")

    def update_plugin_config(self, plugin_name: str, plugin_file: str):
        """更新插件配置文件"""
        try:
            # 使用自定义的配置文件路径
            config_file_path = self.plugins_config_path
            # 如果配置文件不存在，创建一个基础配置
            if not os.path.exists(config_file_path):
                base_config = {
                    "account": "",
                    "password": "",
                    "music_free_info": {
                        "enabled_plugins": [],
                        "plugins_info": [],
                    },
                }
                with open(config_file_path, "w", encoding="utf-8") as f:
                    json.dump(base_config, f, ensure_ascii=False, indent=2)

            # 读取现有配置
            with open(config_file_path, encoding="utf-8") as f:
                config_data = json.load(f)

            # 确保 music_free_info 存在
            if "music_free_info" not in config_data:
                config_data["music_free_info"] = {}
            music_free_info = config_data["music_free_info"]

            # 检查是否已存在该插件信息
            plugin_exists = False
            for plugin_info in music_free_info.get("plugins_info", []):
                if plugin_info.get("name") == plugin_name:
                    plugin_exists = True
                    break

            # 如果不存在，则添加新的插件信息
            if not plugin_exists:
                new_plugin_info = {
                    "name": plugin_name,
                    "file": plugin_file,
                    "enabled": False,  # 默认不启用
                }
                if "plugins_info" not in music_free_info:
                    music_free_info["plugins_info"] = []
                music_free_info["plugins_info"].append(new_plugin_info)
                # 更新回 config_data
                config_data["music_free_info"] = music_free_info
                # 写回配置文件
                with open(config_file_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)

            self.log.info(f"Plugin config updated for {plugin_name}")

        except Exception as e:
            self.log.error(f"Failed to update plugin config: {e}")

    async def plugin_playlist_search(
            self,
            plugin_name: str,
            keyword: str,
            page: int = 1,
            limit: int = 20,
    ):
        """调用 MusicFree 插件进行歌单搜索，并对齐 LX 格式

        Args:
            plugin_name: 插件名称 (如 qq)
            keyword: 搜索关键词
            page: 页码
            limit: 每页数量
        Returns:
            Dict[str, Any]: 歌单搜索结果，结构对齐 LX Server
        """
        try:
            # 显式传入 type_='sheet' 调用底层插件搜索
            result = self.search(plugin_name, keyword, page, limit, type_='sheet')
            data_list = result.get("data", [])

            # 补齐平台字段
            for item in data_list:
                item["platform"] = plugin_name

                # qq插件是worksNums，统一成worksNum
                if "worksNums" in item:
                    item["worksNum"] = item.pop("worksNums")

            # 组装成对齐 LX Server 的标准结构
            return {
                "success": True,
                "data": {
                    "list": data_list,
                    "total": result.get("total", len(data_list)),
                    "page": page,
                    "limit": limit,
                }
            }
        except Exception as e:
            self.log.error(f"插件 {plugin_name} 歌单搜索执行失败: {e}")
            raise

    async def plugin_playlist_detail(
            self,
            plugin_name: str,
            b64_id: str,
    ):
        """解析 Base64 歌单对象并调用插件获取详情（全量歌曲）

        Args:
            plugin_name: 插件名称
            b64_id: 前端传来的 JSON 对象 Base64 字符串
        Returns:
            Dict[str, Any]: 歌曲列表结果
        """
        try:
            # 1. 容错处理 Base64 损坏
            b64_id = b64_id.replace(' ', '+')
            missing_padding = len(b64_id) % 4
            if missing_padding:
                b64_id += '=' * (4 - missing_padding)

            # 2. 还原完整的 JSON 歌单对象
            json_str = base64.b64decode(b64_id).decode("utf-8")
            playlist_info = json.loads(json_str)

            # 3. 调用插件获取歌曲列表
            result = self.get_music_sheet_info(plugin_name, playlist_info, page=1)

            if not result or not result.get("musicList"):
                return {"success": False, "error": "歌单解析为空或格式不支持", "data": []}

            data_list = result.get("musicList", [])

            # 4. 补齐平台字段，确保后端播歌逻辑能识别来源
            for item in data_list:
                if "platform" not in item:
                    item["platform"] = plugin_name

            return {
                "success": True,
                "data": data_list,
                "total": len(data_list)
            }
        except Exception as e:
            self.log.error(f"插件 {plugin_name} 歌单详情解析执行失败: {e}")
            raise

    def get_voice_playlist_strategy(self) -> str:
        """获取语音搜单的选择策略"""
        try:
            config_data = self._get_config_data()
            strategy_conf = config_data.get("voice_playlist_strategy", "default")
            if isinstance(strategy_conf, dict):
                return strategy_conf.get("value", "default")
            return str(strategy_conf)
        except Exception:
            return "default"

    def pick_best_playlist(self, playlists: list):
        """根据系统配置的策略从歌单列表中挑选一个最优歌单"""
        if not playlists:
            return None
        strategy = self.get_voice_playlist_strategy()
        if strategy == "default" or len(playlists) == 1:
            return playlists[0]
        if strategy == "random":
            return random.choice(playlists)
        # 定义提取权重的辅助闭包
        def get_count(item, keys):
            for k in keys:
                val = item.get(k)
                if val is not None:
                    try:
                        return int(val)
                    except:
                        continue
            return 0
        if strategy == "max_songs":
            return max(playlists,
                       key=lambda x: get_count(x, ["worksNum", "worksNums", "songCount", "song_count", "total"]))
        if strategy == "max_plays":
            return max(playlists, key=lambda x: get_count(x, ["playCount", "play_count"]))
        return playlists[0]

    def reset_restart_limit(self):
        """重置重启限制计数器，允许重新开始重启尝试"""
        self._restart_count = 0
        self._last_restart_time = 0
        self.log.info("Node.js process restart limit has been reset")

    def get_restart_status(self) -> dict[str, Any]:
        """获取重启状态信息"""
        current_time = time.time()
        time_since_last_restart = (
            current_time - self._last_restart_time if self._last_restart_time > 0 else 0
        )
        time_until_reset = max(0, self._restart_window - time_since_last_restart)

        return {
            "restart_count": self._restart_count,
            "max_restarts_in_window": self._max_restarts_in_window,
            "restart_window": self._restart_window,
            "time_since_last_restart": time_since_last_restart,
            "time_until_reset": time_until_reset,
            "can_restart": self._restart_count < self._max_restarts_in_window
            or time_since_last_restart >= self._restart_window,
        }

    def shutdown(self):
        """关闭插件管理器"""
        if self.node_process:
            self.node_process.terminate()
            self.node_process.wait()
