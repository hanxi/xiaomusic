"""在线音乐服务模块

负责MusicFree插件集成、在线音乐搜索和播放链接获取。
"""

import asyncio
import base64
import ipaddress
import json
import socket
from urllib.parse import urlparse

import aiohttp

from xiaomusic.const import PLAY_TYPE_ALL


def _build_keyword(song_name, artist):
    """
    根据歌名和艺术家构建关键词

    Args:
        song_name: 歌名
        artist: 艺术家

    Returns:
        str: 构建后的关键词
    """
    if song_name and artist:
        return f"{song_name}-{artist}"
    elif song_name:
        return song_name
    elif artist:
        return artist
    return ""


def _parse_keyword_by_dash(keyword):
    if "-" in keyword:
        parts = keyword.split("-", 1)  # 只分割第一个 `-`
        return parts[0].strip(), parts[1].strip()
    return keyword, ""


class OnlineMusicService:
    """在线音乐服务

    负责处理在线音乐搜索、插件调用和播放链接获取。
    """

    def __init__(self, log, js_plugin_manager, xiaomusic_instance=None):
        """初始化在线音乐服务

        Args:
            log: 日志对象
            js_plugin_manager: JS插件管理器
        """
        self.log = log
        self.js_plugin_manager = js_plugin_manager
        self.xiaomusic = xiaomusic_instance

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
        if not self.js_plugin_manager:
            return {"success": False, "error": "JS Plugin Manager not available"}

        # 解析关键词和艺术家
        keyword, artist = await self._parse_keyword_and_artist(keyword)

        # 获取API配置信息
        openapi_info = self.js_plugin_manager.get_openapi_info()

        if plugin == "all":
            # 并发执行插件搜索和OpenAPI搜索
            return await self._execute_concurrent_searches(
                keyword, artist, page, limit, openapi_info
            )
        elif plugin == "OpenAPI":
            # OpenAPI搜索
            return await self._execute_openapi_search(openapi_info, keyword, artist)
        else:
            # 插件在线搜索
            return await self._execute_plugin_search(
                plugin, keyword, artist, page, limit
            )

    async def _parse_keyword_and_artist(self, keyword):
        """解析关键词和艺术家"""
        parsed_keyword, parsed_artist = await self._parse_keyword_with_ai(keyword)
        keyword = parsed_keyword or keyword
        artist = parsed_artist or ""
        return keyword, artist

    async def _execute_concurrent_searches(
        self, keyword, artist, page, limit, openapi_info
    ):
        """执行并发搜索 - 插件和OpenAPI"""
        tasks = []

        # 插件在线搜索任务
        plugin_task = asyncio.create_task(
            self.get_music_list_mf(
                "all", keyword=keyword, artist=artist, page=page, limit=limit
            )
        )
        tasks.append(plugin_task)

        # OpenAPI搜索任务（只有在配置正确时才创建）
        if (
            openapi_info.get("enabled", False)
            and openapi_info.get("search_url", "") != ""
        ):
            openapi_task = asyncio.create_task(
                self.js_plugin_manager.openapi_search(
                    url=openapi_info.get("search_url"), keyword=keyword, artist=artist
                )
            )
            tasks.append(openapi_task)

        # 并发执行任务
        results = await asyncio.gather(*tasks, return_exceptions=True)

        plugin_result = results[0]
        openapi_result = results[1] if len(results) > 1 else None

        # 处理异常情况
        plugin_result = self._handle_search_exception(plugin_result, "插件")
        openapi_result = self._handle_search_exception(openapi_result, "OpenAPI")

        # 合并结果
        combined_result = self._merge_search_results(
            plugin_result, openapi_result, keyword, artist, limit
        )
        combined_result["artist"] = artist or "佚名"
        return combined_result

    def _handle_search_exception(self, result, source_name):
        """处理搜索异常"""
        if result and isinstance(result, Exception):
            self.log.error(f"{source_name}搜索发生异常: {result}")
            return {"success": False, "error": str(result)}
        return result

    async def _execute_openapi_search(self, openapi_info, keyword, artist):
        """执行OpenAPI搜索"""
        if (
            openapi_info.get("enabled", False)
            and openapi_info.get("search_url", "") != ""
        ):
            # 开放接口获取
            result_data = await self.js_plugin_manager.openapi_search(
                url=openapi_info.get("search_url"), keyword=keyword, artist=artist
            )
        else:
            return {"success": False, "error": "OpenAPI未启用或配置错误"}

        result_data["artist"] = artist or "佚名"
        return result_data

    async def _execute_plugin_search(self, plugin, keyword, artist, page, limit):
        """执行插件搜索"""
        result_data = await self.get_music_list_mf(
            plugin, keyword=keyword, artist=artist, page=page, limit=limit
        )
        result_data["artist"] = artist or "佚名"
        return result_data

    def _merge_search_results(
        self, plugin_result, openapi_result, keyword, artist, limit
    ):
        merged_data = []
        sources = {}

        # 先处理 OpenAPI 结果
        if openapi_result and openapi_result.get("success"):
            openapi_data = openapi_result.get("data", [])
            if openapi_data:
                for item in openapi_data:
                    item["source"] = "openapi"
                merged_data.extend(openapi_data)
                if "sources" in openapi_result:
                    sources.update(openapi_result["sources"])

        # 再处理插件结果
        if plugin_result and plugin_result.get("success"):
            plugin_data = plugin_result.get("data", [])
            if plugin_data:
                for item in plugin_data:
                    item["source"] = "plugin"
                merged_data.extend(plugin_data)
                sources.update(plugin_result.get("sources", {}))

        # 如果都没有成功结果，返回错误
        if not plugin_result.get("success") and not (
            openapi_result and openapi_result.get("success")
        ):
            # 优先返回第一个错误
            error_result = (
                plugin_result if not plugin_result.get("success") else openapi_result
            )
            return error_result

        # 优化合并后的结果
        optimized_result = self.js_plugin_manager.optimize_search_results(
            {"data": merged_data},
            search_keyword=keyword,
            limit=limit,
            search_artist=artist,
        )

        return {
            "success": True,
            "data": optimized_result.get("data", []),
            "total": len(optimized_result.get("data", [])),
            "sources": sources,
            "merged": True,  # 标识这是合并结果
        }

    async def get_music_list_mf(
        self, plugin="all", keyword="", artist="", page=1, limit=20, **kwargs
    ):
        self.log.info("通过MusicFree插件搜索音乐列表!")
        """
        通过MusicFree插件搜索音乐列表

        Args:
            plugin: 插件名称，"all"表示所有插件
            keyword: 搜索关键词
            page: 页码
            limit: 每页数量
            **kwargs: 其他参数

        Returns:
            dict: 搜索结果
        """
        # 检查JS插件管理器是否可用
        if not self.js_plugin_manager:
            return {"success": False, "error": "JS插件管理器不可用"}
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

    # 调用在线搜索歌手，添加歌手歌单并播放
    async def search_singer_play(self, did, search_key, name):
        try:
            # 解析歌手名，可能通过AI或直接分割
            parsed_keyword, parsed_artist = await self._parse_keyword_with_ai(name)
            list_name = "_online_" + parsed_artist
            artist_song_list = self.xiaomusic.get_music_list().get(list_name, [])
            if len(artist_song_list) > 0:
                # 如果歌单存在，则直接播放
                song_name = artist_song_list[0]
                await self.xiaomusic.do_play_music_list(did, list_name, song_name)
            else:
                # 获取歌曲列表
                result = await self.get_music_list_online(keyword=name, limit=10)
                self.log.info(f"在线搜索歌手的歌曲列表: {result}")

                if result.get("success") and result.get("total") > 0:
                    # 打印输出 result.data
                    self.log.info(f"歌曲列表: {result.get('data')}")
                    list_name = "_online_" + result.get("artist")
                    # 调用公共函数,处理歌曲信息 -> 添加歌单 -> 播放歌单
                    return await self.push_music_list_play(
                        did=did, song_list=result.get("data"), list_name=list_name
                    )
                else:
                    return {"success": False, "error": "未找到歌曲"}

        except Exception as e:
            # 记录错误日志
            self.log.error(f"searchKey {search_key} get media source failed: {e}")
            return {"success": False, "error": str(e)}

    # 调用在线搜索歌手，追加歌手歌曲
    async def add_singer_song(self, list_name, name):
        try:
            # 获取歌曲列表
            result = await self.get_music_list_online(keyword=name, limit=10)
            if result.get("success") and result.get("total") > 0:
                self._handle_music_list(result.get("data"), list_name, True)
            else:
                return {"success": False, "error": "未找到歌曲"}
        except Exception as e:
            # 记录错误日志
            return {"success": False, "error": str(e)}

    """------------------------私有--------------------------"""

    async def _parse_keyword_with_ai(self, keyword):
        """
        使用AI解析关键词，如果AI不可用则使用传统分割方式
        Args:
            keyword: 原始关键词
        Returns:
            tuple: (parsed_keyword, parsed_artist)
        """
        # 获取AI配置信息
        ai_info = self.js_plugin_manager.get_aiapi_info()
        # 如果AI启用且配置完整
        if ai_info.get("enabled", False) and ai_info.get("api_key", "") != "":
            try:
                from xiaomusic.utils.openai_utils import (
                    analyze_music_command as utils_analyze_music_command,
                )

                params = {"command": keyword, "api_key": ai_info.get("api_key")}

                # 添加可选参数
                if "base_url" in ai_info:
                    params["base_url"] = ai_info["base_url"]
                if "model" in ai_info:
                    params["model"] = ai_info["model"]

                result = await utils_analyze_music_command(**params)

                if result and (result.get("name") or result.get("artist")):
                    song_name = result.get("name", "")
                    artist = result.get("artist", "")
                    # 构建新的关键词
                    # keyword = _build_keyword(song_name, artist)
                    keyword = song_name
                    self.log.info(f"AI提取到的信息: {result}")
                    return keyword, artist

            except Exception as e:
                self.log.error(f"AI提取报错: {e}")

        # 如果AI不可用或处理失败，使用传统分割方式
        return _parse_keyword_by_dash(keyword)

    # 处理推送的歌单
    def _handle_music_list(
        self, song_list=None, list_name="_online_play", append=False
    ):
        """
        数据转换：将外部歌单格式转换为后端支持的格式
        保存配置：将歌单数据保存到配置中
        更新列表：触发后端重新生成音乐列表
        Args:
            song_list: 歌曲列表
            list_name: 列表名称
            append: 是否追加
        Returns:
            dict: 操作结果
        """
        try:
            if len(song_list) > 1:
                #  对歌单 歌名+歌手名进行去重
                song_list = self._deduplicate_song_list(song_list)
            # 转换外部歌单格式为内部支持的格式
            converted_music_list = self._convert_song_list_to_music_items(song_list)
            if not converted_music_list:
                return {"success": False, "error": "没有有效的歌曲可以添加"}
            music_library = self.xiaomusic.music_library
            # 更新配置中的音乐歌单Json
            music_library.update_music_list_json(
                list_name, converted_music_list, append
            )
            # 重新生成音乐列表
            music_library.gen_all_music_list()
        except Exception as e:
            self.log.error(f"推送歌单失败: {e}")
            return {"success": False, "error": str(e)}

    # 在线播放：在线搜索、播放
    async def online_play(self, did="", arg1="", **kwargs):
        await self._before_play()
        # 获取搜索关键词
        parts = arg1.split("|")
        search_key = parts[0]
        name = parts[1] if len(parts) > 1 else search_key
        if not name:
            name = search_key
        self.log.info(f"搜索关键字{search_key},提取的歌名{name}")
        await self.search_top_one_play(did, search_key, name)

    # 播放歌手：在线搜索歌手并存为列表播放
    async def singer_play(self, did="", arg1="", **kwargs):
        await self._before_play()
        # 获取搜索关键词
        parts = arg1.split("|")
        search_key = parts[0]
        name = parts[1] if len(parts) > 1 else search_key
        if not name:
            name = search_key
        self.log.info(f"搜索关键字{search_key},搜索歌手名{name}")
        await self.search_singer_play(did, search_key, name)

    # 处理推送的歌单并播放
    async def push_music_list_play(
        self, did="web_device", song_list=None, list_name="_online_play", **kwargs
    ):
        """
        处理推送的歌单信息 -> 添加歌单 -> 播放歌单

        Args:
            did: 设备ID
            song_list: 歌曲列表
            list_name: 列表名称
            **kwargs: 其他参数
        Returns:
            dict: 操作结果
        """
        if song_list is None:
            song_list = []

        self.log.info(
            f"推送歌单播放, 歌单名称: {list_name}, 歌曲数量: {len(song_list)}, 设备ID: {did}"
        )
        # 验证输入参数
        if not song_list and len(song_list) > 0:
            return {"success": False, "error": "歌曲列表不能为空"}
        try:
            self._handle_music_list(song_list, list_name)
            # 如果指定了特定设备，播放歌单
            if did != "web_device" and self.xiaomusic.did_exist(did):
                # 歌单推送应该是全部播放，不随机打乱
                await self.xiaomusic.set_play_type(did, PLAY_TYPE_ALL, False)
                push_playlist = self.xiaomusic.get_music_list()[list_name]
                song_name = push_playlist[0]
                await self.xiaomusic.do_play_music_list(did, list_name, song_name)
                return {
                    "success": True,
                    "message": f"成功推送歌单 {list_name}",
                    "list_name": list_name,
                }
            else:
                return {"success": False, "error": "设备不存在！"}
        except Exception as e:
            self.log.error(f"推送歌单播放失败: {e}")
            return {"success": False, "error": str(e)}

    # 在线搜索搜索最符合的一首歌并播放
    async def search_top_one_play(self, did, search_key, name):
        try:
            # 获取歌曲列表
            result = await self.get_music_list_online(keyword=name, limit=10)

            if result.get("success") and result.get("total") > 0:
                # 打印输出 result.data
                self.log.info(f"在线搜索的歌曲列表: {result.get('data')}")
                # 根据搜素关键字，智能搜索出最符合的一条music_item
                top_one_list = await self._search_top_one(
                    result.get("data"), search_key, name
                )
                list_name = "_online_play"
                # 调用公共函数,处理歌曲信息 -> 添加歌单 -> 播放歌单
                return await self.push_music_list_play(
                    did=did, song_list=top_one_list, list_name=list_name
                )
            else:
                return {"success": False, "error": "未找到歌曲"}
        except Exception as e:
            # 记录错误日志
            self.log.error(f"searchKey {search_key} get media source failed: {e}")
            return {"success": False, "error": str(e)}

    def default_url(self):
        # 先推送默认【搜索中】音频，搜索到播放url后推送给小爱
        config = self.xiaomusic.config
        if config and hasattr(config, "hostname") and hasattr(config, "public_port"):
            proxy_base = f"{config.hostname}:{config.public_port}"
        else:
            proxy_base = "http://192.168.31.241:8090"
        # return proxy_base + "/static/search.mp3"
        return proxy_base + "/static/silence.mp3"

    async def _before_play(self):
        # 先推送默认【搜索中】音频，搜索到播放url后推送给小爱
        before_url = self.default_url()
        await self.xiaomusic.play_url(self.xiaomusic.get_cur_did(), before_url)

    def _convert_song_list_to_music_items(self, song_list):
        """
        将外部歌单格式转换为内部支持的格式

        Args:
            song_list: 外部歌单数据

        Returns:
            list: 转换后的音乐项目列表
        """
        converted_music_list = []
        for item in song_list:
            if isinstance(item, dict):
                source_url = item.get("url", "")
                music_item = {}
                if source_url:
                    music_item["url"] = source_url
                else:
                    # 返回插件源的代理接口
                    music_item["url"] = self._get_plugin_proxy_url(item)
                # 其他信息
                music_item["name"] = item.get("title") + "-" + item.get("artist")
                music_item["type"] = item.get("type", "music")
            else:
                continue

            if music_item["name"]:
                converted_music_list.append(music_item)

        return converted_music_list

    def _get_plugin_proxy_url(self, origin_data):
        """获取插件源代理URL"""
        origin_data = json.dumps(origin_data)
        datab64 = base64.b64encode(origin_data.encode("utf-8")).decode("utf-8")
        plugin_source_url = f"self:///api/proxy/plugin-url?data={datab64}"
        self.log.info(f"plugin_source_url : {plugin_source_url}")
        return plugin_source_url

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
        """单个插件搜索任务"""
        try:
            return self.js_plugin_manager.search(plugin_name, keyword, page, limit)
        except Exception as e:
            # 直接抛出异常，让 asyncio.gather 处理
            raise e

    # 调用MusicFree插件获取真实播放url
    async def get_media_source_url(self, music_item, quality: str = "standard"):
        """获取音乐项的媒体源URL
        Args:
            music_item : MusicFree插件定义的 IMusicItem
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

    def _deduplicate_song_list(self, song_list):
        """
        根据歌名+歌手名对歌单中歌曲进行去重
        Args:
            song_list: 原始歌曲列表
        Returns:
            unique_songs: 去重后的歌曲列表
        """
        seen = set()
        unique_songs = []

        for song in song_list:
            # 构建唯一标识：歌名+歌手名
            song_title = song.get("title", "")
            song_artist = song.get("artist", "")

            # 创建唯一标识符
            unique_key = f"{song_title.lower()}_{song_artist.lower()}"

            # 如果未见过此唯一标识，则添加到结果中
            if unique_key not in seen:
                seen.add(unique_key)
                unique_songs.append(song)

        self.log.info(
            f"歌单去重完成，原始数量: {len(song_list)}, 去重后数量: {len(unique_songs)}"
        )
        return unique_songs

    async def _search_top_one(self, music_items, search_key, name):
        """智能搜索出最符合的一条music_item"""
        try:
            if not music_items:
                return []

            self.log.info(f"搜索关键字: {search_key}；歌名：{name}")

            # 使用更高效的算法进行匹配
            if len(music_items) == 1:
                return music_items

            # 计算每个项目的匹配分数
            keyword = search_key.lower().strip()
            if not keyword:
                return [music_items[0]]  # 如果没有搜索词，返回第一首

            def calculate_match_score(item):
                """计算匹配分数"""
                title = (item.get("title", "") or "").lower()
                artist = (item.get("artist", "") or "").lower()

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
            return [sorted_items[0]]

        except Exception as e:
            self.log.error(f"_search_top_one error: {e}")
            # 出现异常时返回第一个项目
            return [music_items[0]] if music_items else []

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
    async def _make_request_with_validation(
        url: str, timeout: int, convert_m4s: bool = False
    ) -> str:
        """
        通用的URL请求和验证方法

        Args:
            url (str): 原始音乐URL
            timeout (int): 请求超时时间(秒)

        Returns:
            str: 最终的真实播放URL，如果代理不成功则返回原始URL
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
                return url  # 返回原始URL
            # 仅允许 http/https
            if parsed_url.scheme not in ("http", "https"):
                return url  # 返回原始URL
            # 检查主机是否安全，防止SSRF到内网
            if not _is_safe_hostname(parsed_url):
                return url  # 返回原始URL

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
                    return final_url
        except Exception:
            return url  # 返回原始URL
