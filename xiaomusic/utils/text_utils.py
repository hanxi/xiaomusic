#!/usr/bin/env python3
"""文本处理和搜索相关工具函数"""

import difflib
import re
from collections.abc import AsyncIterator

from opencc import OpenCC

# 繁简转换器
cc = OpenCC("t2s")

# TTS 相关正则
_no_elapse_chars = re.compile(r"([「」『』《》" "'\"()（）]|(?<!-)-(?!-))", re.UNICODE)
_ending_punctuations = ("。", "？", "！", "；", ".", "?", "!", ";")

# 中文数字映射
chinese_to_arabic = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
    "亿": 100000000,
}


def calculate_tts_elapse(text: str) -> float:
    """计算 TTS 语音时长"""
    # for simplicity, we use a fixed speed
    speed = 4.5  # this value is picked by trial and error
    # Exclude quotes and brackets that do not affect the total elapsed time
    return len(_no_elapse_chars.sub("", text)) / speed


async def split_sentences(text_stream: AsyncIterator[str]) -> AsyncIterator[str]:
    """分句处理，按标点符号分割"""
    cur = ""
    async for text in text_stream:
        cur += text
        if cur.endswith(_ending_punctuations):
            yield cur
            cur = ""
    if cur:
        yield cur


def find_key_by_partial_string(dictionary: dict[str, str], partial_key: str) -> str:
    """通过部分字符串查找字典中的键"""
    for key, value in dictionary.items():
        if key in partial_key:
            return value
    return None


def traditional_to_simple(to_convert: str) -> str:
    """繁体转简体"""
    return cc.convert(to_convert)


def keyword_detection(user_input: str, str_list: list, n: int) -> tuple[list, list]:
    """
    关键词检测

    Args:
        user_input: 用户输入
        str_list: 候选字符串列表
        n: 返回匹配数量，-1 表示返回所有

    Returns:
        (匹配列表, 剩余列表)
    """
    # 过滤包含关键字的字符串
    matched, remains = [], []
    for item in str_list:
        if user_input in item:
            matched.append(item)
        else:
            remains.append(item)

    matched = sorted(
        matched,
        key=lambda s: difflib.SequenceMatcher(None, s, user_input).ratio(),
        reverse=True,  # 降序排序，越相似的越靠前
    )

    # 如果 n 是 -1，如果 n 大于匹配的数量，返回所有匹配的结果
    if n == -1 or n > len(matched):
        return matched, remains

    # 选择前 n 个匹配的结果
    remains = matched[n:] + remains
    return matched[:n], remains


def real_search(prompt: str, candidates: list, cutoff: float, n: int) -> list:
    """实际搜索逻辑"""
    matches, remains = keyword_detection(prompt, candidates, n=n)
    if len(matches) < n:
        # 如果没有准确关键词匹配，开始模糊匹配
        matches += difflib.get_close_matches(prompt, remains, n=n, cutoff=cutoff)
    return matches


def find_best_match(
    user_input: str,
    collection: list,
    cutoff: float = 0.6,
    n: int = 1,
    extra_search_index: dict = None,
) -> list:
    """
    查找最佳匹配

    Args:
        user_input: 用户输入
        collection: 候选集合
        cutoff: 相似度阈值
        n: 返回数量
        extra_search_index: 额外搜索索引

    Returns:
        匹配结果列表
    """
    lower_collection = {
        traditional_to_simple(item.lower()): item for item in collection
    }
    user_input = traditional_to_simple(user_input.lower())
    matches = real_search(user_input, list(lower_collection.keys()), cutoff, n)
    cur_matched_collection = [lower_collection[match] for match in matches]
    if len(matches) >= n or extra_search_index is None:
        return cur_matched_collection[:n]

    # 如果数量不满足，继续搜索
    lower_extra_search_index = {
        traditional_to_simple(k.lower()): v
        for k, v in extra_search_index.items()
        if v not in cur_matched_collection
    }
    matches = real_search(user_input, list(lower_extra_search_index.keys()), cutoff, n)
    cur_matched_collection += [lower_extra_search_index[match] for match in matches]
    return cur_matched_collection[:n]


def fuzzyfinder(
    user_input: str, collection: list, extra_search_index: dict = None
) -> list:
    """模糊搜索"""
    return find_best_match(
        user_input, collection, cutoff=0.1, n=10, extra_search_index=extra_search_index
    )


def custom_sort_key(s: str) -> tuple:
    """
    歌曲排序键函数

    支持数字前缀、数字后缀和字典序排序
    """
    # 使用正则表达式分别提取字符串的数字前缀和数字后缀
    prefix_match = re.match(r"^(\d+)", s)
    suffix_match = re.search(r"(\d+)$", s)

    numeric_prefix = int(prefix_match.group(0)) if prefix_match else None
    numeric_suffix = int(suffix_match.group(0)) if suffix_match else None

    if numeric_prefix is not None:
        # 如果前缀是数字，先按前缀数字排序，再按整个字符串排序
        return (0, numeric_prefix, s)
    elif numeric_suffix is not None:
        # 如果后缀是数字，先按前缀字符排序，再按后缀数字排序
        return (1, s[: suffix_match.start()], numeric_suffix)
    else:
        # 如果前缀和后缀都不是数字，按字典序排序
        return (2, s)


def chinese_to_number(chinese: str) -> int:
    """
    中文数字转阿拉伯数字

    Args:
        chinese: 中文数字字符串，如 "一百二十三"

    Returns:
        对应的阿拉伯数字
    """
    result = 0
    unit = 1
    num = 0
    # 处理特殊情况：以"十"开头时，在前面加"一"
    if chinese.startswith("十"):
        chinese = "一" + chinese

    # 如果只有一个字符且是单位，直接返回其值
    if len(chinese) == 1 and chinese_to_arabic[chinese] >= 10:
        return chinese_to_arabic[chinese]

    for char in reversed(chinese):
        if char in chinese_to_arabic:
            val = chinese_to_arabic[char]
            if val >= 10:
                if val > unit:
                    unit = val
                else:
                    unit *= val
            else:
                num += val * unit
    result += num

    return result


def parse_str_to_dict(s: str, d1: str = ",", d2: str = ":") -> dict:
    """
    解析字符串为字典

    格式: k1:v1,k2:v2

    Args:
        s: 待解析字符串
        d1: 第一级分隔符（默认逗号）
        d2: 第二级分隔符（默认冒号）

    Returns:
        解析后的字典
    """
    result = {}
    parts = s.split(d1)

    for part in parts:
        # 根据冒号切割
        subparts = part.split(d2)
        if len(subparts) == 2:  # 防止数据不是成对出现
            k, v = subparts
            result[k] = v

    return result


def list2str(li: list, verbose: bool = False) -> str:
    """
    列表转字符串展示

    Args:
        li: 列表
        verbose: 是否详细显示

    Returns:
        格式化的字符串
    """
    if len(li) > 5 and not verbose:
        return f"{li[:2]} ... {li[-2:]} with len: {len(li)}"
    else:
        return f"{li}"
