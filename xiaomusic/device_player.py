"""设备播放控制模块

负责单个设备的播放控制、下载管理、TTS处理等功能。
"""

import asyncio
import copy
import json
import os
import random
import time
from typing import TYPE_CHECKING

from miservice import miio_command

from xiaomusic.config import Device

if TYPE_CHECKING:
    from xiaomusic.xiaomusic import XiaoMusic
from xiaomusic.const import (
    NEED_USE_PLAY_MUSIC_API,
    PLAY_TYPE_ALL,
    PLAY_TYPE_ONE,
    PLAY_TYPE_RND,
    PLAY_TYPE_SEQ,
    PLAY_TYPE_SIN,
    TTS_COMMAND,
)
from xiaomusic.events import DEVICE_CONFIG_CHANGED
from xiaomusic.utils.file_utils import chmodfile
from xiaomusic.utils.text_utils import custom_sort_key, list2str


class XiaoMusicDevice:
    """设备播放控制类

    负责单个小爱设备的播放控制，包括：
    - 播放控制（播放、暂停、上一首、下一首）
    - 播放列表管理
    - 下载管理
    - TTS（文字转语音）
    - 定时器管理
    - 设备状态管理
    """

    def __init__(self, xiaomusic: "XiaoMusic", device: Device, group_name: str):
        """初始化设备播放控制器

        Args:
            xiaomusic: XiaoMusic 主类实例
            device: 设备配置对象
            group_name: 设备组名
        """
        self.group_name = group_name
        self.device = device
        self.config = xiaomusic.config
        self.device_id = device.device_id
        self.log = xiaomusic.log
        self.xiaomusic = xiaomusic
        self.auth_manager = xiaomusic.auth_manager
        self.ffmpeg_location = self.config.ffmpeg_location
        self.event_bus = getattr(xiaomusic, "event_bus", None)

        self._download_proc = None  # 下载对象
        self._next_timer = None
        self.is_playing = False
        # 播放进度
        self._start_time = 0
        self._duration = 0
        self._paused_time = 0
        self._play_failed_cnt = 0

        self._play_list = []

        # 关机定时器
        self._stop_timer = None
        self._last_cmd = None
        self.update_playlist()

        # 添加歌曲定时器
        self._add_song_timer = None
        # TTS 播放定时器
        self._tts_timer = None

    @property
    def did(self):
        """获取设备DID"""
        return self.device.did

    @property
    def hardware(self):
        """获取设备硬件型号"""
        return self.device.hardware

    def get_cur_music(self):
        """获取当前播放的音乐名称"""
        return self.device.cur_music

    def get_offset_duration(self):
        """获取播放偏移量和总时长"""
        duration = self._duration
        if not self.is_playing:
            return 0, duration
        offset = time.time() - self._start_time - self._paused_time
        return offset, duration

    # 自动搜歌并加入当前歌单
    async def auto_add_song(self, cur_list_name, sleep_sec=20):
        if self.xiaomusic.js_plugin_manager is None:
            return
        # 是否启用自动添加
        auto_add_song = self.xiaomusic.js_plugin_manager.get_auto_add_song()
        is_online = self.xiaomusic.music_library.is_online_music(cur_list_name)
        # 歌单循环方式：播放全部
        play_all = self.device.play_type == PLAY_TYPE_ALL
        # 当前播放的歌曲是歌单中的最后一曲
        is_last_song = False
        cur_playlist = self._play_list
        cur_music = self.get_cur_music()
        play_list_len = len(cur_playlist)
        if play_list_len != 0:
            index = self._play_list.index(cur_music)
            is_last_song = index == play_list_len - 1
        # 四个条件都满足，才自动添加下一首
        if auto_add_song and is_online and play_all and is_last_song:
            await self._add_singer_song(cur_list_name, cur_music, sleep_sec)

    # 启用延时器，搜索当前歌曲歌手的其他不在歌单内的歌曲
    async def _add_singer_song(self, list_name, cur_music, sleep_sec):
        # 取消之前的定时器（如果存在）
        # self.cancel_add_song_timer()
        # 以 '-' 分割，获取歌手名称
        singer_name = cur_music.split("-")[1]
        # 创建新的定时器，20秒后执行
        self._add_song_timer = asyncio.create_task(
            self._delayed_add_singer_song(list_name, singer_name, sleep_sec)
        )

    async def _delayed_add_singer_song(self, list_name, singer_name, sleep_sec):
        """延迟执行添加歌手歌曲的操作"""
        try:
            await asyncio.sleep(sleep_sec)
            await self.xiaomusic.add_singer_song(list_name, singer_name)
        except asyncio.CancelledError:
            return
        finally:
            # 执行完毕后清除定时器引用
            if self._add_song_timer:  # 确保是当前任务
                self._add_song_timer = None

    def cancel_add_song_timer(self):
        """取消添加歌曲的定时器"""
        self.log.info("添加歌手歌曲的定时器已被取消")
        if self._add_song_timer:
            self._add_song_timer.cancel()
            self._add_song_timer = None
            return True
        return False

    async def play_music(self, name):
        """播放音乐（外部接口）"""
        return await self._playmusic(name)

    def update_playlist(self, reorder=True):
        """初始化/更新播放列表

        Args:
            reorder: 是否重新排序
        """
        # 没有重置 list 且非初始化
        if self.device.cur_playlist == "临时搜索列表" and len(self._play_list) > 0:
            # 更新总播放列表，为了UI显示
            self.xiaomusic.music_library.music_list["临时搜索列表"] = copy.copy(
                self._play_list
            )
        elif (
            self.device.cur_playlist == "临时搜索列表" and len(self._play_list) == 0
        ) or (self.device.cur_playlist not in self.xiaomusic.music_library.music_list):
            self.device.cur_playlist = "全部"
        else:
            pass  # 指定了已知的播放列表名称

        list_name = self.device.cur_playlist
        self._play_list = copy.copy(self.xiaomusic.music_library.music_list[list_name])

        if reorder:
            if self.device.play_type == PLAY_TYPE_RND:
                random.shuffle(self._play_list)
                self.log.info(
                    f"随机打乱 {list_name} {list2str(self._play_list, self.config.verbose)}"
                )
            else:
                self._play_list.sort(key=custom_sort_key)
                self.log.info(
                    f"没打乱 {list_name} {list2str(self._play_list, self.config.verbose)}"
                )
        else:
            self.log.info(
                f"更新 {list_name} {list2str(self._play_list, self.config.verbose)}"
            )

    async def play(self, name="", search_key="", exact=True, update_cur_list=False):
        """播放歌曲（外部接口）"""
        self._last_cmd = "play"
        return await self._play(
            name=name,
            search_key=search_key,
            exact=exact,
            update_cur_list=update_cur_list,
        )

    async def _check_and_download_music(self, name, search_key, allow_download):
        """检查本地歌曲是否存在，如果不存在则根据参数决定是否下载

        Args:
            name: 歌曲名称
            search_key: 搜索关键词
            allow_download: 是否允许下载

        Returns:
            bool: True表示歌曲存在或下载成功，False表示歌曲不存在且不允许下载
        """
        if self.xiaomusic.music_library.is_music_exist(name):
            return True

        self.log.info(f"本地不存在歌曲{name}")

        # 根据 allow_download 参数决定行为
        if not allow_download:
            # playlocal 的行为：不下载，直接提示
            await self.do_tts(f"本地不存在歌曲{name}")
            return False

        # _play 的行为：检查配置决定是否下载
        if self.config.disable_download:
            await self.do_tts(f"本地不存在歌曲{name}")
            return False

        # 下载歌曲
        await self.download(search_key, name)
        # 把文件插入到播放列表里
        await self.add_download_music(name)
        return True

    async def _play_internal(
        self,
        name="",
        search_key="",
        exact=True,
        update_cur_list=False,
        allow_download=True,
    ):
        """播放歌曲的内部统一实现

        Args:
            name: 歌曲名称
            search_key: 搜索关键词
            exact: 是否精确匹配
            update_cur_list: 是否更新当前列表
            allow_download: 是否允许下载（True: _play行为，False: playlocal行为）
        """
        # 初始检查逻辑
        if not search_key and not name:
            if self.check_play_next():
                await self._play_next()
                return
            else:
                name = self.get_cur_music()

        self.log.info(
            f"play_internal. search_key:{search_key} name:{name} exact:{exact} allow_download:{allow_download}"
        )

        if not name:
            self.log.info(f"没有歌曲播放了 name:{name} search_key:{search_key}")
            return

        # 精确匹配分支
        if exact:
            # 检查本地是否存在歌曲，不存在则根据参数决定是否下载
            if not await self._check_and_download_music(
                name, search_key, allow_download
            ):
                return

            # 播放歌曲
            await self._playmusic(name)
            return

        # 模糊搜索分支
        names = self.xiaomusic.find_real_music_name(
            name, n=self.config.search_music_count
        )
        self.log.info(f"play_internal. names:{names} {len(names)}")

        if not names:
            # 检查本地是否存在歌曲，不存在则根据参数决定是否下载
            if not await self._check_and_download_music(
                name, search_key, allow_download
            ):
                return

            # 播放歌曲
            await self._playmusic(name)
            return

        # 处理搜索结果
        if len(names) > 1:  # 大于一首歌才更新
            self._play_list = names
            self.device.cur_playlist = "临时搜索列表"
            self.update_playlist()
        else:  # 只有一首歌，append
            if names[0] not in self._play_list:
                self._play_list = self._play_list + names
                self.device.cur_playlist = "临时搜索列表"
                self.update_playlist(reorder=False)

        name = names[0]
        if update_cur_list and (name not in self._play_list):
            # 根据当前歌曲匹配歌曲列表
            self.device.cur_playlist = self.find_cur_playlist(name)
            self.update_playlist()

        self.log.debug(
            f"当前播放列表为：{list2str(self._play_list, self.config.verbose)}"
        )
        # 本地存在歌曲，直接播放
        await self._playmusic(name)

    async def _play(self, name="", search_key="", exact=True, update_cur_list=False):
        """播放歌曲（内部实现）- 支持下载"""
        return await self._play_internal(
            name=name,
            search_key=search_key,
            exact=exact,
            update_cur_list=update_cur_list,
            allow_download=True,
        )

    async def play_next(self):
        """播放下一首（外部接口）"""
        return await self._play_next()

    async def _play_next(self):
        """播放下一首（内部实现）"""
        self.log.info("开始播放下一首")
        name = self.get_cur_music()
        if (
            self.device.play_type == PLAY_TYPE_ALL
            or self.device.play_type == PLAY_TYPE_RND
            or self.device.play_type == PLAY_TYPE_SEQ
            or name == ""
            or (
                (name not in self._play_list) and self.device.play_type != PLAY_TYPE_ONE
            )
        ):
            name = self.get_next_music()
            self.log.info(f"get_next_music {name}")
        self.log.info(f"_play_next. name:{name}, cur_music:{self.get_cur_music()}")
        if name == "":
            self.log.info("本地没有歌曲")
            return
        await self._play(name, exact=True)

    async def play_prev(self):
        """播放上一首（外部接口）"""
        return await self._play_prev()

    async def _play_prev(self):
        """播放上一首（内部实现）"""
        self.log.info("开始播放上一首")
        name = self.get_cur_music()
        if (
            self.device.play_type == PLAY_TYPE_ALL
            or self.device.play_type == PLAY_TYPE_RND
            or self.device.play_type == PLAY_TYPE_SEQ
            or name == ""
            or (name not in self._play_list)
        ):
            name = self.get_prev_music()
        self.log.info(f"_play_prev. name:{name}, cur_music:{self.get_cur_music()}")
        if name == "":
            await self.do_tts("本地没有歌曲")
            return
        await self._play(name, exact=True)

    async def playlocal(self, name="", exact=True, update_cur_list=False):
        """播放本地歌曲 - 不下载"""
        self._last_cmd = "playlocal"
        return await self._play_internal(
            name=name,
            search_key="",
            exact=exact,
            update_cur_list=update_cur_list,
            allow_download=False,
        )

    async def _playmusic(self, name):
        """播放音乐的核心实现"""
        # 取消组内所有的下一首歌曲的定时器
        await self.cancel_group_next_timer()

        self.is_playing = True
        self.device.cur_music = name
        self.device.playlist2music[self.device.cur_playlist] = name
        cur_playlist = self.device.cur_playlist
        self.log.info(f"cur_music {self.get_cur_music()}")
        url, _ = await self.xiaomusic.music_library.get_music_url(name)
        await self.group_force_stop_xiaoai()
        self.log.info(f"播放 {url}")

        results = await self.group_player_play(url, name)
        if all(ele is None for ele in results):
            self.log.info(f"播放 {name} 失败. 失败次数: {self._play_failed_cnt}")
            await asyncio.sleep(1)
            if (
                self.is_playing
                and self._last_cmd != "stop"
                and self._play_failed_cnt < 10
            ):
                self._play_failed_cnt = self._play_failed_cnt + 1
                await self._play_next()
            return
        # 重置播放失败次数
        self._play_failed_cnt = 0

        self.log.info(f"【{name}】已经开始播放了")

        # 记录歌曲开始播放的时间
        self._start_time = time.time()
        self._paused_time = 0

        sec = await self.xiaomusic.music_library.get_music_duration(name)
        # 存储真实歌曲时长
        self._duration = sec
        await self.xiaomusic.analytics.send_play_event(name, sec, self.hardware)

        # 设置下一首歌曲的播放定时器
        if sec <= 0.1:
            self.log.info(f"【{name}】不会设置下一首歌的定时器")
            return

        # 计算自动添加歌曲的延迟时间，为当前歌曲时长的一半，但不超过60秒
        if sec > 30:
            sleep_sec = min(sec / 2, 60)
            await self.auto_add_song(cur_playlist, sleep_sec)

        # 计算获取时长的执行耗时
        duration_execution_time = time.time() - self._start_time
        self.log.info(f"获取音乐时长耗时: {duration_execution_time:.3f} 秒")
        # 调整定时器时长，减去获取音乐时长的执行时间
        adjusted_sec = sec + self.config.delay_sec - duration_execution_time
        # 确保调整后的时长不会过小，最小保留0.1秒
        adjusted_sec = max(adjusted_sec, 0.1)
        self.log.info(
            f"原始歌曲时长: {sec:.3f} 秒, 调整后定时器时长: {adjusted_sec:.3f} 秒"
        )
        await self.set_next_music_timeout(adjusted_sec)
        # 发布设备配置变更事件
        if self.event_bus:
            self.event_bus.publish(DEVICE_CONFIG_CHANGED)

    async def do_tts(self, value):
        """执行TTS（文字转语音）"""
        self.log.info(f"try do_tts value:{value}")
        if not value:
            self.log.info("do_tts no value")
            return

        # await self.group_force_stop_xiaoai()
        await self.text_to_speech(value)

        # 最大等8秒
        sec = min(8, int(len(value) / 3))
        await asyncio.sleep(sec)
        self.log.info(f"do_tts ok. cur_music:{self.get_cur_music()}")
        await self.check_replay()

    async def force_stop_xiaoai(self, device_id):
        """强制停止小爱播放"""
        try:
            ret = await self.auth_manager.mina_service.player_pause(device_id)
            self.log.info(
                f"force_stop_xiaoai player_pause device_id:{device_id} ret:{ret}"
            )
            await self.stop_if_xiaoai_is_playing(device_id)
        except Exception as e:
            self.log.warning(f"Execption {e}")

    async def get_if_xiaoai_is_playing(self):
        """检查小爱是否正在播放"""
        playing_info = await self.auth_manager.mina_service.player_get_status(
            self.device_id
        )
        self.log.info(playing_info)
        # WTF xiaomi api
        is_playing = (
            json.loads(playing_info.get("data", {}).get("info", "{}")).get("status", -1)
            == 1
        )
        return is_playing

    async def stop_if_xiaoai_is_playing(self, device_id):
        """如果小爱正在播放则停止"""
        is_playing = await self.get_if_xiaoai_is_playing()
        if is_playing or self.config.enable_force_stop:
            # stop it
            ret = await self.auth_manager.mina_service.player_stop(device_id)
            self.log.info(
                f"stop_if_xiaoai_is_playing player_stop device_id:{device_id} enable_force_stop:{self.config.enable_force_stop} ret:{ret}"
            )

    def isdownloading(self):
        """检查是否正在下载"""
        if not self._download_proc:
            return False

        if self._download_proc.returncode is not None:
            self.log.info(
                f"Process exited with returncode:{self._download_proc.returncode}"
            )
            return False

        self.log.info("Download Process is still running.")
        return True

    async def download(self, search_key, name):
        """下载歌曲"""
        if self._download_proc:
            try:
                self._download_proc.kill()
            except ProcessLookupError:
                pass

        sbp_args = (
            "yt-dlp",
            f"{self.config.search_prefix}{search_key}",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--paths",
            self.config.download_path,
            "-o",
            f"{name}.mp3",
            "--ffmpeg-location",
            f"{self.ffmpeg_location}",
            "--no-playlist",
        )

        if self.config.proxy:
            sbp_args += ("--proxy", f"{self.config.proxy}")

        if self.config.enable_yt_dlp_cookies:
            sbp_args += ("--cookies", f"{self.config.yt_dlp_cookies_path}")

        if self.config.loudnorm:
            sbp_args += ("--postprocessor-args", f"-af {self.config.loudnorm}")

        cmd = " ".join(sbp_args)
        self.log.info(f"download cmd: {cmd}")
        self._download_proc = await asyncio.create_subprocess_exec(*sbp_args)
        await self.do_tts(f"正在下载歌曲{search_key}")
        self.log.info(f"正在下载中 {search_key} {name}")
        await self._download_proc.wait()
        # 下载完成后，修改文件权限
        file_path = os.path.join(self.config.download_path, f"{name}.mp3")
        chmodfile(file_path)

    async def check_replay(self):
        """检查是否需要继续播放被打断的歌曲"""
        if self.is_playing and not self.isdownloading():
            if not self.config.continue_play:
                # 重新播放歌曲
                self.log.info("现在重新播放歌曲")
                await self._play()
            else:
                self.log.info(
                    f"继续播放歌曲. self.config.continue_play:{self.config.continue_play}"
                )
        else:
            self.log.info(
                f"不会继续播放歌曲. isplaying:{self.is_playing} isdownloading:{self.isdownloading()}"
            )

    async def add_download_music(self, name):
        """把下载的音乐加入播放列表"""
        filepath = os.path.join(self.config.download_path, f"{name}.mp3")
        self.xiaomusic.music_library.all_music[name] = filepath
        # 应该很快，阻塞运行
        await self.xiaomusic.music_library._gen_all_music_tag({name: filepath})
        if name not in self._play_list:
            self._play_list.append(name)
            self.log.info(f"add_download_music add_music {name}")
            self.log.debug(self._play_list)

    def get_music(self, direction="next"):
        """获取下一首或上一首音乐"""
        play_list_len = len(self._play_list)
        if play_list_len == 0:
            self.log.warning("当前播放列表没有歌曲")
            return ""
        index = 0
        try:
            index = self._play_list.index(self.get_cur_music())
        except ValueError:
            pass

        if play_list_len == 1:
            new_index = index  # 当只有一首歌曲时保持当前索引不变
        else:
            if direction == "next":
                new_index = index + 1
                if (
                    self.device.play_type == PLAY_TYPE_SEQ
                    and new_index >= play_list_len
                ):
                    self.log.info("顺序播放结束")
                    return ""
                if new_index >= play_list_len:
                    new_index = 0
            elif direction == "prev":
                new_index = index - 1
                if new_index < 0:
                    new_index = play_list_len - 1
            else:
                self.log.error("无效的方向参数")
                return ""

        name = self._play_list[new_index]
        if not self.xiaomusic.music_library.is_music_exist(name):
            self._play_list.pop(new_index)
            self.log.info(f"pop not exist music: {name}")
            return self.get_music(direction)
        return name

    def get_next_music(self):
        """获取下一首音乐"""
        return self.get_music(direction="next")

    def get_prev_music(self):
        """获取上一首音乐"""
        return self.get_music(direction="prev")

    def check_play_next(self):
        """判断是否需要播放下一首歌曲"""
        # 当前歌曲不在当前播放列表
        if self.get_cur_music() not in self._play_list:
            self.log.info(f"当前歌曲 {self.get_cur_music()} 不在当前播放列表")
            return True

        # 当前没我在播放的歌曲
        if self.get_cur_music() == "":
            self.log.info("当前没我在播放的歌曲")
            return True
        else:
            # 当前播放的歌曲不存在了
            if not self.xiaomusic.music_library.is_music_exist(self.get_cur_music()):
                self.log.info(f"当前播放的歌曲 {self.get_cur_music()} 不存在了")
                return True
        return False

    async def text_to_speech(self, value):
        """文字转语音"""
        try:
            # 检查是否配置了 edge-tts 语音角色
            if self.config.edge_tts_voice:
                await self._text_to_speech_edge_tts(value)
            else:
                # 使用原有的 TTS 逻辑
                # 有 tts command 优先使用 tts command 说话
                if self.hardware in TTS_COMMAND:
                    tts_cmd = TTS_COMMAND[self.hardware]
                    self.log.info("Call MiIOService tts.")
                    value = value.replace(" ", ",")  # 不能有空格
                    await miio_command(
                        self.auth_manager.miio_service,
                        self.did,
                        f"{tts_cmd} {value}",
                    )
                else:
                    self.log.debug("Call MiNAService tts.")
                    await self.auth_manager.mina_service.text_to_speech(
                        self.device_id, value
                    )
        except Exception as e:
            self.log.exception(f"Execption {e}")

    async def _text_to_speech_edge_tts(self, value):
        """使用 edge-tts 进行文字转语音"""
        from xiaomusic.utils.music_utils import get_local_music_duration
        from xiaomusic.utils.network_utils import text_to_mp3

        self.log.info(f"_text_to_speech_edge_tts {value}")
        try:
            # 取消之前的 TTS 定时器
            if self._tts_timer:
                self._tts_timer.cancel()
                self._tts_timer = None
                self.log.info("已取消之前的 TTS 定时器")

            # 使用 edge-tts 生成 MP3 文件
            self.log.info(
                f"使用 edge-tts 生成语音: {value}, voice: {self.config.edge_tts_voice}"
            )
            mp3_path = await text_to_mp3(
                text=value,
                save_dir=self.config.temp_dir,
                voice=self.config.edge_tts_voice,
            )
            self.log.info(f"edge-tts 生成的文件路径: {mp3_path}")

            # 生成播放 URL
            url = self.xiaomusic.music_library._get_file_url(mp3_path)
            self.log.info(f"TTS 播放 URL: {url}")

            # 播放 TTS 音频
            await self.group_player_play(url)

            # 获取 MP3 时长
            duration = await get_local_music_duration(mp3_path, self.config)
            self.log.info(f"TTS 音频时长: {duration} 秒")

            # 创建定时器，时长到后停止
            if duration > 0:

                async def _tts_timeout():
                    await asyncio.sleep(duration)
                    try:
                        self.log.info("TTS 播放定时器时间到")
                        current_timer = self._tts_timer
                        if current_timer:
                            # 取消任务（防止任务被重复触发，即使sleep已结束）
                            current_timer.cancel()
                            try:
                                await current_timer  # 等待任务取消完成，避免警告
                            except asyncio.CancelledError:
                                pass
                            # 再置空引用
                            self._tts_timer = None
                            await self.stop(arg1="notts")
                    except Exception as e:
                        self.log.error(f"TTS 定时器异常: {e}")

                self._tts_timer = asyncio.create_task(_tts_timeout())
                self.log.info(f"已设置 TTS 定时器，{duration} 秒后停止")

        except Exception as e:
            self.log.exception(f"edge-tts 播放失败: {e}")

    async def group_player_play(self, url, name=""):
        """同一组设备播放"""
        device_id_list = self.xiaomusic.device_manager.get_group_device_id_list(
            self.group_name
        )
        tasks = [
            self.play_one_url(device_id, url, name) for device_id in device_id_list
        ]
        results = await asyncio.gather(*tasks)
        self.log.info(f"group_player_play {url} {device_id_list} {results}")
        return results

    async def play_one_url(self, device_id, url, name):
        """在单个设备上播放URL"""
        ret = None
        try:
            audio_id = await self._get_audio_id(name)
            if self.config.continue_play:
                ret = await self.auth_manager.mina_service.play_by_music_url(
                    device_id, url, _type=1, audio_id=audio_id
                )
                self.log.info(
                    f"play_one_url continue_play device_id:{device_id} ret:{ret} url:{url} audio_id:{audio_id}"
                )
            elif self.config.use_music_api or (
                self.hardware in NEED_USE_PLAY_MUSIC_API
            ):
                ret = await self.auth_manager.mina_service.play_by_music_url(
                    device_id, url, audio_id=audio_id
                )
                self.log.info(
                    f"play_one_url play_by_music_url device_id:{device_id} ret:{ret} url:{url} audio_id:{audio_id}"
                )
            else:
                ret = await self.auth_manager.mina_service.play_by_url(device_id, url)
                self.log.info(
                    f"play_one_url play_by_url device_id:{device_id} ret:{ret} url:{url}"
                )
        except Exception as e:
            self.log.exception(f"Execption {e}")
        return ret

    async def _get_audio_id(self, name):
        """获取音频ID"""
        audio_id = self.config.use_music_audio_id or "1582971365183456177"
        if not (self.config.use_music_api or self.config.continue_play):
            return str(audio_id)
        try:
            params = {
                "query": name,
                "queryType": 1,
                "offset": 0,
                "count": 6,
                "timestamp": int(time.time_ns() / 1000),
            }
            response = await self.auth_manager.mina_service.mina_request(
                "/music/search", params
            )
            for song in response["data"]["songList"]:
                if song["originName"] == "QQ音乐":
                    audio_id = song["audioID"]
                    break
            # 没找到QQ音乐的歌曲，取第一个
            if audio_id == 1582971365183456177:
                audio_id = response["data"]["songList"][0]["audioID"]
            self.log.debug(f"_get_audio_id. name: {name} songId:{audio_id}")
        except Exception as e:
            self.log.error(f"_get_audio_id {e}")
        return str(audio_id)

    async def reset_timer_when_answer(self, answer_length):
        """重置计时器（当小爱回答时）"""
        if not (self.is_playing and self.config.continue_play):
            return
        pause_time = answer_length / 5 + 1
        offset, duration = self.get_offset_duration()
        self._paused_time += pause_time
        new_time = duration - offset + pause_time
        await self.set_next_music_timeout(new_time)
        self.log.info(
            f"reset_timer 延长定时器. answer_length:{answer_length} pause_time:{pause_time}"
        )

    async def set_next_music_timeout(self, sec):
        """设置下一首歌曲的播放定时器"""
        await self.cancel_next_timer()

        async def _do_next():
            await asyncio.sleep(sec)
            try:
                self.log.info(f"定时器时间到了 did: {self.did}")
                current_timer = self._next_timer
                if current_timer:
                    # 取消任务（防止任务被重复触发，即使sleep已结束）
                    current_timer.cancel()
                    try:
                        await current_timer  # 等待任务取消完成，避免警告
                    except asyncio.CancelledError:
                        pass
                    # 再置空引用
                    self._next_timer = None
                    if self.device.play_type == PLAY_TYPE_SIN:
                        self.log.info(f"单曲播放不继续播放下一首 did: {self.did}")
                        await self.stop(arg1="notts")
                    else:
                        await self._play_next()
                else:
                    self.log.info(f"定时器时间到了但是不见了 did: {self.did}")
                    await self.stop(arg1="notts")

            except Exception as e:
                self.log.error(f"Execption {e}")

        self._next_timer = asyncio.create_task(_do_next())
        self.log.info(f"{sec} 秒后将会播放下一首歌曲 did: {self.did}")

    async def set_volume(self, volume: int):
        """设置音量"""
        self.log.info(f"set_volume.  did: {self.did} volume: {volume}")
        try:
            await self.auth_manager.mina_service.player_set_volume(
                self.device_id, volume
            )
        except Exception as e:
            self.log.exception(f"Execption {e}")

    async def get_volume(self):
        """获取音量"""
        volume = 0
        try:
            playing_info = await self.auth_manager.mina_service.player_get_status(
                self.device_id
            )
            self.log.info(f"get_volume. playing_info:{playing_info}")
            volume = json.loads(playing_info.get("data", {}).get("info", "{}")).get(
                "volume", 0
            )
        except Exception as e:
            self.log.warning(f"Execption {e}")
        volume = int(volume)
        self.log.info("get_volume. volume:%d", volume)
        return volume

    async def set_play_type(self, play_type, dotts=True):
        """设置播放类型"""
        self.device.play_type = play_type
        # 发布设备配置变更事件
        if self.event_bus:
            self.event_bus.publish(DEVICE_CONFIG_CHANGED)
        if dotts:
            tts = self.config.get_play_type_tts(play_type)
            await self.do_tts(tts)
        self.update_playlist()

    async def play_music_list(self, list_name, music_name):
        """播放指定播放列表"""
        self._last_cmd = "play_music_list"
        self.device.cur_playlist = list_name
        self.update_playlist()
        if not music_name:
            music_name = self.device.playlist2music.get(list_name, "")
        self.log.info(f"开始播放列表{list_name} {music_name}")
        await self._play(music_name, exact=True)

    async def stop(self, arg1=""):
        """停止播放"""
        self._last_cmd = "stop"
        self.is_playing = False
        if arg1 != "notts":
            await self.do_tts(self.config.stop_tts_msg)
            await asyncio.sleep(3)  # 等它说完
        # 取消组内所有的下一首歌曲的定时器
        await self.cancel_group_next_timer()
        await self.group_force_stop_xiaoai()
        self.log.info("stop now")

    async def group_force_stop_xiaoai(self):
        """强制停止组内所有设备"""
        device_id_list = self.xiaomusic.device_manager.get_group_device_id_list(
            self.group_name
        )
        self.log.info(f"group_force_stop_xiaoai {self.group_name} {device_id_list}")
        tasks = [self.force_stop_xiaoai(device_id) for device_id in device_id_list]
        results = await asyncio.gather(*tasks)
        self.log.info(f"group_force_stop_xiaoai {device_id_list} {results}")
        return results

    async def stop_after_minute(self, minute: int):
        """定时关机"""
        if self._stop_timer:
            self._stop_timer.cancel()
            self._stop_timer = None
            self.log.info("关机定时器已取消")

        async def _do_stop():
            await asyncio.sleep(minute * 60)
            try:
                await self.stop(arg1="notts")
            except Exception as e:
                self.log.exception(f"Execption {e}")

        self._stop_timer = asyncio.create_task(_do_stop())
        await self.do_tts(f"收到,{minute}分钟后将关机")

    async def cancel_next_timer(self):
        """取消下一首定时器"""
        self.log.info(f"cancel_next_timer did: {self.did}")
        if self._next_timer:
            self._next_timer.cancel()
            try:
                await self._next_timer
            except asyncio.CancelledError:
                pass
            self.log.info(f"下一曲定时器已取消 did: {self.did}")
            self._next_timer = None
        else:
            self.log.info(f"下一曲定时器不见了 did: {self.did}")

    async def cancel_group_next_timer(self):
        """取消组内所有设备的下一首定时器"""
        devices = self.xiaomusic.device_manager.get_group_devices(self.group_name)
        self.log.info(f"cancel_group_next_timer {devices}")
        for device in devices.values():
            await device.cancel_next_timer()

    def get_cur_play_list(self):
        """获取当前播放列表名称"""
        return self.device.cur_playlist

    def cancel_all_timer(self):
        """清空所有定时器"""
        self.log.info("in cancel_all_timer")
        if self._next_timer:
            self._next_timer.cancel()
            self._next_timer = None
            self.log.info("cancel_all_timer _next_timer.cancel")

        if self._stop_timer:
            self._stop_timer.cancel()
            self._stop_timer = None
            self.log.info("cancel_all_timer _stop_timer.cancel")

        if self._tts_timer:
            self._tts_timer.cancel()
            self._tts_timer = None
            self.log.info("cancel_all_timer _tts_timer.cancel")

    @classmethod
    def dict_clear(cls, d):
        """清空设备字典并取消所有定时器"""
        for key in list(d):
            val = d.pop(key)
            val.cancel_all_timer()

    def find_cur_playlist(self, name):
        """根据当前歌曲匹配歌曲列表

        匹配顺序：
        1. 收藏
        2. 最近新增
        3. 排除（全部,所有歌曲,所有电台,临时搜索列表）
        4. 所有歌曲
        5. 所有电台
        6. 全部
        """
        music_list = self.xiaomusic.music_library.music_list
        if name in music_list.get("收藏", []):
            return "收藏"
        if name in music_list.get("最近新增", []):
            return "最近新增"
        for list_name, play_list in music_list.items():
            if (list_name not in ["全部", "所有歌曲", "所有电台", "临时搜索列表"]) and (
                name in play_list
            ):
                return list_name
        if name in music_list.get("所有歌曲", []):
            return "所有歌曲"
        if name in music_list.get("所有电台", []):
            return "所有电台"
        return "全部"
