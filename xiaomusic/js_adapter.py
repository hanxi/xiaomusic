#!/usr/bin/env python3
"""
JS 插件适配器
将 MusicFree JS 插件的数据格式转换为 xiaomusic 接口规范
"""

import logging


class JSAdapter:
    """JS 插件数据适配器"""

    def __init__(self, xiaomusic):
        self.xiaomusic = xiaomusic
        self.log = logging.getLogger(__name__)

    def format_search_results(
        self, plugin_results: list[dict], plugin_name: str
    ) -> list[str]:
        """格式化搜索结果为 xiaomusic 格式，返回 ID 列表"""
        formatted_ids = []
        for item in plugin_results:
            if not isinstance(item, dict):
                self.log.warning(f"Invalid item format in plugin {plugin_name}: {item}")
                continue

            # 构造符合 xiaomusic 格式的音乐项
            music_id = self._generate_music_id(
                plugin_name, item.get("id", ""), item.get("songmid", "")
            )
            music_item = {
                "id": music_id,
                "title": item.get("title", item.get("name", "")),
                "artist": self._extract_artists(item),
                "album": item.get("album", item.get("albumName", "")),
                "source": "online",
                "plugin_name": plugin_name,
                "original_data": item,
                "duration": item.get("duration", 0),
                "cover": item.get(
                    "artwork", item.get("cover", item.get("albumPic", ""))
                ),
                "url": item.get("url", ""),
                "lyric": item.get("lyric", item.get("lrc", "")),
                "quality": item.get("quality", ""),
            }

            # 添加到 all_music 字典中
            self.xiaomusic.all_music[music_id] = music_item
            formatted_ids.append(music_id)

        return formatted_ids

    def format_media_source_result(
        self, media_source_result: dict, music_item: dict
    ) -> dict:
        """格式化媒体源结果"""
        if not media_source_result:
            return {}

        formatted = {
            "url": media_source_result.get("url", ""),
            "headers": media_source_result.get("headers", {}),
            "userAgent": media_source_result.get(
                "userAgent", media_source_result.get("user_agent", "")
            ),
        }

        return formatted

    def format_lyric_result(self, lyric_result: dict) -> str:
        """格式化歌词结果为 lrc 格式字符串"""
        if not lyric_result:
            return ""

        # 获取原始歌词和翻译
        raw_lrc = lyric_result.get("rawLrc", lyric_result.get("raw_lrc", ""))
        translation = lyric_result.get("translation", "")

        # 如果有翻译，合并歌词和翻译
        if translation and raw_lrc:
            # 这里可以实现歌词和翻译的合并逻辑
            return f"{raw_lrc}\n{translation}"

        return raw_lrc or translation or ""

    def format_album_info_result(self, album_info_result: dict) -> dict:
        """格式化专辑信息结果"""
        if not album_info_result:
            return {}

        album_item = album_info_result.get("albumItem", {})
        formatted = {
            "isEnd": album_info_result.get("isEnd", True),
            "musicList": self.format_search_results(
                album_info_result.get("musicList", []), "album"
            ),
            "albumItem": {
                "title": album_item.get("title", ""),
                "artist": album_item.get("artist", ""),
                "cover": album_item.get("cover", ""),
                "description": album_item.get("description", ""),
            },
        }

        return formatted

    def format_music_sheet_info_result(self, music_sheet_result: dict) -> dict:
        """格式化音乐单信息结果"""
        if not music_sheet_result:
            return {}
        sheet_item = music_sheet_result.get("sheetItem", {})
        formatted = {
            "isEnd": music_sheet_result.get("isEnd", True),
            "musicList": self.format_search_results(
                music_sheet_result.get("musicList", []), "playlist"
            ),
            "sheetItem": {
                "title": sheet_item.get("title", ""),
                "cover": sheet_item.get("cover", ""),
                "description": sheet_item.get("description", ""),
            },
        }

        return formatted

    def format_artist_works_result(self, artist_works_result: dict) -> dict:
        """格式化艺术家作品结果"""
        if not artist_works_result:
            return {}

        formatted = {
            "isEnd": artist_works_result.get("isEnd", True),
            "data": self.format_search_results(
                artist_works_result.get("data", []), "artist"
            ),
        }

        return formatted

    def format_top_lists_result(self, top_lists_result: list[dict]) -> list[dict]:
        """格式化榜单列表结果"""
        if not top_lists_result:
            return []

        formatted = []
        for group in top_lists_result:
            formatted_group = {"title": group.get("title", ""), "data": []}

            for item in group.get("data", []):
                formatted_item = {
                    "id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "coverImg": item.get("coverImg", item.get("cover", "")),
                }
                formatted_group["data"].append(formatted_item)

            formatted.append(formatted_group)

        return formatted

    def format_top_list_detail_result(self, top_list_detail_result: dict) -> dict:
        """格式化榜单详情结果"""
        if not top_list_detail_result:
            return {}

        formatted = {
            "isEnd": top_list_detail_result.get("isEnd", True),
            "musicList": self.format_search_results(
                top_list_detail_result.get("musicList", []), "toplist"
            ),
            "topListItem": top_list_detail_result.get("topListItem", {}),
        }

        return formatted

    def _generate_music_id(
        self, plugin_name: str, item_id: str, fallback_id: str = ""
    ) -> str:
        """生成唯一音乐ID"""
        if item_id:
            return f"online_{plugin_name}_{item_id}"
        else:
            # 如果没有 id，尝试使用其他标识符
            return f"online_{plugin_name}_{fallback_id}"

    def _extract_artists(self, item: dict) -> str:
        """提取艺术家信息"""
        # 尝试多种可能的艺术家字段
        artist_fields = ["artist", "artists", "singer", "author", "creator", "singers"]

        for field in artist_fields:
            if field not in item:
                continue
            value = item[field]
            if isinstance(value, list):
                # 如果是艺术家列表，连接为字符串
                artists = []
                for artist in value:
                    if isinstance(artist, dict):
                        artists.append(artist.get("name", str(artist)))
                    else:
                        artists.append(str(artist))
                return ", ".join(artists)
            elif isinstance(value, dict):
                # 如果是艺术家对象
                return value.get("name", str(value))
            elif value:
                return str(value)

        # 如果没有找到艺术家信息，返回默认值
        return "未知艺术家"

    def convert_music_item_for_plugin(self, music_item: dict) -> dict:
        """将 xiaomusic 音乐项转换为插件兼容格式"""
        # 如果原始数据存在，优先使用原始数据
        if isinstance(music_item, dict) and "original_data" in music_item:
            return music_item["original_data"]

        # 否则构造一个基本的音乐项
        converted = {
            "id": music_item.get("id", ""),
            "title": music_item.get("title", ""),
            "artist": music_item.get("artist", ""),
            "album": music_item.get("album", ""),
            "url": music_item.get("url", ""),
            "duration": music_item.get("duration", 0),
            "artwork": music_item.get("cover", ""),
            "lyric": music_item.get("lyric", ""),
            "quality": music_item.get("quality", ""),
        }

        return converted
