"""命令处理模块

负责语音指令的解析、匹配和路由。
"""

import asyncio
import re

from xiaomusic.config import KEY_WORD_ARG_BEFORE_DICT


class CommandHandler:
    """命令处理器

    负责解析用户的语音指令，匹配对应的命令，并路由到相应的处理方法。
    """

    def __init__(self, config, log, xiaomusic_instance):
        """初始化命令处理器

        Args:
            config: 配置对象
            log: 日志对象
            xiaomusic_instance: XiaoMusic 主类实例，用于调用命令执行方法
        """
        self.config = config
        self.log = log
        self.xiaomusic = xiaomusic_instance
        self.active_cmd = config.active_cmd.split(",") if config.active_cmd else []

    async def do_check_cmd(self, did="", query="", ctrl_panel=True, **kwargs):
        """检查并执行命令

        这是命令处理的入口方法，负责：
        1. 记录命令
        2. 匹配命令
        3. 执行对应的方法
        4. 处理未匹配的情况

        Args:
            did: 设备ID
            query: 用户查询/命令
            ctrl_panel: 是否来自控制面板
            **kwargs: 其他参数
        """
        self.log.info(f"收到消息:{query} 控制面板:{ctrl_panel} did:{did}")

        # 记录最后一条命令
        self.xiaomusic.last_cmd = query

        try:
            # 匹配命令
            opvalue, oparg = self.match_cmd(did, query, ctrl_panel)

            if not opvalue:
                # 未匹配到命令，等待后检查是否需要重播
                await asyncio.sleep(1)
                await self.xiaomusic.check_replay(did)
                return

            # 执行命令
            func = getattr(self.xiaomusic, opvalue)
            await func(did=did, arg1=oparg)

        except Exception as e:
            self.log.exception(f"Execption {e}")

    def match_cmd(self, did, query, ctrl_panel):
        """匹配命令

        根据用户输入的查询字符串，匹配对应的命令和参数。

        匹配策略：
        1. 优先完全匹配
        2. 然后按配置的优先级顺序进行模糊匹配
        3. 检查是否在激活命令列表中

        Args:
            did: 设备ID
            query: 用户查询字符串
            ctrl_panel: 是否来自控制面板

        Returns:
            tuple: (命令值, 命令参数)，未匹配返回 (None, None)
        """
        # 优先处理完全匹配
        opvalue = self.check_full_match_cmd(did, query, ctrl_panel)
        if opvalue:
            self.log.info(f"完全匹配指令. query:{query} opvalue:{opvalue}")
            # 自定义口令
            if opvalue.startswith("exec#"):
                code = opvalue.split("#", 1)[1]
                return ("exec", code)
            return (opvalue, "")

        # 按优先级顺序进行模糊匹配
        for opkey in self.config.key_match_order:
            patternarg = rf"(.*){opkey}(.*)"
            # 匹配参数
            matcharg = re.match(patternarg, query)
            if not matcharg:
                continue

            argpre = matcharg.groups()[0]
            argafter = matcharg.groups()[1]
            self.log.debug(
                "matcharg. opkey:%s, argpre:%s, argafter:%s",
                opkey,
                argpre,
                argafter,
            )

            # 根据配置决定参数位置
            oparg = argafter
            if opkey in KEY_WORD_ARG_BEFORE_DICT:
                oparg = argpre

            opvalue = self.config.key_word_dict.get(opkey)

            # 检查是否在激活命令中
            if (
                (not ctrl_panel)
                and (not self.xiaomusic.isplaying(did))
                and self.active_cmd
                and (opvalue not in self.active_cmd)
                and (opkey not in self.active_cmd)
            ):
                self.log.info(f"不在激活命令中 {opvalue}")
                continue

            self.log.info(f"匹配到指令. opkey:{opkey} opvalue:{opvalue} oparg:{oparg}")

            # 自定义口令
            if opvalue.startswith("exec#"):
                code = opvalue.split("#", 1)[1]
                return ("exec", code)

            return (opvalue, oparg)

        self.log.info(f"未匹配到指令 {query} {ctrl_panel}")
        return (None, None)

    def check_full_match_cmd(self, did, query, ctrl_panel):
        """检查是否完全匹配命令

        检查查询字符串是否与配置的命令关键词完全一致。

        Args:
            did: 设备ID
            query: 用户查询字符串
            ctrl_panel: 是否来自控制面板

        Returns:
            str: 匹配的命令值，未匹配返回 None
        """
        if query in self.config.key_match_order:
            opkey = query
            opvalue = self.config.key_word_dict.get(opkey)

            # 控制面板或正在播放时允许执行
            if ctrl_panel or self.xiaomusic.isplaying(did):
                return opvalue
            else:
                # 检查是否在激活命令中
                if not self.active_cmd or opvalue in self.active_cmd:
                    return opvalue

        return None
