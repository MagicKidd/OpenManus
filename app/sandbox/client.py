# app/sandbox/client.py
# 沙箱客户端模块 - 提供与Docker沙箱交互的客户端接口和实现

"""
沙箱客户端模块实现了与Docker沙箱的交互接口，使智能体能够安全地执行代码。
本模块展示了多种Python高级设计模式，特别适合初学者学习现代Python编程实践。

设计模式展示:
1. 接口设计: 使用Protocol和ABC分离接口与实现
2. 工厂模式: 通过工厂函数创建具体的客户端实例
3. 依赖注入: 通过参数传入配置，而不是硬编码
4. 异步编程: 使用async/await进行非阻塞操作

主要组件:
- SandboxFileOperations: 文件操作协议接口
- BaseSandboxClient: 沙箱客户端抽象基类
- LocalSandboxClient: 本地沙箱客户端具体实现
- create_sandbox_client: 客户端工厂函数
"""

from abc import ABC, abstractmethod  # 导入抽象基类相关工具
from typing import Dict, Optional, Protocol  # 导入类型提示相关工具

from app.config import SandboxSettings  # 导入沙箱配置类
from app.sandbox.core.sandbox import DockerSandbox  # 导入Docker沙箱实现


class SandboxFileOperations(Protocol):
    """
    沙箱文件操作协议。

    这个类使用了Python的Protocol类型，它定义了一个"鸭子类型"接口，
    任何实现了这些方法的类都被视为符合此协议，不需要显式继承。

    Protocol相比ABC(抽象基类)的优势:
    1. 不要求显式继承，更灵活
    2. 支持结构化类型检查
    3. 适合定义第三方库接口

    本协议定义了沙箱进行文件操作所需的四个基本方法。
    """

    async def copy_from(self, container_path: str, local_path: str) -> None:
        """
        从容器复制文件到本地。

        Args:
            container_path: 容器内的文件路径。
            local_path: 本地目标路径。
        """
        ...  # 省略号表示这是一个抽象方法，具体实现由子类提供

    async def copy_to(self, local_path: str, container_path: str) -> None:
        """
        从本地复制文件到容器。

        Args:
            local_path: 本地源文件路径。
            container_path: 容器内的目标路径。
        """
        ...

    async def read_file(self, path: str) -> str:
        """
        读取容器内文件内容。

        Args:
            path: 容器内的文件路径。

        Returns:
            str: 文件内容。
        """
        ...

    async def write_file(self, path: str, content: str) -> None:
        """
        向容器内文件写入内容。

        Args:
            path: 容器内的文件路径。
            content: 要写入的内容。
        """
        ...


class BaseSandboxClient(ABC):
    """
    沙箱客户端基础接口。

    这个类使用了Python的抽象基类(ABC)，定义了所有沙箱客户端必须实现的方法。
    通过ABC和@abstractmethod装饰器，我们可以:
    1. 强制子类必须实现这些方法
    2. 防止直接实例化抽象类
    3. 提供清晰的接口文档

    抽象基类是面向对象设计中"接口继承"的Python实现方式。
    """

    @abstractmethod
    async def create(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        创建沙箱实例。

        Args:
            config: 沙箱配置，可选。
            volume_bindings: 卷绑定映射，可选。
        """
        # 抽象方法不提供实现，必须由子类重写

    @abstractmethod
    async def run_command(self, command: str, timeout: Optional[int] = None) -> str:
        """
        在沙箱中执行命令。

        Args:
            command: 要执行的命令。
            timeout: 超时时间(秒)，可选。

        Returns:
            命令执行的输出结果。
        """
        pass

    @abstractmethod
    async def copy_from(self, container_path: str, local_path: str) -> None:
        """从容器复制文件到本地。"""
        pass

    @abstractmethod
    async def copy_to(self, local_path: str, container_path: str) -> None:
        """从本地复制文件到容器。"""
        pass

    @abstractmethod
    async def read_file(self, path: str) -> str:
        """读取容器内文件。"""
        pass

    @abstractmethod
    async def write_file(self, path: str, content: str) -> None:
        """向容器内文件写入内容。"""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """清理沙箱资源。"""
        pass


class LocalSandboxClient(BaseSandboxClient):
    """
    本地沙箱客户端实现。

    这个类继承自BaseSandboxClient抽象基类，提供了与本地Docker沙箱交互的具体实现。
    它封装了DockerSandbox的功能，提供了更高级的接口。

    这个类展示了:
    1. 如何实现抽象基类的所有抽象方法
    2. 如何管理资源生命周期(创建和清理)
    3. 如何优雅处理错误情况
    """

    def __init__(self):
        """
        初始化本地沙箱客户端。

        在构造函数中，我们将sandbox属性设置为None，表示沙箱尚未创建。
        这是延迟初始化的一个例子，只有在需要时才创建资源。
        """
        self.sandbox: Optional[DockerSandbox] = None

    async def create(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        创建沙箱实例。

        这个方法实例化一个DockerSandbox对象，并调用其create方法来创建和启动容器。

        Args:
            config: 沙箱配置，可选。如果为None，使用默认配置。
            volume_bindings: 卷映射，可选。定义主机路径到容器路径的映射。

        Raises:
            RuntimeError: 如果沙箱创建失败。
        """
        self.sandbox = DockerSandbox(config, volume_bindings)
        await self.sandbox.create()

    async def run_command(self, command: str, timeout: Optional[int] = None) -> str:
        """
        在沙箱中执行命令。

        这个方法展示了如何检查状态(sandbox是否已初始化)，然后委托给底层对象执行实际工作。

        Args:
            command: 要执行的命令。
            timeout: 执行超时时间(秒)，可选。

        Returns:
            命令输出。

        Raises:
            RuntimeError: 如果沙箱未初始化。
        """
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        return await self.sandbox.run_command(command, timeout)

    async def copy_from(self, container_path: str, local_path: str) -> None:
        """
        从容器复制文件到本地。

        Args:
            container_path: 容器内的文件路径。
            local_path: 本地目标路径。

        Raises:
            RuntimeError: 如果沙箱未初始化。
        """
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        await self.sandbox.copy_from(container_path, local_path)

    async def copy_to(self, local_path: str, container_path: str) -> None:
        """
        从本地复制文件到容器。

        Args:
            local_path: 本地源文件路径。
            container_path: 容器内的目标路径。

        Raises:
            RuntimeError: 如果沙箱未初始化。
        """
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        await self.sandbox.copy_to(local_path, container_path)

    async def read_file(self, path: str) -> str:
        """
        读取容器中的文件内容。

        Args:
            path: 容器内的文件路径。

        Returns:
            文件内容。

        Raises:
            RuntimeError: 如果沙箱未初始化。
        """
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        return await self.sandbox.read_file(path)

    async def write_file(self, path: str, content: str) -> None:
        """
        向容器内文件写入内容。

        Args:
            path: 容器内的文件路径。
            content: 要写入的内容。

        Raises:
            RuntimeError: 如果沙箱未初始化。
        """
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        await self.sandbox.write_file(path, content)

    async def cleanup(self) -> None:
        """
        清理沙箱资源。

        这个方法展示了资源管理的最佳实践:
        1. 检查资源是否存在，避免清理不存在的资源
        2. 调用适当的清理方法释放资源
        3. 将引用设置为None，允许垃圾收集
        """
        if self.sandbox:
            await self.sandbox.cleanup()
            self.sandbox = None


def create_sandbox_client() -> LocalSandboxClient:
    """
    创建沙箱客户端的工厂函数。

    这个函数展示了工厂模式，它负责创建复杂对象，而不是让调用者直接实例化。
    工厂模式的优点:
    1. 封装对象创建逻辑
    2. 允许将来改变实现而不影响调用代码
    3. 可以根据配置或环境选择不同的实现

    Returns:
        LocalSandboxClient: 沙箱客户端实例。
    """
    return LocalSandboxClient()


# 全局客户端实例，可以在整个应用中共享使用
SANDBOX_CLIENT = create_sandbox_client()
