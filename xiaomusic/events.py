"""事件系统模块

提供简单的事件发布-订阅机制，用于模块间的解耦通信。
"""

from collections.abc import Callable

# 事件类型常量
CONFIG_CHANGED = "config_changed"
DEVICE_CONFIG_CHANGED = "device_config_changed"


class EventBus:
    """事件总线类

    实现简单的发布-订阅模式，支持事件的订阅、取消订阅和发布。
    """

    def __init__(self):
        """初始化事件总线"""
        self._subscribers: dict[str, list[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """订阅事件

        Args:
            event_type: 事件类型
            callback: 回调函数
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if callback not in self._subscribers[event_type]:
            self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """取消订阅事件

        Args:
            event_type: 事件类型
            callback: 回调函数
        """
        if event_type in self._subscribers:
            if callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)

    def publish(self, event_type: str, **kwargs) -> None:
        """发布事件

        Args:
            event_type: 事件类型
            **kwargs: 事件参数
        """
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    callback(**kwargs)
                except Exception as e:
                    # 避免某个订阅者的异常影响其他订阅者
                    print(f"Error in event callback for {event_type}: {e}")
