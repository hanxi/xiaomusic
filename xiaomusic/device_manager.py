"""设备管理模块

本模块负责小米音箱设备的管理，包括：
- 设备列表管理
- 设备分组管理
- 设备信息查询
"""

from xiaomusic.utils import (
    parse_str_to_dict,
)


class DeviceManager:
    """设备管理器

    负责管理小米音箱设备列表、分组和设备信息查询。
    """

    def __init__(self, config, log):
        """初始化设备管理器

        Args:
            config: 配置对象
            log: 日志对象
        """
        self.config = config
        self.log = log

        # 设备相关数据结构
        self.devices = {}  # key 为 did，value 为 XiaoMusicDevice 实例
        self.device_id_did = {}  # device_id 到 did 的映射
        self.groups = {}  # 设备分组，key 为组名，value 为 device_id 列表

    def update_devices(self):
        """更新设备列表

        根据配置中的设备信息和分组信息，更新设备列表和分组映射。
        这个方法需要在设备信息已经从小米服务器获取后调用。
        """
        self.device_id_did = {}
        self.groups = {}

        # 遍历配置中的设备，构建基本映射
        did2group = parse_str_to_dict(self.config.group_list, d1=",", d2=":")
        for did, device in self.config.devices.items():
            # 构建 device_id 到 did 的映射
            self.device_id_did[device.device_id] = did
            group_name = did2group.get(did)
            if not group_name:
                group_name = device.name
            if group_name not in self.groups:
                self.groups[group_name] = []
            self.groups[group_name].append(device.device_id)

        self.log.info(f"设备列表已更新: device_id_did={self.device_id_did}")
        self.log.info(f"设备分组已更新: groups={self.groups}")

    def get_one_device_id(self):
        """获取一个设备ID

        Returns:
            str: 第一个设备的device_id，如果没有设备则返回空字符串
        """
        device_id = next(iter(self.device_id_did), "")
        return device_id

    def get_did(self, device_id):
        """根据device_id获取did

        Args:
            device_id: 设备ID

        Returns:
            str: 设备的did，如果不存在则返回空字符串
        """
        return self.device_id_did.get(device_id, "")

    def get_hardward(self, device_id):
        """获取设备硬件信息

        Args:
            device_id: 设备ID

        Returns:
            str: 设备的硬件型号，如果设备不存在则返回空字符串
        """
        device = self.get_device_by_device_id(device_id)
        if not device:
            return ""
        return device.hardware

    def get_device_by_device_id(self, device_id):
        """根据device_id获取设备配置

        Args:
            device_id: 设备ID

        Returns:
            Device: 设备配置对象，如果不存在则返回None
        """
        did = self.device_id_did.get(device_id)
        if not did:
            return None
        return self.config.devices.get(did)

    def get_group_device_id_list(self, group_name):
        """获取分组的设备ID列表

        Args:
            group_name: 分组名称

        Returns:
            list: 设备ID列表
        """
        return self.groups.get(group_name, [])

    def get_group_devices(self, group_name):
        """获取分组的设备字典

        Args:
            group_name: 分组名称

        Returns:
            dict: 设备字典，key为did，value为XiaoMusicDevice实例
        """
        device_id_list = self.groups.get(group_name, [])
        devices = {}
        for device_id in device_id_list:
            did = self.device_id_did.get(device_id, "")
            if did and did in self.devices:
                devices[did] = self.devices[did]
        return devices

    def set_devices(self, devices):
        """设置设备实例字典

        这个方法用于在主类中设置实际的设备实例。

        Args:
            devices: 设备实例字典，key为did，value为XiaoMusicDevice实例
        """
        self.devices = devices
