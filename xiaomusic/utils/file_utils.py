#!/usr/bin/env python3
"""文件和目录操作相关工具函数"""

import logging
import os
import re
import shutil

log = logging.getLogger(__package__)


def _get_depth_path(root: str, directory: str, depth: int) -> str:
    """计算指定深度的路径"""
    # 计算当前目录的深度
    relative_path = root[len(directory) :].strip(os.sep)
    path_parts = relative_path.split(os.sep)
    if len(path_parts) >= depth:
        return os.path.join(directory, *path_parts[:depth])
    else:
        return root


def _append_files_result(
    result: dict, root: str, joinpath: str, files: list, support_extension: set
) -> None:
    """将文件添加到结果字典中"""
    dir_name = os.path.basename(root)
    if dir_name not in result:
        result[dir_name] = []
    for file in files:
        # 过滤隐藏文件
        if file.startswith("."):
            continue
        # 过滤文件后缀
        (name, extension) = os.path.splitext(file)
        if extension.lower() not in support_extension:
            continue

        result[dir_name].append(os.path.join(joinpath, file))


def traverse_music_directory(
    directory: str, depth: int, exclude_dirs: set, support_extension: set
) -> dict:
    """
    遍历音乐目录

    Args:
        directory: 目录路径
        depth: 遍历深度
        exclude_dirs: 排除的目录集合
        support_extension: 支持的文件扩展名集合

    Returns:
        {目录名: [文件路径列表]}
    """
    result = {}
    for root, dirs, files in os.walk(directory, followlinks=True):
        # 忽略排除的目录
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        # 计算当前目录的深度
        current_depth = root[len(directory) :].count(os.sep) + 1
        if current_depth > depth:
            depth_path = _get_depth_path(root, directory, depth - 1)
            _append_files_result(result, depth_path, root, files, support_extension)
        else:
            _append_files_result(result, root, root, files, support_extension)
    return result


def safe_join_path(safe_root: str, directory: str) -> str:
    """
    安全地拼接路径，确保结果在安全根目录内

    Args:
        safe_root: 安全根目录
        directory: 要拼接的目录

    Returns:
        规范化的完整路径

    Raises:
        ValueError: 如果路径不在安全根目录内
    """
    directory = os.path.join(safe_root, directory)
    # Normalize the directory path
    normalized_directory = os.path.normpath(directory)
    # Ensure the directory is within the safe root
    if not normalized_directory.startswith(os.path.normpath(safe_root)):
        raise ValueError(f"Access to directory '{directory}' is not allowed.")
    return normalized_directory


def _longest_common_prefix(file_names: list) -> str:
    """查找文件名列表的最长公共前缀"""
    if not file_names:
        return ""

    # 将第一个文件名作为初始前缀
    prefix = file_names[0]

    for file_name in file_names[1:]:
        while not file_name.startswith(prefix):
            # 如果当前文件名不以prefix开头，则缩短prefix
            prefix = prefix[:-1]
            if not prefix:
                return ""

    return prefix


def remove_common_prefix(directory: str) -> None:
    """
    移除目录下文件名的公共前缀

    Args:
        directory: 目录路径
    """
    files = os.listdir(directory)

    # 获取所有文件的前缀
    common_prefix = _longest_common_prefix(files)

    log.info(f'Common prefix identified: "{common_prefix}"')

    pattern = re.compile(r"^[pP]?(\d+)\s+\d*(.+?)\.(.*$)")
    for filename in files:
        if filename == common_prefix:
            continue
        # 检查文件名是否以共同前缀开头
        if filename.startswith(common_prefix):
            # 构造新的文件名
            new_filename = filename[len(common_prefix) :]
            match = pattern.search(new_filename.strip())
            if match:
                num = match.group(1)
                name = match.group(2).replace(".", " ").strip()
                suffix = match.group(3)
                new_filename = f"{num}.{name}.{suffix}"
            # 生成完整的文件路径
            old_file_path = os.path.join(directory, filename)
            new_file_path = os.path.join(directory, new_filename)

            # 重命名文件
            os.rename(old_file_path, new_file_path)
            log.debug(f'Renamed: "{filename}" to "{new_filename}"')


def not_in_dirs(filename: str, ignore_absolute_dirs: list) -> bool:
    """
    判断文件是否不在排除目录列表中

    Args:
        filename: 文件路径
        ignore_absolute_dirs: 要忽略的绝对路径列表

    Returns:
        True 如果文件不在排除目录中
    """
    file_absolute_path = os.path.abspath(filename)
    file_dir = os.path.dirname(file_absolute_path)
    for ignore_dir in ignore_absolute_dirs:
        if file_dir.startswith(ignore_dir):
            log.info(f"{file_dir} in {ignore_dir}")
            return False  # 文件在排除目录中

    return True  # 文件不在排除目录中


def chmodfile(file_path: str) -> None:
    """修改文件权限为 775"""
    try:
        os.chmod(file_path, 0o775)
    except Exception as e:
        log.info(f"chmodfile failed: {e}")


def chmoddir(dir_path: str) -> None:
    """修改目录下所有文件的权限为 775"""
    # 获取指定目录下的所有文件和子目录
    for item in os.listdir(dir_path):
        item_path = os.path.join(dir_path, item)
        # 确保是文件，且不是目录
        if os.path.isfile(item_path):
            try:
                os.chmod(item_path, 0o775)
                log.info(f"Changed permissions of file: {item_path}")
            except Exception as e:
                log.info(f"chmoddir failed: {e}")


async def clean_temp_dir(config):
    try:
        temp_dir = config.temp_dir
        if not os.path.exists(temp_dir):
            log.info(f"临时目录不存在: {temp_dir}")
            # 目录不存在时也创建，保持目录结构统一
            os.makedirs(temp_dir, exist_ok=True)
            log.info(f"已创建临时目录: {temp_dir}")
            return

        # 递归删除整个临时目录（包括目录内所有文件/子目录）
        shutil.rmtree(temp_dir)
        log.debug(f"已删除临时目录: {temp_dir}")

        # 重新创建空的临时目录
        os.makedirs(temp_dir, exist_ok=True)
        log.info(f"已重新创建临时目录: {temp_dir}")

        log.info("定时清理临时文件完成，已删除并重建临时目录")
    except Exception as e:
        log.exception(f"清理临时文件异常: {e}")
