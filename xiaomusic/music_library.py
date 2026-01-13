"""音乐库管理模块

负责音乐库的管理、播放列表操作、音乐搜索和标签管理。
"""

import asyncio
import copy
import json
import os
import random
import time
import urllib.parse
from collections import OrderedDict
from dataclasses import asdict

from xiaomusic.const import SUPPORT_MUSIC_TYPE
from xiaomusic.utils import (
    custom_sort_key,
    extract_audio_metadata,
    find_best_match,
    fuzzyfinder,
    not_in_dirs,
    save_picture_by_base64,
    set_music_tag_to_file,
    traverse_music_directory,
    try_add_access_control_param,
)
from xiaomusic.utils.music_utils import (
    Metadata,
    get_local_music_duration,
    get_web_music_duration,
)


class MusicLibrary:
    """音乐库管理类

    负责管理本地和网络音乐库，包括：
    - 音乐列表生成和管理
    - 播放列表的增删改查
    - 音乐搜索和模糊匹配
    - 音乐标签的读取和更新
    """

    def __init__(
        self,
        config,
        log,
        music_path,
        download_path,
        hostname,
        public_port,
        music_path_depth,
        exclude_dirs,
    ):
        """初始化音乐库

        Args:
            config: 配置对象
            log: 日志对象
            music_path: 音乐目录路径
            download_path: 下载目录路径
            hostname: 主机名
            public_port: 公开端口
            music_path_depth: 音乐目录扫描深度
            exclude_dirs: 排除的目录列表
        """
        self.config = config
        self.log = log
        self.music_path = music_path
        self.download_path = download_path
        self.hostname = hostname
        self.public_port = public_port
        self.music_path_depth = music_path_depth
        self.exclude_dirs = exclude_dirs

        # 音乐库数据
        self.all_music = {}  # 所有音乐 {name: filepath/url}
        self.music_list = {}  # 播放列表 {list_name: [music_names]}
        self.default_music_list_names = []  # 非自定义歌单名称列表
        self.custom_play_list = None  # 自定义播放列表缓存

        # 网络音乐相关
        self._all_radio = {}  # 所有电台
        self._web_music_api = {}  # 需要通过API获取的网络音乐

        # 搜索索引
        self._extra_index_search = {}  # 额外搜索索引 {filepath: name}

        # 标签管理
        self.all_music_tags = {}  # 音乐标签缓存
        self._tag_generation_task = False  # 标签生成任务标志
        self._web_music_duration_cache = {}  # 网络音乐时长缓存（仅内存）

    def gen_all_music_list(self):
        """生成所有音乐列表

        扫描音乐目录，生成本地音乐列表和播放列表。
        """
        self.all_music = {}
        all_music_by_dir = {}

        # 扫描本地音乐目录
        local_musics = traverse_music_directory(
            self.music_path,
            depth=self.music_path_depth,
            exclude_dirs=self.exclude_dirs,
            support_extension=SUPPORT_MUSIC_TYPE,
        )

        for dir_name, files in local_musics.items():
            if len(files) == 0:
                continue

            # 处理目录名称
            if dir_name == os.path.basename(self.music_path):
                dir_name = "其他"
            if self.music_path != self.download_path and dir_name == os.path.basename(
                self.download_path
            ):
                dir_name = "下载"

            if dir_name not in all_music_by_dir:
                all_music_by_dir[dir_name] = {}

            for file in files:
                # 歌曲名字相同会覆盖
                filename = os.path.basename(file)
                (name, _) = os.path.splitext(filename)
                self.all_music[name] = file
                all_music_by_dir[dir_name][name] = True
                self.log.debug(f"gen_all_music_list {name}:{dir_name}:{file}")

        # 初始化播放列表（使用 OrderedDict 保持顺序）
        self.music_list = OrderedDict(
            {
                "临时搜索列表": [],
                "所有歌曲": [],
                "所有电台": [],
                "收藏": [],
                "全部": [],  # 包含所有歌曲和所有电台
                "下载": [],  # 下载目录下的
                "其他": [],  # 主目录下的
                "最近新增": [],  # 按文件时间排序
            }
        )

        # 最近新增(不包含网络歌单)
        self.music_list["最近新增"] = sorted(
            self.all_music.keys(),
            key=lambda x: os.path.getmtime(self.all_music[x]),
            reverse=True,
        )[: self.config.recently_added_playlist_len]

        # 补充网络歌单
        try:
            # NOTE: 函数内会更新 self.all_music, self.music_list；重建 self._all_radio
            self._append_music_list()
        except Exception as e:
            self.log.exception(f"Execption {e}")

        # 全部，所有歌曲（排除电台）
        self.music_list["全部"] = list(self.all_music.keys())
        self.music_list["所有歌曲"] = [
            name for name in self.all_music.keys() if name not in self._all_radio
        ]

        # 文件夹歌单
        for dir_name, musics in all_music_by_dir.items():
            self.music_list[dir_name] = list(musics.keys())

        # 歌单排序
        for _, play_list in self.music_list.items():
            play_list.sort(key=custom_sort_key)

        # 非自定义歌单
        self.default_music_list_names = list(self.music_list.keys())

        # 刷新自定义歌单
        self.refresh_custom_play_list()

        # 重建索引
        self._extra_index_search = {}
        for k, v in self.all_music.items():
            # 如果不是 url，则增加索引
            if not (v.startswith("http") or v.startswith("https")):
                self._extra_index_search[v] = k

        # all_music 更新，重建 tag（仅在事件循环启动后才会执行）
        self.try_gen_all_music_tag()

    def _append_music_list(self):
        """给歌单里补充网络歌单"""
        if not self.config.music_list_json:
            return

        self._all_radio = {}
        self._web_music_api = {}
        music_list = json.loads(self.config.music_list_json)

        try:
            for item in music_list:
                list_name = item.get("name")
                musics = item.get("musics")
                if (not list_name) or (not musics):
                    continue

                one_music_list = []
                for music in musics:
                    name = music.get("name")
                    url = music.get("url")
                    music_type = music.get("type")
                    if (not name) or (not url):
                        continue

                    self.all_music[name] = url
                    one_music_list.append(name)

                    # 处理电台列表
                    if music_type == "radio":
                        self._all_radio[name] = url
                    if music.get("api"):
                        self._web_music_api[name] = music

                self.log.debug(one_music_list)
                # 歌曲名字相同会覆盖
                self.music_list[list_name] = one_music_list

            if self._all_radio:
                self.music_list["所有电台"] = list(self._all_radio.keys())
        except Exception as e:
            self.log.exception(f"Execption {e}")

    def refresh_custom_play_list(self):
        """刷新自定义歌单"""
        try:
            # 删除旧的自定义歌单
            for k in list(self.music_list.keys()):
                if k not in self.default_music_list_names:
                    del self.music_list[k]

            # 合并新的自定义歌单
            custom_play_list = self.get_custom_play_list()
            for k, v in custom_play_list.items():
                self.music_list[k] = list(v)
        except Exception as e:
            self.log.exception(f"Execption {e}")

    def get_custom_play_list(self):
        """获取自定义播放列表

        Returns:
            dict: 自定义播放列表字典
        """
        if self.custom_play_list is None:
            self.custom_play_list = {}
            if self.config.custom_play_list_json:
                self.custom_play_list = json.loads(self.config.custom_play_list_json)
        return self.custom_play_list

    def save_custom_play_list(self, save_config_callback):
        """保存自定义播放列表

        Args:
            save_config_callback: 保存配置的回调函数
        """
        custom_play_list = self.get_custom_play_list()
        self.refresh_custom_play_list()
        self.config.custom_play_list_json = json.dumps(
            custom_play_list, ensure_ascii=False
        )
        save_config_callback()

    # ==================== 播放列表管理 ====================

    def play_list_add(self, name, save_config_callback):
        """新增歌单

        Args:
            name: 歌单名称
            save_config_callback: 保存配置的回调函数

        Returns:
            bool: 是否成功
        """
        custom_play_list = self.get_custom_play_list()
        if name in custom_play_list:
            return False
        custom_play_list[name] = []
        self.save_custom_play_list(save_config_callback)
        return True

    def play_list_del(self, name, save_config_callback):
        """移除歌单

        Args:
            name: 歌单名称
            save_config_callback: 保存配置的回调函数

        Returns:
            bool: 是否成功
        """
        custom_play_list = self.get_custom_play_list()
        if name not in custom_play_list:
            return False
        custom_play_list.pop(name)
        self.save_custom_play_list(save_config_callback)
        return True

    def play_list_update_name(self, oldname, newname, save_config_callback):
        """修改歌单名字

        Args:
            oldname: 旧歌单名称
            newname: 新歌单名称
            save_config_callback: 保存配置的回调函数

        Returns:
            bool: 是否成功
        """
        custom_play_list = self.get_custom_play_list()
        if oldname not in custom_play_list:
            self.log.info(f"旧歌单名字不存在 {oldname}")
            return False
        if newname in custom_play_list:
            self.log.info(f"新歌单名字已存在 {newname}")
            return False

        play_list = custom_play_list[oldname]
        custom_play_list.pop(oldname)
        custom_play_list[newname] = play_list
        self.save_custom_play_list(save_config_callback)
        return True

    def get_play_list_names(self):
        """获取所有自定义歌单名称

        Returns:
            list: 歌单名称列表
        """
        custom_play_list = self.get_custom_play_list()
        return list(custom_play_list.keys())

    def play_list_musics(self, name):
        """获取歌单中所有歌曲

        Args:
            name: 歌单名称

        Returns:
            tuple: (状态消息, 歌曲列表)
        """
        custom_play_list = self.get_custom_play_list()
        if name not in custom_play_list:
            return "歌单不存在", []
        play_list = custom_play_list[name]
        return "OK", play_list

    def play_list_update_music(self, name, music_list, save_config_callback):
        """歌单更新歌曲（覆盖）

        Args:
            name: 歌单名称
            music_list: 歌曲列表
            save_config_callback: 保存配置的回调函数

        Returns:
            bool: 是否成功
        """
        custom_play_list = self.get_custom_play_list()
        if name not in custom_play_list:
            # 歌单不存在则新建
            if not self.play_list_add(name, save_config_callback):
                return False

        play_list = []
        for music_name in music_list:
            if (music_name in self.all_music) and (music_name not in play_list):
                play_list.append(music_name)

        # 直接覆盖
        custom_play_list[name] = play_list
        self.save_custom_play_list(save_config_callback)
        return True

    def update_music_list_json(self, list_name, update_list, append=False):
        """
        更新配置的音乐歌单Json，如果歌单存在则根据 append：False:覆盖； True:追加
        Args:
            list_name: 更新的歌单名称
            update_list: 更新的歌单列表
            append: 追加歌曲，默认 False

        Returns:
            list: 转换后的音乐项目列表
        """
        # 更新配置中的音乐列表
        if self.config.music_list_json:
            music_list = json.loads(self.config.music_list_json)
        else:
            music_list = []

        # 检查是否已存在同名歌单
        existing_index = None
        for i, item in enumerate(music_list):
            if item.get("name") == list_name:
                existing_index = i
                break

        # 构建新歌单数据
        new_music_items = [
            {"name": item["name"], "url": item["url"], "type": item["type"]}
            for item in update_list
        ]

        if existing_index is not None:
            if append:
                # 追加模式：将新项目添加到现有歌单中，避免重复
                existing_musics = music_list[existing_index]["musics"]
                existing_names = {music["name"] for music in existing_musics}

                # 只添加不存在的项目
                for new_item in new_music_items:
                    if new_item["name"] not in existing_names:
                        existing_musics.append(new_item)

                music_list[existing_index]["musics"] = existing_musics
            else:
                # 覆盖模式：替换整个歌单
                music_list[existing_index] = {
                    "name": list_name,
                    "musics": new_music_items,
                }
        else:
            # 添加新歌单
            new_music_list = {"name": list_name, "musics": new_music_items}
            music_list.append(new_music_list)

        # 保存更新后的配置
        self.config.music_list_json = json.dumps(music_list, ensure_ascii=False)

    def play_list_add_music(self, name, music_list, save_config_callback):
        """歌单新增歌曲

        Args:
            name: 歌单名称
            music_list: 歌曲列表
            save_config_callback: 保存配置的回调函数

        Returns:
            bool: 是否成功
        """
        custom_play_list = self.get_custom_play_list()
        if name not in custom_play_list:
            # 歌单不存在则新建
            if not self.play_list_add(name, save_config_callback):
                return False

        play_list = custom_play_list[name]
        for music_name in music_list:
            if (music_name in self.all_music) and (music_name not in play_list):
                play_list.append(music_name)

        self.save_custom_play_list(save_config_callback)
        return True

    def play_list_del_music(self, name, music_list, save_config_callback):
        """歌单移除歌曲

        Args:
            name: 歌单名称
            music_list: 歌曲列表
            save_config_callback: 保存配置的回调函数

        Returns:
            bool: 是否成功
        """
        custom_play_list = self.get_custom_play_list()
        if name not in custom_play_list:
            return False

        play_list = custom_play_list[name]
        for music_name in music_list:
            if music_name in play_list:
                play_list.remove(music_name)

        self.save_custom_play_list(save_config_callback)
        return True

    # ==================== 音乐搜索 ====================

    def find_real_music_name(self, name, n):
        """模糊搜索音乐名称

        Args:
            name: 搜索关键词
            n: 返回结果数量

        Returns:
            list: 匹配的音乐名称列表
        """
        if not self.config.enable_fuzzy_match:
            self.log.debug("没开启模糊匹配")
            return []

        all_music_list = list(self.all_music.keys())
        real_names = find_best_match(
            name,
            all_music_list,
            cutoff=self.config.fuzzy_match_cutoff,
            n=n,
            extra_search_index=self._extra_index_search,
        )

        if real_names:
            if n > 1 and name not in real_names:
                # 模糊匹配模式，扩大范围再找，最后保留随机 n 个
                real_names = find_best_match(
                    name,
                    all_music_list,
                    cutoff=self.config.fuzzy_match_cutoff,
                    n=n * 2,
                    extra_search_index=self._extra_index_search,
                )
                random.shuffle(real_names)
                real_names = real_names[:n]
            elif name in real_names:
                # 可以精确匹配，限制只返回一个（保证网页端播放可用）
                real_names = [name]
            self.log.info(f"根据【{name}】找到歌曲【{real_names}】")
            return real_names

        self.log.info(f"没找到歌曲【{name}】")
        return []

    def find_real_music_list_name(self, list_name):
        """模糊搜索播放列表名称

        Args:
            list_name: 播放列表名称

        Returns:
            str: 匹配的播放列表名称
        """
        if not self.config.enable_fuzzy_match:
            self.log.debug("没开启模糊匹配")
            return list_name

        # 模糊搜一个播放列表（只需要一个，不需要 extra index）
        real_name = find_best_match(
            list_name,
            self.music_list,
            cutoff=self.config.fuzzy_match_cutoff,
            n=1,
        )[0]

        if real_name:
            self.log.info(f"根据【{list_name}】找到播放列表【{real_name}】")
            list_name = real_name
        else:
            self.log.info(f"没找到播放列表【{list_name}】")

        return list_name

    def searchmusic(self, name):
        """搜索音乐

        Args:
            name: 搜索关键词

        Returns:
            list: 搜索结果列表
        """
        all_music_list = list(self.all_music.keys())
        search_list = fuzzyfinder(name, all_music_list, self._extra_index_search)
        self.log.debug(f"searchmusic. name:{name} search_list:{search_list}")
        return search_list

    # ==================== 音乐信息 ====================

    def get_filename(self, name):
        """获取音乐文件路径

        Args:
            name: 音乐名称

        Returns:
            str: 文件路径，不存在返回空字符串
        """
        if name not in self.all_music:
            self.log.info(f"get_filename not in. name:{name}")
            return ""

        filename = self.all_music[name]
        self.log.info(f"try get_filename. filename:{filename}")

        if os.path.exists(filename):
            return filename
        return ""

    def is_music_exist(self, name):
        """判断本地音乐是否存在，网络歌曲不判断

        Args:
            name: 音乐名称

        Returns:
            bool: 是否存在
        """
        if name not in self.all_music:
            return False
        if self.is_web_music(name):
            return True
        filename = self.get_filename(name)
        if filename:
            return True
        return False

    def is_web_radio_music(self, name):
        """是否是网络电台

        Args:
            name: 音乐名称

        Returns:
            bool: 是否是网络电台
        """
        return name in self._all_radio

    # 是否是在线音乐
    @staticmethod
    def is_online_music(cur_playlist):
        # cur_playlist 开头是 '_online_' 则表示online
        return cur_playlist.startswith("_online_")

    def is_web_music(self, name):
        """是否是网络歌曲

        Args:
            name: 音乐名称

        Returns:
            bool: 是否是网络歌曲
        """
        if name not in self.all_music:
            return False
        url = self.all_music[name]
        return url.startswith(("http://", "https://"))

    def is_need_use_play_music_api(self, name):
        """是否是需要通过api获取播放链接的网络歌曲

        Args:
            name: 音乐名称

        Returns:
            bool: 是否需要通过API获取
        """
        return name in self._web_music_api

    # ==================== 标签管理 ====================

    async def get_music_tags(self, name):
        """获取音乐标签信息

        Args:
            name: 音乐名称

        Returns:
            dict: 标签信息字典
        """
        tags = copy.copy(self.all_music_tags.get(name, asdict(Metadata())))
        picture = tags["picture"]

        if picture:
            if picture.startswith(self.config.picture_cache_path):
                picture = picture[len(self.config.picture_cache_path) :]
            picture = picture.replace("\\", "/")
            if picture.startswith("/"):
                picture = picture[1:]
            encoded_name = urllib.parse.quote(picture)
            tags["picture"] = try_add_access_control_param(
                self.config,
                f"{self.hostname}:{self.public_port}/picture/{encoded_name}",
            )

        if self.is_web_music(name):
            try:
                duration = await self.get_music_duration(name)
                if duration > 0:
                    tags["duration"] = duration
            except Exception as e:
                self.log.exception(f"获取网络音乐 {name} 时长失败: {e}")
        return tags

    def set_music_tag(self, name, info):
        """修改标签信息

        Args:
            name: 音乐名称
            info: 标签信息对象

        Returns:
            str: 操作结果消息
        """
        if self._tag_generation_task:
            self.log.info("tag 更新中，请等待")
            return "Tag generation task running"

        tags = copy.copy(self.all_music_tags.get(name, asdict(Metadata())))
        tags["title"] = info.title
        tags["artist"] = info.artist
        tags["album"] = info.album
        tags["year"] = info.year
        tags["genre"] = info.genre
        tags["lyrics"] = info.lyrics

        file_path = self.all_music[name]
        if info.picture:
            tags["picture"] = save_picture_by_base64(
                info.picture, self.config.picture_cache_path, file_path
            )

        if self.config.enable_save_tag and (not self.is_web_music(name)):
            set_music_tag_to_file(file_path, Metadata(tags))

        self.all_music_tags[name] = tags
        self.try_save_tag_cache()
        return "OK"

    async def get_music_duration(self, name: str) -> float:
        """获取歌曲时长

        优先从缓存中读取，如果缓存中没有则获取并缓存
        注意：此方法不处理在线音乐，在线音乐的时长获取在 music_url 中处理

        Args:
            name: 歌曲名称

        Returns:
            float: 歌曲时长（秒），失败返回 0
        """
        # 检查歌曲是否存在
        if name not in self.all_music:
            self.log.warning(f"歌曲 {name} 不存在")
            return 0

        # 电台直接返回 0
        if self.is_web_radio_music(name):
            self.log.info(f"电台 {name} 不会有播放时长")
            return 0

        # 网络音乐：使用内存缓存
        if self.is_web_music(name):
            # 先检查内存缓存
            if name in self._web_music_duration_cache:
                duration = self._web_music_duration_cache[name]
                self.log.debug(f"从内存缓存读取网络音乐 {name} 时长: {duration} 秒")
                return duration

            # 缓存中没有，获取时长
            try:
                url = self.all_music[name]
                duration, _ = await get_web_music_duration(url, self.config)
                self.log.info(f"网络音乐 {name} 时长: {duration} 秒")

                # 存入内存缓存（不持久化）
                if duration > 0:
                    self._web_music_duration_cache[name] = duration
                    self.log.info(f"已缓存网络音乐 {name} 时长到内存: {duration} 秒")

                return duration
            except Exception as e:
                self.log.exception(f"获取网络音乐 {name} 时长失败: {e}")
                return 0

        # 本地音乐：使用持久化缓存
        # 先检查缓存中是否有时长信息
        if name in self.all_music_tags:
            duration = self.all_music_tags[name].get("duration", 0)
            if duration > 0:
                self.log.debug(f"从缓存读取本地音乐 {name} 时长: {duration} 秒")
                return duration

        # 缓存中没有，需要获取时长
        duration = 0
        try:
            filename = self.all_music[name]
            if os.path.exists(filename):
                duration = await get_local_music_duration(filename, self.config)
                self.log.info(f"本地音乐 {name} 时长: {duration} 秒")
            else:
                self.log.warning(f"本地音乐文件 {filename} 不存在")

            # 获取到时长后，更新到缓存并持久化
            if duration > 0:
                if name not in self.all_music_tags:
                    self.all_music_tags[name] = asdict(Metadata())
                self.all_music_tags[name]["duration"] = duration
                # 保存缓存
                self.try_save_tag_cache()
                self.log.info(f"已缓存本地音乐 {name} 时长: {duration} 秒")

        except Exception as e:
            self.log.exception(f"获取本地音乐 {name} 时长失败: {e}")

        return duration

    def refresh_music_tag(self):
        """刷新音乐标签（给前端调用）"""
        if not self.ensure_single_thread_for_tag():
            return

        filename = self.config.tag_cache_path
        if filename is not None:
            # 清空 cache
            with open(filename, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            self.log.info("刷新：已清空 tag cache")
        else:
            self.log.info("刷新：tag cache 未启用")

        # TODO: 优化性能？
        # TODO 如何安全的清空 picture_cache_path
        self.all_music_tags = {}  # 需要清空内存残留
        self.clear_web_music_duration_cache()  # 清空网络音乐时长缓存
        self.try_gen_all_music_tag()
        self.log.info("刷新：已启动重建 tag cache")

    def try_load_from_tag_cache(self):
        """从缓存加载标签

        Returns:
            dict: 标签缓存字典
        """
        filename = self.config.tag_cache_path
        tag_cache = {}

        try:
            if filename is not None:
                if os.path.exists(filename):
                    with open(filename, encoding="utf-8") as f:
                        tag_cache = json.load(f)
                    self.log.info(f"已从【{filename}】加载 tag cache")
                else:
                    self.log.info(f"【{filename}】tag cache 已启用，但文件不存在")
            else:
                self.log.info("加载：tag cache 未启用")
        except Exception as e:
            self.log.exception(f"Execption {e}")

        return tag_cache

    def try_save_tag_cache(self):
        """保存标签缓存"""
        filename = self.config.tag_cache_path
        if filename is not None:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(self.all_music_tags, f, ensure_ascii=False, indent=2)
            self.log.info(f"保存：tag cache 已保存到【{filename}】")
        else:
            self.log.info("保存：tag cache 未启用")

    def ensure_single_thread_for_tag(self):
        """确保标签生成任务单线程执行

        Returns:
            bool: 是否可以执行新任务
        """
        if self._tag_generation_task:
            self.log.info("tag 更新中，请等待")
        return not self._tag_generation_task

    def try_gen_all_music_tag(self, only_items=None):
        """尝试生成所有音乐标签

        Args:
            only_items: 仅更新指定的音乐项，None表示更新全部
        """
        if self.ensure_single_thread_for_tag():
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # 没有运行中的事件循环，跳过
                self.log.info("协程时间循环未启动")
                return
            asyncio.ensure_future(self._gen_all_music_tag(only_items))
            self.log.info("启动后台构建 tag cache")

    async def _gen_all_music_tag(self, only_items=None):
        """生成所有音乐标签（异步）

        Args:
            only_items: 仅更新指定的音乐项，None表示更新全部
        """
        self._tag_generation_task = True
        if only_items is None:
            only_items = self.all_music  # 默认更新全部

        all_music_tags = self.try_load_from_tag_cache()
        all_music_tags.update(self.all_music_tags)  # 保证最新

        ignore_tag_absolute_dirs = self.config.get_ignore_tag_dirs()
        self.log.info(f"ignore_tag_absolute_dirs: {ignore_tag_absolute_dirs}")

        for name, file_or_url in only_items.items():
            start = time.perf_counter()
            if name not in all_music_tags:
                try:
                    if os.path.exists(file_or_url) and not_in_dirs(
                        file_or_url, ignore_tag_absolute_dirs
                    ):
                        all_music_tags[name] = extract_audio_metadata(
                            file_or_url, self.config.picture_cache_path
                        )
                    else:
                        self.log.info(f"{name}/{file_or_url} 无法更新 tag")
                except BaseException as e:
                    self.log.exception(f"{e} {file_or_url} error {type(file_or_url)}!")

            # 获取并缓存歌曲时长（仅本地音乐）
            if name in all_music_tags and "duration" not in all_music_tags[name]:
                # 跳过网络音乐的时长获取
                if not self.is_web_music(name):
                    try:
                        duration = await self.get_music_duration(name)
                        if duration > 0:
                            all_music_tags[name]["duration"] = duration
                    except Exception as e:
                        self.log.warning(f"获取歌曲 {name} 时长失败: {e}")

            if (time.perf_counter() - start) < 1:
                await asyncio.sleep(0.001)
            else:
                # 处理一首歌超过1秒，则等1秒，解决挂载网盘卡死的问题
                await asyncio.sleep(1)

        # 全部更新结束后，一次性赋值
        self.all_music_tags = all_music_tags
        # 刷新 tag cache
        self.try_save_tag_cache()
        self._tag_generation_task = False
        self.log.info("tag 更新完成")

    # ==================== 辅助方法 ====================

    def get_music_list(self):
        """获取所有播放列表

        Returns:
            dict: 播放列表字典
        """
        return self.music_list

    def get_all_music(self):
        """获取所有音乐

        Returns:
            dict: 所有音乐字典
        """
        return self.all_music

    def get_web_music_api(self):
        """获取网络音乐API配置

        Returns:
            dict: 网络音乐API配置字典
        """
        return self._web_music_api

    def get_all_radio(self):
        """获取所有电台

        Returns:
            dict: 所有电台字典
        """
        return self._all_radio

    def clear_web_music_duration_cache(self):
        """清空网络音乐时长缓存

        清空内存中的网络音乐时长缓存，不影响本地音乐的缓存
        """
        self._web_music_duration_cache = {}
        self.log.info("已清空网络音乐时长缓存")
