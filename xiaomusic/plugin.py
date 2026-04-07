import ast
import importlib
import inspect
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xiaomusic.xiaomusic import XiaoMusic


class PluginManager:
    def __init__(self, xiaomusic: "XiaoMusic", plugin_dir="plugins"):
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

    def _parse_plugin_call(self, code):
        try:
            expression = ast.parse(code, mode="eval")
        except SyntaxError as exc:
            raise ValueError("Invalid plugin code.") from exc

        if not isinstance(expression.body, ast.Call):
            raise ValueError("Plugin code must be a function call.")

        call = expression.body
        if not isinstance(call.func, ast.Name):
            raise ValueError("Plugin code must call a plugin function directly.")
        if call.keywords:
            raise ValueError("Keyword arguments are not supported.")

        return call.func.id, [self._parse_plugin_arg(arg) for arg in call.args]

    def _parse_plugin_arg(self, arg):
        if isinstance(arg, ast.Constant):
            if isinstance(arg.value, (str, int, float, bool, type(None))):
                return arg.value
        elif isinstance(arg, ast.List):
            return [self._parse_plugin_arg(item) for item in arg.elts]
        elif isinstance(arg, ast.Tuple):
            return tuple(self._parse_plugin_arg(item) for item in arg.elts)
        elif isinstance(arg, ast.Dict):
            if any(key is None for key in arg.keys):
                raise ValueError("Unsupported plugin argument.")
            keys = [self._parse_plugin_arg(key) for key in arg.keys]
            values = [self._parse_plugin_arg(value) for value in arg.values]
            return dict(zip(keys, values))

        raise ValueError("Unsupported plugin argument.")

    async def execute_plugin(self, code):
        """
        执行指定的插件代码。插件函数可以是同步或异步。
        :param code: 需要执行的插件函数代码（例如 'plugin1("hello")'）
        """
        func_name, args = self._parse_plugin_call(code)

        plugin_func = self.get_func(func_name)
        if not plugin_func:
            raise ValueError(f"No plugin function named '{func_name}' found.")

        if inspect.iscoroutinefunction(plugin_func):
            await plugin_func(*args)
        else:
            plugin_func(*args)
