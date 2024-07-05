import importlib
import inspect
import pkgutil


class PluginManager:
    def __init__(self, xiaomusic, plugin_dir="plugins"):
        self.xiaomusic = xiaomusic
        self.log = xiaomusic.log
        self._funcs = {}
        self._load_plugins(plugin_dir)

    def _load_plugins(self, plugin_dir):
        # 假设 plugins 已经在搜索路径上
        package_name = plugin_dir
        package = importlib.import_module(package_name)

        # 遍历 package 中所有模块并动态导入它们
        for _, modname, _ in pkgutil.iter_modules(package.__path__, package_name + "."):
            # 跳过__init__文件
            if modname.endswith("__init__"):
                continue
            module = importlib.import_module(modname)
            # 将 log 和 xiaomusic 注入模块的命名空间
            module.log = self.log
            module.xiaomusic = self.xiaomusic

            # 动态获取模块中与文件名同名的函数
            function_name = modname.split(".")[-1]  # 从模块全名提取函数名
            if hasattr(module, function_name):
                self._funcs[function_name] = getattr(module, function_name)
            else:
                self.log.error(
                    f"No function named '{function_name}' found in module {modname}"
                )

    def get_func(self, plugin_name):
        """根据插件名获取插件函数"""
        return self._funcs.get(plugin_name)

    def get_local_namespace(self):
        """返回包含所有插件函数的字典，可以用作 exec 要执行的代码的命名空间"""
        return self._funcs.copy()

    async def execute_plugin(self, code):
        """
        执行指定的插件代码。插件函数可以是同步或异步。
        :param code: 需要执行的插件函数代码（例如 'plugin1("hello")'）
        """
        # 分解代码字符串以获取函数名
        func_name = code.split("(")[0]

        # 根据解析出的函数名从插件字典中获取函数
        plugin_func = self.get_func(func_name)

        if not plugin_func:
            raise ValueError(f"No plugin function named '{func_name}' found.")

        # 检查函数是否是异步函数
        global_namespace = globals().copy()
        local_namespace = self.get_local_namespace()
        if inspect.iscoroutinefunction(plugin_func):
            # 如果是异步函数，构建执行用的协程对象
            coroutine = eval(code, global_namespace, local_namespace)
            # 等待协程执行
            await coroutine
        else:
            # 如果是普通函数，直接执行代码
            eval(code, global_namespace, local_namespace)
