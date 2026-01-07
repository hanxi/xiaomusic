import json
import logging
import os
from datetime import date

log = logging.getLogger(__package__)

# 用于存储已加载的年份数据
loaded_years = {}


def load_year_data(year):
    """加载指定年份的节假日数据"""
    global loaded_years

    if year in loaded_years:
        return True

    file_path = f"holiday/{year}.json"
    if not os.path.exists(file_path):
        log.warning(f"未找到 {file_path} 文件。")
        return False

    try:
        with open(file_path, encoding="utf-8") as file:
            data = json.load(file)
            loaded_years[year] = {
                day_info["date"]: day_info["isOffDay"]
                for day_info in data.get("days", [])
            }
        log.info(f"成功加载 {year} 年数据。")
        log.debug(f"加载的日期数据: {loaded_years[year]}")
        return True
    except Exception as e:
        log.error(f"加载 {year} 年数据失败: {e}")
        return False


def is_valid_date(year, month, day):
    """检查日期是否有效"""
    try:
        date(year, month, day)
        return True
    except ValueError:
        return False


def is_weekend(year, month, day):
    """判断是否为周末"""
    weekday = date(year, month, day).isoweekday()
    return weekday >= 6  # 周六或周日


def is_off_day(year, month, day):
    """判断是否为休息日（包括法定节假日和周末）"""
    # 检查日期有效性
    if not is_valid_date(year, month, day):
        log.warning(f"无效日期: {year}-{month:02d}-{day:02d}")
        return None

    # 加载年份数据
    if not load_year_data(year):
        return None

    date_str = f"{year}-{month:02d}-{day:02d}"

    # 检查是否为特殊日期
    special_day = loaded_years[year].get(date_str)
    if special_day is not None:
        return special_day

    # 检查是否为周末
    return is_weekend(year, month, day)


def is_working_day(year, month, day):
    """判断是否为工作日（非休息日）"""
    off_day = is_off_day(year, month, day)
    return False if off_day is None else not off_day
