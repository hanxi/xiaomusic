#!/usr/bin/env python3
"""
检查所有插件的加载状态
"""

import sys

sys.path.append(".")

from xiaomusic.config import Config
from xiaomusic.js_plugin_manager import JSPluginManager


def check_all_plugins():
    print("=== 检查所有插件加载状态 ===\n")

    config = Config()
    config.verbose = True

    class SimpleLogger:
        def info(self, msg):
            print(f"[INFO] {msg}")

        def error(self, msg):
            print(f"[ERROR] {msg}")

        def debug(self, msg):
            print(f"[DEBUG] {msg}")

    print("1. 创建插件管理器...")
    manager = JSPluginManager(None)
    manager.config = config
    manager.log = SimpleLogger()

    import time

    time.sleep(3)  # 等待插件加载

    print("\n2. 获取所有插件状态...")
    plugins = manager.get_plugin_list()
    print(f"   总共找到 {len(plugins)} 个插件")

    # 分类插件状态
    working_plugins = []
    failed_plugins = []

    for plugin in plugins:
        if plugin.get("loaded", False) and plugin.get("enabled", False):
            working_plugins.append(plugin)
        else:
            failed_plugins.append(plugin)

    print(f"\n   正常工作的插件 ({len(working_plugins)} 个):")
    for plugin in working_plugins:
        print(f"     ✓ {plugin['name']}")

    print(f"\n   失败的插件 ({len(failed_plugins)} 个):")
    for plugin in failed_plugins:
        print(f"     ✗ {plugin['name']}: {plugin.get('error', 'Unknown error')}")

    # 清理
    if hasattr(manager, "node_process") and manager.node_process:
        manager.node_process.terminate()


if __name__ == "__main__":
    check_all_plugins()
