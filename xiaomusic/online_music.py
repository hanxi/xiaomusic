"""在线音乐服务模块

负责MusicFree插件集成、在线音乐搜索和播放链接获取。
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import aiohttp


class OnlineMusicService:
    """在线音乐服务

    负责处理在线音乐搜索、插件调用和播放链接获取。
    """

    def __init__(self, log, js_plugin_manager):
        """初始化在线音乐服务

        Args:
            log: 日志对象
            js_plugin_manager: JS插件管理器
        """
        self.log = log
        self.js_plugin_manager = js_plugin_manager

    async def get_music_list_online(
        self, plugin="all", keyword="", page=1, limit=20, **kwargs
    ):
        """在线获取歌曲列表

        Args:
            plugin: 插件名称，"OpenAPI"表示通过开放接口获取，其他为插件在线搜索
            keyword: 搜索关键词
            page: 页码
            limit: 每页数量
            **kwargs: 其他参数

        Returns:
            dict: 搜索结果
        """
        self.log.info("在线获取歌曲列表!")

        openapi_info = self.js_plugin_manager.get_openapi_info()
        if (
            openapi_info.get("enabled", False)
            and openapi_info.get("search_url", "") != ""
        ):
            # 开放接口获取
            return await self.js_plugin_manager.openapi_search(
                openapi_info.get("search_url"), keyword
            )
        else:
            if not self.js_plugin_manager:
                return {"success": False, "error": "JS Plugin Manager not available"}
            # 插件在线搜索
            return await self.get_music_list_mf(plugin, keyword, page, limit)

    async def get_music_list_mf(
        self, plugin="all", keyword="", page=1, limit=20, **kwargs
    ):
        """通过MusicFree插件搜索音乐列表

        Args:
            plugin: 插件名称，"all"表示所有插件
            keyword: 搜索关键词
            page: 页码
            limit: 每页数量
            **kwargs: 其他参数

        Returns:
            dict: 搜索结果
        """
        self.log.info("通过MusicFree插件搜索音乐列表!")

        # 检查JS插件管理器是否可用
        if not self.js_plugin_manager:
            return {"success": False, "error": "JS插件管理器不可用"}

        # 如果关键词包含 '-'，则提取歌手名、歌名
        if "-" in keyword:
            parts = keyword.split("-")
            keyword = parts[0]
            artist = parts[1]
        else:
            artist = ""

        try:
            if plugin == "all":
                # 搜索所有启用的插件
                return await self._search_all_plugins(keyword, artist, page, limit)
            else:
                # 搜索指定插件
                return await self._search_specific_plugin(
                    plugin, keyword, artist, page, limit
                )
        except Exception as e:
            self.log.error(f"搜索音乐时发生错误: {e}")
            return {"success": False, "error": str(e)}

    async def _search_all_plugins(self, keyword, artist, page, limit):
        """搜索所有启用的插件

        Args:
            keyword: 搜索关键词
            artist: 艺术家名称
            page: 页码
            limit: 每页数量

        Returns:
            dict: 搜索结果
        """
        enabled_plugins = self.js_plugin_manager.get_enabled_plugins()
        if not enabled_plugins:
            return {"success": False, "error": "没有可用的接口和插件，请先进行配置！"}

        results = []
        sources = {}

        # 计算每个插件的限制数量
        plugin_count = len(enabled_plugins)
        item_limit = max(1, limit // plugin_count) if plugin_count > 0 else limit

        # 并行搜索所有插件
        search_tasks = [
            self._search_plugin_task(plugin_name, keyword, page, item_limit)
            for plugin_name in enabled_plugins
        ]

        plugin_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        # 处理搜索结果
        for i, result in enumerate(plugin_results):
            plugin_name = list(enabled_plugins)[i]

            # 检查是否为异常对象
            if isinstance(result, Exception):
                self.log.error(f"插件 {plugin_name} 搜索失败: {result}")
                continue

            # 检查是否为有效的搜索结果
            if result and isinstance(result, dict):
                # 检查是否有错误信息
                if "error" in result:
                    self.log.error(
                        f"插件 {plugin_name} 搜索失败: {result.get('error', '未知错误')}"
                    )
                    continue

                # 处理成功的搜索结果
                data_list = result.get("data", [])
                if data_list:
                    results.extend(data_list)
                    sources[plugin_name] = len(data_list)
                # 如果没有data字段但有其他数据，也认为是成功的结果
                elif result:  # 非空字典
                    results.append(result)
                    sources[plugin_name] = 1

        # 统一排序并提取前limit条数据
        if results:
            unified_result = {"data": results}
            optimized_result = self.js_plugin_manager.optimize_search_results(
                unified_result,
                search_keyword=keyword,
                limit=limit,
                search_artist=artist,
            )
            results = optimized_result.get("data", [])

        return {
            "success": True,
            "data": results,
            "total": len(results),
            "sources": sources,
            "page": page,
            "limit": limit,
        }

    async def _search_specific_plugin(self, plugin, keyword, artist, page, limit):
        """搜索指定插件

        Args:
            plugin: 插件名称
            keyword: 搜索关键词
            artist: 艺术家名称
            page: 页码
            limit: 每页数量

        Returns:
            dict: 搜索结果
        """
        try:
            results = self.js_plugin_manager.search(plugin, keyword, page, limit)

            # 额外检查 resources 字段
            data_list = results.get("data", [])
            if data_list:
                # 优化搜索结果排序
                results = self.js_plugin_manager.optimize_search_results(
                    results, search_keyword=keyword, limit=limit, search_artist=artist
                )

            return {
                "success": True,
                "data": results.get("data", []),
                "total": results.get("total", 0),
                "page": page,
                "limit": limit,
            }
        except Exception as e:
            self.log.error(f"插件 {plugin} 搜索失败: {e}")
            return {"success": False, "error": str(e)}

    async def _search_plugin_task(self, plugin_name, keyword, page, limit):
        """单个插件搜索任务

        Args:
            plugin_name: 插件名称
            keyword: 搜索关键词
            page: 页码
            limit: 每页数量

        Returns:
            dict: 搜索结果

        Raises:
            Exception: 搜索失败时抛出异常
        """
        try:
            return self.js_plugin_manager.search(plugin_name, keyword, page, limit)
        except Exception as e:
            # 直接抛出异常，让 asyncio.gather 处理
            raise e

    async def get_media_source_url(self, music_item, quality: str = "standard"):
        """获取音乐项的媒体源URL

        Args:
            music_item: MusicFree插件定义的 IMusicItem
            quality: 音质参数

        Returns:
            dict: 包含成功状态和URL信息的字典
        """
        # kwargs可追加
        kwargs = {"quality": quality}
        return await self._call_plugin_method(
            plugin_name=music_item.get("platform"),
            method_name="get_media_source",
            music_item=music_item,
            result_key="url",
            required_field="url",
            **kwargs,
        )

    async def get_media_lyric(self, music_item):
        """获取音乐项的歌词 Lyric

        Args:
            music_item: MusicFree插件定义的 IMusicItem

        Returns:
            dict: 包含成功状态和歌词信息的字典
        """
        return await self._call_plugin_method(
            plugin_name=music_item.get("platform"),
            method_name="get_lyric",
            music_item=music_item,
            result_key="rawLrc",
            required_field="rawLrc",
        )

    async def search_music_online(self, search_key, name):
        """调用MusicFree插件搜索歌曲

        Args:
            search_key: 搜索关键词
            name: 歌曲名

        Returns:
            dict: 包含成功状态和URL信息的字典
        """
        try:
            # 获取歌曲列表
            result = await self.get_music_list_online(keyword=name, limit=10)
            self.log.info(f"在线搜索歌曲列表: {result}")

            if result.get("success") and result.get("total") > 0:
                # 打印输出 result.data
                self.log.info(f"歌曲列表: {result.get('data')}")
                # 根据搜索关键字，智能搜索出最符合的一条music_item
                music_item = await self._search_top_one(
                    result.get("data"), search_key, name
                )
                # 验证 music_item 是否为字典类型
                if not isinstance(music_item, dict):
                    self.log.error(
                        f"music_item should be a dict, but got {type(music_item)}: {music_item}"
                    )
                    return {"success": False, "error": "Invalid music item format"}

                # 如果是OpenAPI，则需要转换播放链接
                openapi_info = self.js_plugin_manager.get_openapi_info()
                if openapi_info.get("enabled", False):
                    return await self.get_real_url_of_openapi(music_item.get("url"))
                else:
                    media_source = await self.get_media_source_url(music_item)
                    if media_source.get("success"):
                        return {"success": True, "url": media_source.get("url")}
                    else:
                        return {"success": False, "error": media_source.get("error")}
            else:
                return {"success": False, "error": "未找到歌曲"}

        except Exception as e:
            # 记录错误日志
            self.log.error(f"searchKey {search_key} get media source failed: {e}")
            return {"success": False, "error": str(e)}

    async def _search_top_one(self, music_items, search_key, name):
        """智能搜索出最符合的一条music_item

        Args:
            music_items: 音乐项目列表
            search_key: 搜索关键词
            name: 歌曲名

        Returns:
            dict: 最匹配的音乐项目，如果没有则返回None
        """
        try:
            # 如果没有音乐项目，返回None
            if not music_items:
                return None

            self.log.info(f"搜索关键字: {search_key}；歌名：{name}")
            # 如果只有一个项目，直接返回
            if len(music_items) == 1:
                return music_items[0]

            # 计算每个项目的匹配分数
            def calculate_match_score(item):
                """计算匹配分数"""
                title = item.get("title", "").lower() if item.get("title") else ""
                artist = item.get("artist", "").lower() if item.get("artist") else ""
                keyword = search_key.lower()

                if not keyword:
                    return 0

                score = 0
                # 歌曲名匹配权重
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

                # 艺术家名匹配权重
                if keyword in artist:
                    # 完全匹配
                    if artist == keyword:
                        score += 9
                    # 开头匹配
                    elif artist.startswith(keyword):
                        score += 7
                    # 结尾匹配
                    elif artist.endswith(keyword):
                        score += 5
                    # 包含匹配
                    else:
                        score += 3
                # 部分字符匹配
                elif any(char in artist for char in keyword.split()):
                    score += 1

                return score

            # 按匹配分数排序，返回分数最高的项目
            sorted_items = sorted(music_items, key=calculate_match_score, reverse=True)
            return sorted_items[0]

        except Exception as e:
            self.log.error(f"_search_top_one error: {e}")
            # 出现异常时返回第一个项目
            return music_items[0] if music_items else None

    async def _call_plugin_method(
        self,
        plugin_name: str,
        method_name: str,
        music_item: dict,
        result_key: str,
        required_field: str = None,
        **kwargs,
    ):
        """通用方法：调用 JS 插件的方法并返回结果

        Args:
            plugin_name: 插件名称
            method_name: 插件方法名（如 get_media_source 或 get_lyric）
            music_item: 音乐项数据
            result_key: 返回结果中的字段名（如 'url' 或 'rawLrc'）
            required_field: 必须存在的字段（用于校验）
            **kwargs: 传递给插件方法的额外参数

        Returns:
            dict: 包含 success 和对应字段的字典
        """
        if not music_item:
            return {"success": False, "error": "Music item required"}

        # 检查插件管理器是否可用
        if not self.js_plugin_manager:
            return {"success": False, "error": "JS Plugin Manager not available"}

        enabled_plugins = self.js_plugin_manager.get_enabled_plugins()
        if plugin_name not in enabled_plugins:
            return {"success": False, "error": f"Plugin {plugin_name} not enabled"}

        try:
            # 调用插件方法，传递额外参数
            result = getattr(self.js_plugin_manager, method_name)(
                plugin_name, music_item, **kwargs
            )
            if (
                not result
                or not result.get(result_key)
                or result.get(result_key) == "None"
            ):
                return {"success": False, "error": f"Failed to get {result_key}"}

            # 如果指定了必填字段，则额外校验
            if required_field and not result.get(required_field):
                return {
                    "success": False,
                    "error": f"Missing required field: {required_field}",
                }
            # 追加属性后返回
            result["success"] = True
            return result

        except Exception as e:
            self.log.error(f"Plugin {plugin_name} {method_name} failed: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def get_real_url_of_openapi(url: str, timeout: int = 10) -> dict:
        """通过服务端代理获取开放接口真实的音乐播放URL，避免CORS问题

        Args:
            url: 原始音乐URL
            timeout: 请求超时时间(秒)

        Returns:
            dict: 包含success、url、statusCode等信息的字典
        """

        # 内部辅助函数：检查主机解析到的IP是否安全，防止访问内网/本地地址
        def _is_safe_hostname(parsed) -> bool:
            hostname = parsed.hostname
            if not hostname:
                return False
            try:
                # 解析主机名对应的所有地址
                addrinfo_list = socket.getaddrinfo(hostname, None)
            except Exception:
                return False
            for family, _, _, _, sockaddr in addrinfo_list:
                ip_str = (
                    sockaddr[0] if family in (socket.AF_INET, socket.AF_INET6) else None
                )
                if not ip_str:
                    continue
                try:
                    ip_obj = ipaddress.ip_address(ip_str)
                except ValueError:
                    return False
                # 拒绝内网、回环、链路本地、多播和保留地址
                if (
                    ip_obj.is_private
                    or ip_obj.is_loopback
                    or ip_obj.is_link_local
                    or ip_obj.is_multicast
                    or ip_obj.is_reserved
                ):
                    return False
            return True

        try:
            # 验证URL格式
            parsed_url = urlparse(url)
            if not parsed_url.scheme or not parsed_url.netloc:
                return {"success": False, "url": url, "error": "Invalid URL format"}
            # 仅允许 http/https
            if parsed_url.scheme not in ("http", "https"):
                return {
                    "success": False,
                    "url": url,
                    "error": "Unsupported URL scheme",
                }
            # 检查主机是否安全，防止SSRF到内网
            if not _is_safe_hostname(parsed_url):
                return {
                    "success": False,
                    "url": url,
                    "error": "Unsafe target host",
                }

            # 创建aiohttp客户端会话
            async with aiohttp.ClientSession() as session:
                # 发送HEAD请求跟随重定向
                async with session.head(
                    url,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    # 获取最终重定向后的URL
                    final_url = str(response.url)

                    return {
                        "success": True,
                        "url": final_url,
                        "statusCode": response.status,
                    }
        except Exception as e:
            return {"success": False, "url": url, "error": f"Error occurred: {str(e)}"}
