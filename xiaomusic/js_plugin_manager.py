#!/usr/bin/env python3
"""
JS 插件管理器
负责加载、管理和运行 MusicFree JS 插件
"""

import json
import logging
import os
import subprocess
import threading
import time
from typing import Dict, Any, List


def optimize_search_results(
        result_data: Dict[str, Any],
        search_keyword: str = ""
) -> Dict[str, Any]:
    """
    优化搜索结果排序函数
    根据歌曲名(title)和专辑名(album)的匹配度进行智能排序
    """
    if not result_data or 'data' not in result_data or not result_data['data']:
        return result_data

    if not search_keyword.strip():
        # 关键词为空或仅空白，无需排序
        return result_data

    data_list: List[Dict[str, Any]] = result_data['data']

    def calculate_match_score(item):
        """计算匹配分数"""
        title = item.get('title', '').lower()
        album = item.get('album', '').lower()
        keyword = search_keyword.lower()

        if not keyword:
            return 0
        score = 0

        # 歌曲名匹配权重(十位数级别: 10-90分)
        if keyword in title:
            # 完全匹配得最高分
            if title == keyword:
                score += 90
            # 开头匹配
            elif title.startswith(keyword):
                score += 70
            # 结尾匹配
            elif title.endswith(keyword):
                score += 50
            # 包含匹配
            else:
                score += 30
        # 部分字符匹配
        elif any(char in title for char in keyword.split()):
            score += 10

        # 专辑名匹配权重(个位数级别: 1-9分)
        if keyword in album:
            # 完全匹配
            if album == keyword:
                score += 9
            # 开头匹配
            elif album.startswith(keyword):
                score += 7
            # 结尾匹配
            elif album.endswith(keyword):
                score += 5
            # 包含匹配
            else:
                score += 3
        # 部分字符匹配
        elif any(char in album for char in keyword.split()):
            score += 1

        return score

    # 排序：高分在前
    sorted_data = sorted(data_list, key=calculate_match_score, reverse=True)
    result_data['data'] = sorted_data

    return result_data


class JSPluginManager:
    """JS 插件管理器"""

    def __init__(self, xiaomusic):
        self.xiaomusic = xiaomusic
        self.log = logging.getLogger(__name__)
        self.plugins_dir = os.path.join(os.path.dirname(__file__), "js_plugins")
        self.plugins = {}  # 插件状态信息
        self.node_process = None
        self.message_queue = []
        self.response_handlers = {}
        self._lock = threading.Lock()
        self.request_id = 0
        self.pending_requests = {}

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
                ['node', '--max-old-space-size=128', runner_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1  # 行缓冲
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
            if self.node_process and self.node_process.poll() is not None:
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
                        self.log.warning(f"Non-JSON output from Node.js process: {line.strip()}, error: {e}")
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
                            self.log.error(f"Node.js process error output: {error_line.strip()}")
                    except Exception as e:
                        self.log.error(f"Error handler error: {e}")
                time.sleep(0.1)

        threading.Thread(target=stdout_handler, daemon=True).start()
        threading.Thread(target=stderr_handler, daemon=True).start()

    def _send_message(self, message: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
        """发送消息到 Node.js 子进程"""
        with self._lock:
            if not self.node_process or self.node_process.poll() is not None:
                raise Exception("Node.js process not available")

            message_id = f"msg_{int(time.time() * 1000)}"
            message['id'] = message_id

            # 记录发送的消息
            self.log.info(f"JS Plugin Manager sending message: {message.get('action', 'unknown')} for plugin: {message.get('pluginName', 'unknown')}")
            if 'params' in message:
                self.log.info(f"JS Plugin Manager search params: {message['params']}")
            elif 'musicItem' in message:
                self.log.info(f"JS Plugin Manager music item: {message['musicItem']}")

            # 发送消息
            self.node_process.stdin.write(json.dumps(message) + '\n')
            self.node_process.stdin.flush()

            # 等待响应
            response = self._wait_for_response(message_id, timeout)
            self.log.info(f"JS Plugin Manager received response for message {message_id}: {response.get('success', 'unknown')}")
            return response

    def _wait_for_response(self, message_id: str, timeout: int) -> Dict[str, Any]:
        """等待特定消息的响应"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if message_id in self.response_handlers:
                response = self.response_handlers.pop(message_id)
                return response
            time.sleep(0.1)

        raise TimeoutError(f"Message {message_id} timeout")

    def _handle_response(self, response: Dict[str, Any]):
        """处理 Node.js 进程的响应"""
        message_id = response.get('id')
        self.log.debug(f"JS Plugin Manager received raw response: {response}")  # 添加原始响应日志

        # 添加更严格的数据验证
        if not isinstance(response, dict):
            self.log.error(f"JS Plugin Manager received invalid response type: {type(response)}, value: {response}")
            return

        if 'id' not in response:
            self.log.error(f"JS Plugin Manager received response without id: {response}")
            return

        # 确保 success 字段存在
        if 'success' not in response:
            self.log.warning(f"JS Plugin Manager received response without success field: {response}")
            response['success'] = False

        # 如果有 result 字段，验证其结构
        if 'result' in response and response['result'] is not None:
            result = response['result']
            if isinstance(result, dict):
                # 对搜索结果进行特殊处理
                if 'data' in result and not isinstance(result['data'], list):
                    self.log.warning(f"JS Plugin Manager received result with invalid data type: {type(result['data'])}, setting to empty list")
                    result['data'] = []

        if message_id:
            self.response_handlers[message_id] = response

    def _load_plugins(self):
        """加载所有插件"""
        if not os.path.exists(self.plugins_dir):
            os.makedirs(self.plugins_dir)
            return

        # 只加载指定的重要插件，避免加载所有插件导致超时
        important_plugins = ['kw', 'qq-yuanli']  # 可以根据需要添加更多
        # TODO 后面改成读取配置文件配置
        # important_plugins = []
        for filename in os.listdir(self.plugins_dir):
            if filename.endswith('.js'):
                try:
                    plugin_name = os.path.splitext(filename)[0]
                    # 如果是重要插件或没有指定重要插件列表，则加载
                    if not important_plugins or plugin_name in important_plugins:
                        try:
                            self.log.info(f"Loading plugin: {plugin_name}")
                            self.load_plugin(plugin_name)
                        except Exception as e:
                            self.log.error(f"Failed to load important plugin {plugin_name}: {e}")
                            # 即使加载失败也记录插件信息
                            self.plugins[plugin_name] = {
                                'name': plugin_name,
                                'enabled': False,
                                'loaded': False,
                                'error': str(e)
                            }
                    else:
                        self.log.debug(f"Skipping plugin (not in important list): {plugin_name}")
                        # 标记为未加载但可用
                        self.plugins[plugin_name] = {
                            'name': plugin_name,
                            'enabled': False,
                            'loaded': False,
                            'error': 'Not loaded (not in important plugins list)'
                        }
                except Exception as e:
                    self.log.error(f"Failed to load plugin {filename}: {e}")
                    # 即使加载失败也记录插件信息
                    self.plugins[plugin_name] = {
                        'name': plugin_name,
                        'enabled': False,
                        'loaded': False,
                        'error': str(e)
                    }

    def load_plugin(self, plugin_name: str) -> bool:
        """加载单个插件"""
        plugin_file = os.path.join(self.plugins_dir, f"{plugin_name}.js")

        if not os.path.exists(plugin_file):
            raise FileNotFoundError(f"Plugin file not found: {plugin_file}")

        try:
            with open(plugin_file, 'r', encoding='utf-8') as f:
                js_code = f.read()

            response = self._send_message({
                'action': 'load',
                'name': plugin_name,
                'code': js_code
            })

            if response['success']:
                self.plugins[plugin_name] = {
                    'status': 'loaded',
                    'load_time': time.time(),
                    'enabled': True
                }
                self.log.info(f"Loaded JS plugin: {plugin_name}")
                return True
            else:
                self.log.error(f"Failed to load JS plugin {plugin_name}: {response['error']}")
                return False

        except Exception as e:
            self.log.error(f"Failed to load JS plugin {plugin_name}: {e}")
            return False

    def get_plugin_list(self) -> List[Dict[str, Any]]:
        """获取插件列表"""
        result = []
        for name, info in self.plugins.items():
            # 确保 info 是字典格式
            if not isinstance(info, dict):
                info = {'name': name, 'enabled': False, 'loaded': False}

            result.append({
                'name': name,
                'status': info.get('status', 'loaded' if info.get('loaded', False) else 'not_loaded'),
                'enabled': info.get('enabled', False),
                'load_time': info.get('load_time'),
                'loaded': info.get('loaded', False),
                'error': info.get('error')
            })
        return result

    def get_enabled_plugins(self) -> List[str]:
        """获取启用的插件列表"""
        return [
            name for name, info in self.plugins.items()
            if info.get('enabled', False) and info.get('status') == 'loaded'
        ]

    def search(self, plugin_name: str, keyword: str, page: int = 1, limit: int = 20):
        """搜索音乐"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.info(f"JS Plugin Manager starting search in plugin {plugin_name} for keyword: {keyword}")
        response = self._send_message({
            'action': 'search',
            'pluginName': plugin_name,
            'params': {
                'keywords': keyword,
                'page': page,
                'limit': limit
            }
        })

        self.log.debug(f"JS Plugin Manager search response: {response}")  # 使用 debug 级别，减少日志量

        if not response['success']:
            self.log.error(f"JS Plugin Manager search failed in plugin {plugin_name}: {response['error']}")
            # 添加详细的错误信息
            self.log.error(f"JS Plugin Manager full error response: {response}")
            raise Exception(f"Search failed: {response['error']}")
        else:
            # 检查返回的数据结构
            result_data = response['result']
            self.log.debug(f"JS Plugin Manager search raw result: {result_data}")  # 使用 debug 级别
            data_list = result_data.get('data', [])
            is_end = result_data.get('isEnd', True)
            self.log.info(f"JS Plugin Manager search completed in plugin {plugin_name}, isEnd: {is_end}, found {len(data_list)} results")
            # 检查数据类型是否正确
            if not isinstance(data_list, list):
                self.log.error(f"JS Plugin Manager search returned invalid data type: {type(data_list)}, value: {data_list}")
            else:
                self.log.debug(f"JS Plugin Manager search data sample: {data_list[:2] if len(data_list) > 0 else 'No results'}")
                # 额外检查 resources 字段
                if data_list:
                    # 优化搜索结果排序后输出
                    result_data = optimize_search_results(result_data, search_keyword=keyword)
        return result_data

    def get_media_source(self, plugin_name: str, music_item: Dict[str, Any]):
        """获取媒体源"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(f"JS Plugin Manager getting media source in plugin {plugin_name} for item: {music_item.get('title', 'unknown')} by {music_item.get('artist', 'unknown')}")
        response = self._send_message({
            'action': 'getMediaSource',
            'pluginName': plugin_name,
            'musicItem': music_item
        })

        if not response['success']:
            self.log.error(f"JS Plugin Manager getMediaSource failed in plugin {plugin_name}: {response['error']}")
            raise Exception(f"getMediaSource failed: {response['error']}")
        else:
            self.log.debug(f"JS Plugin Manager getMediaSource completed in plugin {plugin_name}, URL length: {len(response['result'].get('url', '')) if response['result'] else 0}")

        return response['result']

    def get_lyric(self, plugin_name: str, music_item: Dict[str, Any]):
        """获取歌词"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(f"JS Plugin Manager getting lyric in plugin {plugin_name} for music: {music_item.get('title', 'unknown')}")
        response = self._send_message({
            'action': 'getLyric',
            'pluginName': plugin_name,
            'musicItem': music_item
        })

        if not response['success']:
            self.log.error(f"JS Plugin Manager getLyric failed in plugin {plugin_name}: {response['error']}")
            raise Exception(f"getLyric failed: {response['error']}")

        return response['result']

    def get_music_info(self, plugin_name: str, music_item: Dict[str, Any]):
        """获取音乐详情"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(f"JS Plugin Manager getting music info in plugin {plugin_name} for music: {music_item.get('title', 'unknown')}")
        response = self._send_message({
            'action': 'getMusicInfo',
            'pluginName': plugin_name,
            'musicItem': music_item
        })

        if not response['success']:
            self.log.error(f"JS Plugin Manager getMusicInfo failed in plugin {plugin_name}: {response['error']}")
            raise Exception(f"getMusicInfo failed: {response['error']}")

        return response['result']

    def get_album_info(self, plugin_name: str, album_info: Dict[str, Any], page: int = 1):
        """获取专辑详情"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(f"JS Plugin Manager getting album info in plugin {plugin_name} for album: {album_info.get('title', 'unknown')}")
        response = self._send_message({
            'action': 'getAlbumInfo',
            'pluginName': plugin_name,
            'albumInfo': album_info
        })

        if not response['success']:
            self.log.error(f"JS Plugin Manager getAlbumInfo failed in plugin {plugin_name}: {response['error']}")
            raise Exception(f"getAlbumInfo failed: {response['error']}")

        return response['result']

    def get_music_sheet_info(self, plugin_name: str, playlist_info: Dict[str, Any], page: int = 1):
        """获取歌单详情"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(f"JS Plugin Manager getting music sheet info in plugin {plugin_name} for playlist: {playlist_info.get('title', 'unknown')}")
        response = self._send_message({
            'action': 'getMusicSheetInfo',
            'pluginName': plugin_name,
            'playlistInfo': playlist_info
        })

        if not response['success']:
            self.log.error(f"JS Plugin Manager getMusicSheetInfo failed in plugin {plugin_name}: {response['error']}")
            raise Exception(f"getMusicSheetInfo failed: {response['error']}")

        return response['result']

    def get_artist_works(self, plugin_name: str, artist_item: Dict[str, Any], page: int = 1, type_: str = 'music'):
        """获取作者作品"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(f"JS Plugin Manager getting artist works in plugin {plugin_name} for artist: {artist_item.get('title', 'unknown')}")
        response = self._send_message({
            'action': 'getArtistWorks',
            'pluginName': plugin_name,
            'artistItem': artist_item,
            'page': page,
            'type': type_
        })

        if not response['success']:
            self.log.error(f"JS Plugin Manager getArtistWorks failed in plugin {plugin_name}: {response['error']}")
            raise Exception(f"getArtistWorks failed: {response['error']}")

        return response['result']

    def import_music_item(self, plugin_name: str, url_like: str):
        """导入单曲"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(f"JS Plugin Manager importing music item in plugin {plugin_name} from: {url_like}")
        response = self._send_message({
            'action': 'importMusicItem',
            'pluginName': plugin_name,
            'urlLike': url_like
        })

        if not response['success']:
            self.log.error(f"JS Plugin Manager importMusicItem failed in plugin {plugin_name}: {response['error']}")
            raise Exception(f"importMusicItem failed: {response['error']}")

        return response['result']

    def import_music_sheet(self, plugin_name: str, url_like: str):
        """导入歌单"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(f"JS Plugin Manager importing music sheet in plugin {plugin_name} from: {url_like}")
        response = self._send_message({
            'action': 'importMusicSheet',
            'pluginName': plugin_name,
            'urlLike': url_like
        })

        if not response['success']:
            self.log.error(f"JS Plugin Manager importMusicSheet failed in plugin {plugin_name}: {response['error']}")
            raise Exception(f"importMusicSheet failed: {response['error']}")

        return response['result']

    def get_top_lists(self, plugin_name: str):
        """获取榜单列表"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(f"JS Plugin Manager getting top lists in plugin {plugin_name}")
        response = self._send_message({
            'action': 'getTopLists',
            'pluginName': plugin_name
        })

        if not response['success']:
            self.log.error(f"JS Plugin Manager getTopLists failed in plugin {plugin_name}: {response['error']}")
            raise Exception(f"getTopLists failed: {response['error']}")

        return response['result']

    def get_top_list_detail(self, plugin_name: str, top_list_item: Dict[str, Any], page: int = 1):
        """获取榜单详情"""
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin {plugin_name} not found or not loaded")

        self.log.debug(f"JS Plugin Manager getting top list detail in plugin {plugin_name} for list: {top_list_item.get('title', 'unknown')}")
        response = self._send_message({
            'action': 'getTopListDetail',
            'pluginName': plugin_name,
            'topListItem': top_list_item,
            'page': page
        })

        if not response['success']:
            self.log.error(f"JS Plugin Manager getTopListDetail failed in plugin {plugin_name}: {response['error']}")
            raise Exception(f"getTopListDetail failed: {response['error']}")

        return response['result']

    def enable_plugin(self, plugin_name: str) -> bool:
        """启用插件"""
        if plugin_name in self.plugins:
            self.plugins[plugin_name]['enabled'] = True
            self.log.info(f"Plugin {plugin_name} enabled")
            return True
        return False

    def disable_plugin(self, plugin_name: str) -> bool:
        """禁用插件"""
        if plugin_name in self.plugins:
            self.plugins[plugin_name]['enabled'] = False
            self.log.info(f"Plugin {plugin_name} disabled")
            return True
        return False

    def shutdown(self):
        """关闭插件管理器"""
        if self.node_process:
            self.node_process.terminate()
            self.node_process.wait()
