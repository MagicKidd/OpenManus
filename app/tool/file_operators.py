"""
文件操作模块 (File Operations Module)

这个模块定义了统一的文件操作接口和两种实现方式：本地文件系统和沙箱环境。
它展示了如何使用协议和多态性设计跨环境的文件操作抽象，实现代码的可移植性和安全性。

教学点:
1. 协议设计: 使用Python Protocol定义接口
2. 多态实现: 不同环境下提供相同接口的不同实现
3. 环境抽象: 隔离环境差异，提供统一操作方式
4. 异步IO: 使用异步方法进行文件操作
5. 类型标注: 使用Python类型提示提高代码可读性和安全性
"""

import asyncio
from pathlib import Path
from typing import Optional, Protocol, Tuple, Union, runtime_checkable

from app.config import SandboxSettings
from app.exceptions import ToolError
from app.sandbox.client import SANDBOX_CLIENT

PathLike = Union[str, Path]  # 定义路径类型，可以是字符串或Path对象


@runtime_checkable
class FileOperator(Protocol):
    """文件操作接口协议。

    这个协议定义了文件操作的标准接口，允许在不同环境（如本地或沙箱）
    中实现相同的文件操作功能。使用Python的Protocol特性实现了结构化类型提示。

    设计理念:
    1. 接口与实现分离: 定义统一接口，允许多种实现
    2. 鸭子类型: 使用runtime_checkable支持运行时类型检查
    3. 异步设计: 所有操作都是异步的，避免IO阻塞

    Protocol特性:
    - 不需要显式继承，只需实现相同方法签名
    - 支持运行时检查，配合@runtime_checkable使用
    - 比抽象基类更灵活，更符合Python的动态特性
    """

    async def read_file(self, path: PathLike) -> str:
        """读取文件内容。

        参数:
            path: 文件路径，可以是字符串或Path对象。

        返回:
            文件内容字符串。

        异常:
            可能抛出与实现相关的异常。
        """
        ...

    async def write_file(self, path: PathLike, content: str) -> None:
        """写入内容到文件。

        参数:
            path: 文件路径，可以是字符串或Path对象。
            content: 要写入的内容字符串。

        异常:
            可能抛出与实现相关的异常。
        """
        ...

    async def is_directory(self, path: PathLike) -> bool:
        """检查路径是否指向目录。

        参数:
            path: 要检查的路径，可以是字符串或Path对象。

        返回:
            如果路径是目录则为True，否则为False。
        """
        ...

    async def exists(self, path: PathLike) -> bool:
        """检查路径是否存在。

        参数:
            path: 要检查的路径，可以是字符串或Path对象。

        返回:
            如果路径存在则为True，否则为False。
        """
        ...

    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        """运行shell命令并返回结果。

        参数:
            cmd: 要执行的shell命令。
            timeout: 命令执行超时时间（秒），None表示无超时。

        返回:
            包含返回码、标准输出和标准错误的元组。

        异常:
            可能抛出超时或执行错误相关的异常。
        """
        ...


class LocalFileOperator(FileOperator):
    """本地文件系统操作实现。

    这个类实现了FileOperator协议，提供对本地文件系统的操作支持。
    它使用标准的Python文件IO操作，并包装为异步接口。

    设计模式:
    1. 适配器模式: 将同步文件操作转换为异步接口
    2. 错误转换: 将底层异常包装为统一的ToolError

    属性:
        encoding: 文件读写使用的编码，默认为utf-8。
    """

    encoding: str = "utf-8"

    async def read_file(self, path: PathLike) -> str:
        """读取本地文件内容。

        使用Path对象标准方法读取文件，并处理可能的异常。

        实现细节:
        - 使用Path.read_text处理编码细节
        - 捕获所有异常并转换为ToolError
        - 使用from None清除异常链，简化错误信息

        参数:
            path: 本地文件路径。

        返回:
            文件内容字符串。

        异常:
            ToolError: 如果文件读取失败。
        """
        try:
            return Path(path).read_text(encoding=self.encoding)
        except Exception as e:
            raise ToolError(f"Failed to read {path}: {str(e)}") from None

    async def write_file(self, path: PathLike, content: str) -> None:
        """写入内容到本地文件。

        使用Path对象标准方法写入文件，并处理可能的异常。

        参数:
            path: 本地文件路径。
            content: 要写入的内容字符串。

        异常:
            ToolError: 如果文件写入失败。
        """
        try:
            Path(path).write_text(content, encoding=self.encoding)
        except Exception as e:
            raise ToolError(f"Failed to write to {path}: {str(e)}") from None

    async def is_directory(self, path: PathLike) -> bool:
        """检查本地路径是否指向目录。

        参数:
            path: 要检查的本地路径。

        返回:
            如果路径是目录则为True，否则为False。
        """
        return Path(path).is_dir()

    async def exists(self, path: PathLike) -> bool:
        """检查本地路径是否存在。

        参数:
            path: 要检查的本地路径。

        返回:
            如果路径存在则为True，否则为False。
        """
        return Path(path).exists()

    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        """在本地运行shell命令。

        这个方法使用asyncio子进程功能异步执行命令，并支持超时控制。
        它展示了如何使用Python的异步子进程来执行命令和获取结果。

        实现技巧:
        1. 异步子进程: 使用asyncio.create_subprocess_shell创建子进程
        2. 流捕获: 捕获标准输出和标准错误流
        3. 超时控制: 使用asyncio.wait_for实现超时
        4. 进程清理: 在超时情况下尝试终止进程

        参数:
            cmd: 要执行的shell命令。
            timeout: 命令执行超时时间（秒）。

        返回:
            包含返回码、标准输出和标准错误的元组。

        异常:
            TimeoutError: 如果命令执行超时。
        """
        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
            return (
                process.returncode or 0,
                stdout.decode(),
                stderr.decode(),
            )
        except asyncio.TimeoutError as exc:
            try:
                process.kill()  # 尝试终止超时进程
            except ProcessLookupError:
                pass  # 进程可能已经结束
            raise TimeoutError(
                f"Command '{cmd}' timed out after {timeout} seconds"
            ) from exc


class SandboxFileOperator(FileOperator):
    """沙箱环境文件操作实现。

    这个类实现了FileOperator协议，提供对隔离沙箱环境的文件操作支持。
    它通过沙箱客户端转发所有操作，确保在安全的隔离环境中执行。

    设计模式:
    1. 代理模式: 将操作转发到沙箱客户端
    2. 懒加载: 按需初始化沙箱环境

    属性:
        sandbox_client: 用于与沙箱通信的客户端实例。
    """

    def __init__(self):
        """初始化沙箱文件操作器。

        设置沙箱客户端引用，但不立即初始化沙箱环境，实现延迟加载。
        """
        self.sandbox_client = SANDBOX_CLIENT

    async def _ensure_sandbox_initialized(self):
        """确保沙箱已初始化。

        这个辅助方法检查并在需要时初始化沙箱环境。
        它实现了懒加载模式，只在实际需要时创建资源。
        """
        if not self.sandbox_client.sandbox:
            await self.sandbox_client.create(config=SandboxSettings())

    async def read_file(self, path: PathLike) -> str:
        """读取沙箱中的文件内容。

        通过沙箱客户端读取文件，确保在隔离环境中操作。

        参数:
            path: 沙箱中的文件路径。

        返回:
            文件内容字符串。

        异常:
            ToolError: 如果文件读取失败。
        """
        await self._ensure_sandbox_initialized()
        try:
            return await self.sandbox_client.read_file(str(path))
        except Exception as e:
            raise ToolError(f"Failed to read {path} in sandbox: {str(e)}") from None

    async def write_file(self, path: PathLike, content: str) -> None:
        """写入内容到沙箱中的文件。

        通过沙箱客户端写入文件，确保在隔离环境中操作。

        参数:
            path: 沙箱中的文件路径。
            content: 要写入的内容字符串。

        异常:
            ToolError: 如果文件写入失败。
        """
        await self._ensure_sandbox_initialized()
        try:
            await self.sandbox_client.write_file(str(path), content)
        except Exception as e:
            raise ToolError(f"Failed to write to {path} in sandbox: {str(e)}") from None

    async def is_directory(self, path: PathLike) -> bool:
        """检查沙箱中的路径是否指向目录。

        通过在沙箱中执行shell命令检查路径类型。

        实现技巧:
        使用shell的test命令，这比通过客户端API更加灵活

        参数:
            path: 要检查的沙箱路径。

        返回:
            如果路径是目录则为True，否则为False。
        """
        await self._ensure_sandbox_initialized()
        result = await self.sandbox_client.run_command(
            f"test -d {path} && echo 'true' || echo 'false'"
        )
        return result.strip() == "true"

    async def exists(self, path: PathLike) -> bool:
        """检查沙箱中的路径是否存在。

        通过在沙箱中执行shell命令检查路径存在性。

        参数:
            path: 要检查的沙箱路径。

        返回:
            如果路径存在则为True，否则为False。
        """
        await self._ensure_sandbox_initialized()
        result = await self.sandbox_client.run_command(
            f"test -e {path} && echo 'true' || echo 'false'"
        )
        return result.strip() == "true"

    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        """在沙箱中运行shell命令。

        通过沙箱客户端执行命令，确保在隔离环境中操作。

        实现限制:
        当前沙箱实现只能获取标准输出，不能获取返回码和标准错误

        参数:
            cmd: 要执行的shell命令。
            timeout: 命令执行超时时间（秒）。

        返回:
            包含返回码、标准输出和标准错误的元组（但沙箱中总是返回0作为返回码，空字符串作为标准错误）。

        异常:
            TimeoutError: 如果命令执行超时。
        """
        await self._ensure_sandbox_initialized()
        try:
            stdout = await self.sandbox_client.run_command(
                cmd, timeout=int(timeout) if timeout else None
            )
            return (
                0,  # 始终返回0，因为当前沙箱实现不提供明确的返回码
                stdout,
                "",  # 当前沙箱实现不捕获标准错误
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"Command '{cmd}' timed out after {timeout} seconds in sandbox"
            ) from exc
        except Exception as exc:
            return 1, "", f"Error executing command in sandbox: {str(exc)}"
