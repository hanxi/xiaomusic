#!/usr/bin/env python3
import asyncio
import logging
from typing import Any

from openai import OpenAI

log = logging.getLogger(__package__)

# 简化的音乐分析提示，专注于快速提取
MUSIC_ANALYSIS_PROMPT = """
你是一个音乐播放口令分析师，专门负责从用户指令中提取歌曲名和歌手名信息。

任务要求：
1. 识别用户指令中的歌曲名和歌手名
2. 按照JSON格式返回结果：{"name": "歌曲名", "artist": "歌手名"}
3. 如果只识别到歌曲名，返回：{"name": "歌曲名", "artist": ""}
4. 如果只识别到歌手名，返回：{"name": "", "artist": "歌手名"}
5. 如果识别出多个歌名名，返回：{"name": "", "artist": "歌手名1,歌手名2"}
6. 如果都没有识别到，返回：{}
7. 不要添加任何额外解释或文字，只返回JSON格式结果
8. 特别要注意一些歌曲名称中包含'的'字的歌，不要识别错误了。如用户指令：你的答案，应返回：{"name": "你的答案", "artist": ""}
"""


def create_openai_client(base_url: str, api_key: str) -> OpenAI:
    """
    创建OpenAI客户端

    Args:
        base_url: OpenAI API的基础URL
        api_key: API密钥

    Returns:
        OpenAI客户端实例
    """
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
    )


# 默认使用通义千问API【阿里云百炼】: qwen-flash
async def call_openai_chat(
    client: OpenAI,
    messages: list[dict[str, str]],
    model: str = "qwen-flash",
    temperature: float = 0.1,  # 更低的温度值以获得更一致的结果
    max_tokens: int | None = 100,  # 限制输出长度以提高速度
    timeout: int = 10,  # 减少超时时间
    extra_body: dict[str, Any] | None = None,
) -> str | None:
    """
    异步调用OpenAI聊天接口

    Args:
        client: OpenAI客户端实例
        messages: 消息列表，每个消息包含role和content
        model: 使用的模型名称
        temperature: 控制输出随机性的参数
        max_tokens: 最大输出token数
        timeout: 请求超时时间（秒）
        extra_body: 额外的请求体参数

    Returns:
        模型返回的内容，失败时返回None
    """
    try:
        # 设置请求超时
        completion = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    extra_body=extra_body or {},
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
            ),
            timeout=timeout,
        )

        # 获取返回内容
        content = completion.choices[0].message.content
        log.debug(
            f"OpenAI API call successful, response length: {len(content) if content else 0}"
        )
        return content

    except asyncio.TimeoutError:
        log.warning(f"OpenAI API call timed out after {timeout} seconds")
        return None
    except Exception as e:
        log.warning(f"Error calling OpenAI API: {e}")
        return None


async def analyze_music_command(
    command: str,
    # 默认使用通义千问API【阿里云百炼】: qwen-flash
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key: str = "",
    model: str = "qwen-flash",
    temperature: float = 0.1,  # 更低的温度值以获得更一致、更快的结果
) -> dict[str, str]:
    """
    快速分析音乐播放口令，提取歌曲名和歌手名

    Args:
        command: 用户的音乐播放指令
        base_url: OpenAI API的基础URL
        api_key: API密钥
        model: 使用的模型名称
        temperature: 控制输出随机性的参数（较低值保持一致性）

    Returns:
        包含歌曲名和歌手名的字典，格式为 {"name": "歌曲名", "artist": "歌手名"}
    """
    try:
        # 直接创建客户端并调用，减少函数调用层级
        client = OpenAI(base_url=base_url, api_key=api_key)

        completion = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": MUSIC_ANALYSIS_PROMPT},
                        {"role": "user", "content": f"用户指令：{command}"},
                    ],
                    temperature=temperature,
                    max_tokens=100,  # 限制输出长度以提高速度
                ),
            ),
            timeout=10,  # 减少超时时间
        )

        content = completion.choices[0].message.content

        # 快速提取JSON部分
        start = content.find("{")
        end = content.rfind("}") + 1
        if start != -1 and end != 0:
            import json

            json_str = content[start:end]
            result = json.loads(json_str)
            return {"name": result.get("name", ""), "artist": result.get("artist", "")}
    except (asyncio.TimeoutError, json.JSONDecodeError, Exception) as e:
        log.debug(f"Music command analysis failed: {e}")

    return {}


def format_openai_messages(conversation_history: list[str]) -> list[dict[str, str]]:
    """
    将对话历史格式化为OpenAI所需的格式

    Args:
        conversation_history: 对话历史列表，交替包含用户和助手的消息

    Returns:
        格式化后的消息列表
    """
    messages = []
    for i, msg in enumerate(conversation_history):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": msg})
    return messages


async def stream_openai_chat(
    client: OpenAI,
    messages: list[dict[str, str]],
    model: str = "TBStars2-200B-A13B",
    temperature: float = 0.7,
) -> str | None:
    """
    流式调用OpenAI聊天接口

    Args:
        client: OpenAI客户端实例
        messages: 消息列表
        model: 使用的模型名称
        temperature: 控制输出随机性的参数

    Returns:
        完整的流式响应内容，失败时返回None
    """
    try:
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature, stream=True
        )

        full_content = ""
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                content_piece = chunk.choices[0].delta.content
                full_content += content_piece
                # 可以在这里实时处理流式返回的内容
                print(content_piece, end="", flush=True)

        print()  # 换行
        return full_content

    except Exception as e:
        log.error(f"Error in stream_openai_chat: {e}")
        return None
