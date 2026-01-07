"""对话记录拉取模块

本模块负责从小爱音箱拉取对话记录，包括：
- 轮询最新对话记录
- 从小爱API获取对话
- 通过Mina服务获取对话
- 解析和验证对话记录
"""

import asyncio
import json
import time

from aiohttp import ClientTimeout


class ConversationPoller:
    """对话记录轮询器

    负责定期从小爱音箱拉取最新的对话记录，支持两种方式：
    1. 通过小爱API直接获取（LATEST_ASK_API）
    2. 通过Mina服务获取（适用于特定硬件）
    """

    def __init__(
        self,
        config,
        log,
        auth_manager,
        device_id_did,
        get_did_func,
        get_hardward_func,
        init_all_data_func,
        latest_ask_api,
        get_ask_by_mina_list,
    ):
        """初始化对话轮询器

        Args:
            config: 配置对象
            log: 日志对象
            auth_manager: 认证管理器实例
            device_id_did: 设备ID到DID的映射字典
            get_did_func: 获取DID的函数
            get_hardward_func: 获取硬件类型的函数
            init_all_data_func: 初始化所有数据的函数
            latest_ask_api: 最新对话API模板
            get_ask_by_mina_list: 需要通过Mina获取对话的硬件列表
        """
        self.config = config
        self.log = log
        self.auth_manager = auth_manager
        self.device_id_did = device_id_did
        self.last_timestamp = {}  # key为 did. timestamp last call mi speaker
        self.get_did = get_did_func
        self.get_hardward = get_hardward_func
        self.init_all_data = init_all_data_func
        self.latest_ask_api = latest_ask_api
        self.get_ask_by_mina_list = get_ask_by_mina_list

        # 存储最新的对话记录
        self.last_record = None

        # 内部事件管理
        self.polling_event = asyncio.Event()
        self.new_record_event = asyncio.Event()

    async def run_conversation_loop(
        self, session, do_check_cmd_callback, reset_timer_callback
    ):
        """运行对话循环

        持续运行的主循环，负责：
        1. 启动对话轮询任务
        2. 等待新对话记录
        3. 调用回调处理对话命令

        Args:
            session: aiohttp客户端会话
            do_check_cmd_callback: 处理命令的回调函数 async def(did, query, ctrl_panel)
            reset_timer_callback: 重置计时器的回调函数 async def(answer_length, did)
        """
        # 启动轮询任务
        task = asyncio.create_task(self.poll_latest_ask(session))
        assert task is not None  # to keep the reference to task, do not remove this

        try:
            while True:
                self.polling_event.set()
                await self.new_record_event.wait()
                self.new_record_event.clear()
                new_record = self.last_record
                self.polling_event.clear()  # stop polling when processing the question

                query = new_record.get("query", "").strip()
                did = new_record.get("did", "").strip()
                await do_check_cmd_callback(did, query, False)

                answer = new_record.get("answer")
                answers = new_record.get("answers", [{}])
                if answers:
                    answer = answers[0].get("tts", {}).get("text", "").strip()
                    await reset_timer_callback(len(answer), did)
                    self.log.debug(f"query:{query} did:{did} answer:{answer}")
        except asyncio.CancelledError:
            self.log.info("Conversation loop cancelled, cleaning up...")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            raise

    async def poll_latest_ask(self, session):
        """轮询最新对话记录

        持续运行的协程，定期从所有设备拉取最新对话记录。
        根据配置的拉取间隔和硬件类型选择合适的获取方式。

        Args:
            session: aiohttp客户端会话
        """
        try:
            while True:
                if not self.config.enable_pull_ask:
                    self.log.debug("Listening new message disabled")
                    await asyncio.sleep(5)
                    continue

                self.log.debug(
                    f"Listening new message, timestamp: {self.last_timestamp}"
                )
                # 动态获取最新的 cookie_jar
                if self.auth_manager.cookie_jar is not None:
                    session._cookie_jar = self.auth_manager.cookie_jar

                # 拉取所有音箱的对话记录
                tasks = []
                for device_id in self.device_id_did:
                    # 首次用当前时间初始化
                    did = self.get_did(device_id)
                    if did not in self.last_timestamp:
                        self.last_timestamp[did] = int(time.time() * 1000)

                    hardware = self.get_hardward(device_id)
                    if (
                        hardware in self.get_ask_by_mina_list
                    ) or self.config.get_ask_by_mina:
                        tasks.append(self.get_latest_ask_by_mina(device_id))
                    else:
                        tasks.append(
                            self.get_latest_ask_from_xiaoai(session, device_id)
                        )
                await asyncio.gather(*tasks)

                start = time.perf_counter()
                await self.polling_event.wait()
                if self.config.pull_ask_sec <= 1:
                    if (d := time.perf_counter() - start) < 1:
                        await asyncio.sleep(1 - d)
                else:
                    sleep_sec = 0
                    while True:
                        await asyncio.sleep(1)
                        sleep_sec = sleep_sec + 1
                        if sleep_sec >= self.config.pull_ask_sec:
                            break
        except asyncio.CancelledError:
            self.log.info("Polling task cancelled")
            raise

    async def get_latest_ask_from_xiaoai(self, session, device_id):
        """从小爱API获取最新对话

        通过HTTP请求小爱API获取指定设备的最新对话记录。
        包含重试机制和错误处理。

        Args:
            session: aiohttp客户端会话
            device_id: 设备ID

        Returns:
            None - 通过 _check_last_query 更新内部状态
        """
        cookies = {"deviceId": device_id}
        retries = 3
        for i in range(retries):
            try:
                timeout = ClientTimeout(total=15)
                hardware = self.get_hardward(device_id)
                url = self.latest_ask_api.format(
                    hardware=hardware,
                    timestamp=str(int(time.time() * 1000)),
                )
                # self.log.debug(f"url:{url} device_id:{device_id} hardware:{hardware}")
                r = await session.get(url, timeout=timeout, cookies=cookies)

                # 检查响应状态码
                if r.status != 200:
                    self.log.warning(f"Request failed with status {r.status}")
                    # fix #362
                    if i == 2 and r.status == 401:
                        await self.init_all_data(session)
                    continue

            except asyncio.CancelledError:
                self.log.warning("Task was cancelled.")
                return None

            except Exception as e:
                self.log.warning(f"Execption {e}")
                continue

            try:
                data = await r.json()
            except Exception as e:
                self.log.warning(f"Execption {e}")
                if i == 2:
                    # tricky way to fix #282 #272 # if it is the third time we re init all data
                    self.log.info("Maybe outof date trying to re init it")
                    await self.init_all_data(session)
            else:
                return self._get_last_query(device_id, data)
        self.log.warning("get_latest_ask_from_xiaoai. All retries failed.")

    async def get_latest_ask_by_mina(self, device_id):
        """通过Mina服务获取最新对话

        使用Mina服务API获取对话记录，适用于特定硬件类型。

        Args:
            device_id: 设备ID

        Returns:
            None - 通过 _check_last_query 更新内部状态
        """
        try:
            did = self.get_did(device_id)
            # 动态获取最新的 mina_service
            if self.auth_manager.mina_service is None:
                self.log.warning(
                    f"mina_service is None, skip get_latest_ask_by_mina for device {device_id}"
                )
                return
            messages = await self.auth_manager.mina_service.get_latest_ask(device_id)
            self.log.debug(
                f"get_latest_ask_by_mina device_id:{device_id} did:{did} messages:{messages}"
            )
            for message in messages:
                query = message.response.answer[0].question
                answer = message.response.answer[0].content
                last_record = {
                    "time": message.timestamp_ms,
                    "did": did,
                    "query": query,
                    "answer": answer,
                }
                self._check_last_query(last_record)
        except Exception as e:
            self.log.warning(f"get_latest_ask_by_mina {e}")
        return

    def _get_last_query(self, device_id, data):
        """从API响应数据中提取最后一条对话

        解析小爱API返回的JSON数据，提取最新的对话记录。

        Args:
            device_id: 设备ID
            data: API响应数据

        Returns:
            None - 通过 _check_last_query 更新内部状态
        """
        did = self.get_did(device_id)
        self.log.debug(f"_get_last_query device_id:{device_id} did:{did} data:{data}")
        if d := data.get("data"):
            records = json.loads(d).get("records")
            if not records:
                return
            last_record = records[0]
            last_record["did"] = did
            answers = last_record.get("answers", [{}])
            if answers:
                answer = answers[0].get("tts", {}).get("text", "").strip()
                last_record["answer"] = answer
            self._check_last_query(last_record)

    def _check_last_query(self, last_record):
        """检查并更新最后一条对话记录

        验证对话记录的时间戳，如果是新记录则更新并触发事件。

        Args:
            last_record: 对话记录字典，包含 did、time、query、answer 等字段
        """
        did = last_record["did"]
        timestamp = last_record.get("time")
        query = last_record.get("query", "").strip()
        self.log.debug(f"{did} 获取到最后一条对话记录：{query} {timestamp}")

        if timestamp > self.last_timestamp[did]:
            self.last_timestamp[did] = timestamp
            self.last_record = last_record
            self.new_record_event.set()
