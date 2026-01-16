#!/usr/bin/env python3
"""
JS 插件管理器
负责加载、管理和运行 MusicFree JS 插件
"""

import json
import logging
import os
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

        # ... 配置文件相关 ...
        self._config_cache = None
        self._config_cache_time = 0
        self._config_cache_ttl = 3 * 60  # 缓存有效期5秒，可根据需要调整

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
                    self.log.warning("Node.js process died, restarting...")
                    self._start_node_process()
            time.sleep(5)

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
            if not self.node_process or self.node_process.poll() is not None:
                raise Exception("Node.js process not available")

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

    """------------------------------开放接口相关函数----------------------------------------"""

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
            self.log.error(f"Failed to read OpenAPI info from config: {e}")
            return {}

    def get_openapi_info(self) -> dict[str, Any]:
        """获取开放接口配置信息
        Returns:
            Dict[str, Any]: 包含 OpenAPI 配置信息的字典，包括启用状态和搜索 URL
        """
        try:
            # 读取配置文件中的 OpenAPI 配置信息
            config_data = self._get_config_data()
            if config_data:
                # 返回 openapi_info 配置项
                return config_data.get("openapi_info", {})
            else:
                return {"enabled": False}
        except Exception as e:
            self.log.error(f"Failed to read OpenAPI info from config: {e}")
            return {}

    def toggle_openapi(self) -> dict[str, Any]:
        """切换开放接口配置状态"""
        try:
            if os.path.exists(self.plugins_config_path):
                with open(self.plugins_config_path, encoding="utf-8") as f:
                    config_data = json.load(f)

                openapi_info = config_data.get("openapi_info", {})
                current_enabled = openapi_info.get("enabled", False)
                openapi_info["enabled"] = not current_enabled
                config_data["openapi_info"] = openapi_info

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

                openapi_info = config_data.get("openapi_info", {})
                openapi_info["search_url"] = openapi_url
                config_data["openapi_info"] = openapi_info

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
                return config_data.get("plugin_source", {})
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
                plugin_source = config_data.get("plugin_source", {})
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

                plugin_source = config_data.get("plugin_source", {})
                plugin_source["source_url"] = source_url
                config_data["plugin_source"] = plugin_source

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

    def _load_plugins(self):
        """加载所有插件"""
        if not os.path.exists(self.plugins_dir):
            os.makedirs(self.plugins_dir)

        # 读取、加载插件配置Json
        if not os.path.exists(self.plugins_config_path):
            # 复制 plugins-config-example.json 模板，创建插件配置Json文件
            example_config_path = os.path.join(
                os.path.dirname(__file__), "plugins-config-example.json"
            )
            if os.path.exists(example_config_path):
                shutil.copy2(example_config_path, self.plugins_config_path)
            else:
                base_config = {
                    "account": "",
                    "password": "",
                    "auto_add_song": True,
                    "aiapi_info": {"enabled": False, "api_key": ""},
                    "enabled_plugins": [],
                    "openapi_info": {"enabled": False, "search_url": ""},
                    "plugin_source": {"source_url": ""},
                    "plugins_info": [],
                }
                with open(self.plugins_config_path, "w", encoding="utf-8") as f:
                    json.dump(base_config, f, ensure_ascii=False, indent=2)
        # 输出文件夹、配置文件地址
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
                plugin_infos = config_data.get("plugins_info", [])
                enabled_plugins = config_data.get("enabled_plugins", [])

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

    def get_enabled_plugins(self) -> list[str]:
        """获取启用的插件列表"""
        try:
            # 读取配置文件中的启用插件列表
            config_data = self._get_config_data()
            if config_data:
                enabled_plugins = config_data.get("enabled_plugins", [])
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

    def search(self, plugin_name: str, keyword: str, page: int = 1, limit: int = 20):
        """搜索音乐"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.info(
            f"JS Plugin Manager starting search in plugin {plugin_name} for keyword: {keyword}"
        )
        response = self._send_message(
            {
                "action": "search",
                "pluginName": plugin_name,
                "params": {"keywords": keyword, "page": page, "limit": limit},
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

    async def openapi_search(
        self, url: str, keyword: str, artist: str, limit: int = 20
    ):
        """直接调用在线接口进行音乐搜索

        Args:
            url (str): 在线搜索接口地址
            keyword (str): 搜索关键词，歌名/歌手名
            artist (str): 搜索的歌手名，可能为空
            limit (int): 每页数量，默认为5
        Returns:
            Dict[str, Any]: 搜索结果，数据结构与search函数一致
        """
        import asyncio

        import aiohttp

        try:
            # 构造请求参数
            params = {"type": "aggregateSearch", "keyword": keyword, "limit": limit}
            # 使用aiohttp发起异步HTTP GET请求
            connector = aiohttp.TCPConnector(ssl=False)  # 跳过 SSL 验证
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    response.raise_for_status()  # 抛出HTTP错误
                    # 解析响应数据
                    raw_data = await response.json()

            self.log.info(f"在线接口返回Json: {raw_data}")

            # 检查API调用是否成功
            if raw_data.get("code") != 200:
                raise Exception(
                    f"API request failed with code: {raw_data.get('code', 'unknown')}"
                )

            # 提取实际的搜索结果
            api_data = raw_data.get("data", {})
            results = api_data.get("results", [])

            # 转换数据格式以匹配插件系统的期望格式
            converted_data = []
            for item in results:
                url = item.get("url", "")
                self.log.info(f"openapi_search url: {url}")
                converted_item = {
                    "id": item.get("id", ""),
                    "title": item.get("name", ""),
                    "artist": item.get("artist", ""),
                    "album": item.get("album", ""),
                    "platform": "OpenAPI-" + item.get("platform"),
                    "isOpenAPI": True,
                    "url": url,
                    "artwork": item.get("pic", ""),
                    "lrc": item.get("lrc", ""),
                }
                converted_data.append(converted_item)
            # 排序筛选
            unified_result = {"data": converted_data}
            # 调用优化函数
            optimized_result = self.optimize_search_results(
                unified_result,
                search_keyword=keyword,
                limit=limit,
                search_artist=artist,
            )
            results = optimized_result.get("data", [])
            # 返回统一格式的数据
            return {
                "success": True,
                "isOpenAPI": True,
                "data": results,
                "total": len(results),
                "sources": {"OpenAPI": len(results)},
                "page": 1,
                "limit": limit,
            }

        except asyncio.TimeoutError as e:
            self.log.error(f"OpenAPI search timeout at URL {url}: {e}")
            return {
                "success": False,
                "isOpenAPI": True,
                "error": f"OpenAPI search timeout: {str(e)}",
                "data": [],
                "total": 0,
                "sources": {},
                "page": 1,
                "limit": limit,
            }
        except Exception as e:
            self.log.error(f"OpenAPI search error at URL {url}: {e}")
            return {
                "success": False,
                "isOpenAPI": True,
                "error": f"OpenAPI search error: {str(e)}",
                "data": [],
                "total": 0,
                "sources": {},
                "page": 1,
                "limit": limit,
            }

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
            # 开放接口的平台权重最高 20
            if platform.startswith("OpenAPI-"):
                platform_bonus = 20
            else:
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

                    # 更新plugins_info中对应插件的状态
                    for plugin_info in config_data.get("plugins_info", []):
                        if plugin_info.get("name") == plugin_name:
                            plugin_info["enabled"] = True

                    # 添加到enabled_plugins中（如果不存在）
                    if "enabled_plugins" not in config_data:
                        config_data["enabled_plugins"] = []

                    if plugin_name not in config_data["enabled_plugins"]:
                        # 追加到list的第一个
                        config_data["enabled_plugins"].insert(0, plugin_name)

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

                # 更新plugins_info中对应插件的状态
                for plugin_info in config_data.get("plugins_info", []):
                    if plugin_info.get("name") == plugin_name:
                        plugin_info["enabled"] = False

                # 添加到enabled_plugins中（如果不存在）
                if "enabled_plugins" not in config_data:
                    config_data["enabled_plugins"] = []

                if plugin_name in config_data["enabled_plugins"]:
                    # 移除对应的插件名
                    config_data["enabled_plugins"].remove(plugin_name)

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

                    # 移除plugins_info属性中对应的插件项目
                    if "plugins_info" in config_data:
                        config_data["plugins_info"] = [
                            plugin_info
                            for plugin_info in config_data["plugins_info"]
                            if plugin_info.get("name") != plugin_name
                        ]

                    # 从enabled_plugins中移除插件（如果存在）
                    if (
                        "enabled_plugins" in config_data
                        and plugin_name in config_data["enabled_plugins"]
                    ):
                        config_data["enabled_plugins"].remove(plugin_name)

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
                    "enabled_plugins": [],
                    "plugins_info": [],
                }
                with open(config_file_path, "w", encoding="utf-8") as f:
                    json.dump(base_config, f, ensure_ascii=False, indent=2)

            # 读取现有配置
            with open(config_file_path, encoding="utf-8") as f:
                config_data = json.load(f)

            # 检查是否已存在该插件信息
            plugin_exists = False
            for plugin_info in config_data.get("plugins_info", []):
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
                if "plugins_info" not in config_data:
                    config_data["plugins_info"] = []
                config_data["plugins_info"].append(new_plugin_info)
                # 写回配置文件
                with open(config_file_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)

            self.log.info(f"Plugin config updated for {plugin_name}")

        except Exception as e:
            self.log.error(f"Failed to update plugin config: {e}")

    def shutdown(self):
        """关闭插件管理器"""
        if self.node_process:
            self.node_process.terminate()
            self.node_process.wait()
