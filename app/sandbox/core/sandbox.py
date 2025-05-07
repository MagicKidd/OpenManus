import asyncio
import io
import os
import tarfile
import tempfile
import uuid
from typing import Dict, Optional

import docker
from docker.errors import NotFound
from docker.models.containers import Container

from app.config import SandboxSettings
from app.sandbox.core.exceptions import SandboxTimeoutError
from app.sandbox.core.terminal import AsyncDockerizedTerminal


class DockerSandbox:
    """Docker沙箱环境。

    提供一个带有资源限制、文件操作和命令执行能力的容器化执行环境。

    教学点:
    1. 沙箱模式: 通过隔离环境确保安全执行不受信任的代码
    2. 资源限制: 防止DoS攻击和资源耗尽
    3. 文件系统隔离: 保护主机文件系统，防止未授权访问
    4. Docker容器化: 利用容器技术实现轻量级隔离

    Attributes:
        config: 沙箱配置。
        volume_bindings: 卷映射配置。
        client: Docker客户端。
        container: Docker容器实例。
        terminal: 容器终端接口。
    """

    def __init__(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
    ):
        """初始化沙箱实例。

        沙箱设计原则:
        1. 可配置性: 通过配置对象定制沙箱行为
        2. 资源控制: 限制内存、CPU和网络使用
        3. 文件系统隔离: 通过卷映射控制文件访问
        4. 默认安全: 没有显式配置时使用安全的默认值

        Args:
            config: 沙箱配置。如果为None，使用默认配置。
            volume_bindings: {主机路径: 容器路径}格式的卷映射。
        """
        self.config = config or SandboxSettings()
        self.volume_bindings = volume_bindings or {}
        self.client = docker.from_env()
        self.container: Optional[Container] = None
        self.terminal: Optional[AsyncDockerizedTerminal] = None

    async def create(self) -> "DockerSandbox":
        """创建并启动沙箱容器。

        这个方法执行以下关键步骤:
        1. 准备容器配置，包括资源限制和卷映射
        2. 创建并启动Docker容器
        3. 初始化终端接口

        错误处理模式:
        采用try-except-finally模式确保资源在出错时正确清理

        Returns:
            当前沙箱实例。

        Raises:
            docker.errors.APIError: 如果Docker API调用失败。
            RuntimeError: 如果容器创建或启动失败。
        """
        try:
            # 准备容器配置
            host_config = self.client.api.create_host_config(
                mem_limit=self.config.memory_limit,  # 内存限制
                cpu_period=100000,  # CPU周期
                cpu_quota=int(100000 * self.config.cpu_limit),  # CPU配额
                network_mode=(
                    "none" if not self.config.network_enabled else "bridge"
                ),  # 网络模式
                binds=self._prepare_volume_bindings(),  # 卷映射
            )

            # 生成带有sandbox_前缀的唯一容器名
            container_name = f"sandbox_{uuid.uuid4().hex[:8]}"

            # 创建容器
            container = await asyncio.to_thread(
                self.client.api.create_container,
                image=self.config.image,
                command="tail -f /dev/null",  # 保持容器运行的空闲命令
                hostname="sandbox",
                working_dir=self.config.work_dir,
                host_config=host_config,
                name=container_name,
                tty=True,  # 分配TTY
                detach=True,  # 后台运行
            )

            self.container = self.client.containers.get(container["Id"])

            # 启动容器
            await asyncio.to_thread(self.container.start)

            # 初始化终端
            self.terminal = AsyncDockerizedTerminal(
                container["Id"],
                self.config.work_dir,
                env_vars={"PYTHONUNBUFFERED": "1"},  # 确保Python输出不缓冲
            )
            await self.terminal.init()

            return self

        except Exception as e:
            await self.cleanup()  # 确保资源被清理
            raise RuntimeError(f"Failed to create sandbox: {e}") from e

    def _prepare_volume_bindings(self) -> Dict[str, Dict[str, str]]:
        """准备卷绑定配置。

        卷映射是Docker提供的关键功能，允许:
        1. 在主机和容器之间共享文件/目录
        2. 在容器重启后保留数据
        3. 在多个容器之间共享数据

        设计模式:
        辅助方法封装复杂逻辑，遵循单一责任原则

        Returns:
            卷绑定配置字典。
        """
        bindings = {}

        # 创建并添加工作目录映射
        work_dir = self._ensure_host_dir(self.config.work_dir)
        bindings[work_dir] = {"bind": self.config.work_dir, "mode": "rw"}

        # 添加自定义卷绑定
        for host_path, container_path in self.volume_bindings.items():
            bindings[host_path] = {"bind": container_path, "mode": "rw"}

        return bindings

    @staticmethod
    def _ensure_host_dir(path: str) -> str:
        """确保主机上目录存在。

        这个方法展示了临时目录创建的最佳实践:
        1. 使用标准tempfile模块创建临时目录
        2. 添加随机后缀避免冲突
        3. 使用os.makedirs确保目录存在

        设计模式:
        静态方法(@staticmethod)用于不需要访问实例状态的工具函数

        Args:
            path: 目录路径。

        Returns:
            主机上的实际路径。
        """
        host_path = os.path.join(
            tempfile.gettempdir(),
            f"sandbox_{os.path.basename(path)}_{os.urandom(4).hex()}",
        )
        os.makedirs(host_path, exist_ok=True)
        return host_path

    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> str:
        """在沙箱中运行命令。

        通过AsyncDockerizedTerminal运行命令，确保:
        1. 超时控制，防止长时间运行的命令
        2. 异常处理和转换，提供更明确的错误信息
        3. 配置继承，使用全局超时默认值(如果未指定)

        错误处理模式:
        捕获并转换异常，提供更具体的错误类型(SandboxTimeoutError)

        Args:
            cmd: 要执行的命令。
            timeout: 超时时间(秒)。

        Returns:
            字符串形式的命令输出。

        Raises:
            RuntimeError: 如果沙箱未初始化或命令执行失败。
            TimeoutError: 如果命令执行超时。
        """
        if not self.terminal:
            raise RuntimeError("Sandbox not initialized")

        try:
            return await self.terminal.run_command(
                cmd, timeout=timeout or self.config.timeout
            )
        except TimeoutError:
            raise SandboxTimeoutError(
                f"Command execution timed out after {timeout or self.config.timeout} seconds"
            )

    async def read_file(self, path: str) -> str:
        """从容器读取文件。

        文件访问机制:
        使用Docker API的get_archive方法读取文件，这比执行shell命令更高效、安全。

        处理流程:
        1. 解析并验证文件路径
        2. 从容器获取文件归档(tar)
        3. 从tar提取文件内容
        4. 处理特定错误情况，如文件不存在

        Args:
            path: 文件路径。

        Returns:
            文件内容字符串。

        Raises:
            FileNotFoundError: 如果文件不存在。
            RuntimeError: 如果读取操作失败。
        """
        if not self.container:
            raise RuntimeError("Sandbox not initialized")

        try:
            # 获取文件归档
            resolved_path = self._safe_resolve_path(path)
            tar_stream, _ = await asyncio.to_thread(
                self.container.get_archive, resolved_path
            )

            # 从tar流中读取文件内容
            content = await self._read_from_tar(tar_stream)
            return content.decode("utf-8")

        except NotFound:
            raise FileNotFoundError(f"File not found: {path}")
        except Exception as e:
            raise RuntimeError(f"Failed to read file: {e}")

    async def write_file(self, path: str, content: str) -> None:
        """写入内容到容器中的文件。

        文件写入过程:
        1. 安全解析目标路径，防止路径遍历攻击
        2. 确保父目录存在
        3. 创建临时tar文件
        4. 使用Docker API将tar写入容器

        安全考虑:
        - 路径验证防止目录遍历
        - 内容编码处理

        Args:
            path: 目标路径。
            content: 文件内容。

        Raises:
            RuntimeError: 如果写入操作失败。
        """
        if not self.container:
            raise RuntimeError("Sandbox not initialized")

        try:
            resolved_path = self._safe_resolve_path(path)
            parent_dir = os.path.dirname(resolved_path)

            # 创建父目录
            if parent_dir:
                await self.run_command(f"mkdir -p {parent_dir}")

            # 准备文件数据
            tar_stream = await self._create_tar_stream(
                os.path.basename(path), content.encode("utf-8")
            )

            # 写入文件
            await asyncio.to_thread(
                self.container.put_archive, parent_dir or "/", tar_stream
            )

        except Exception as e:
            raise RuntimeError(f"Failed to write file: {e}")

    def _safe_resolve_path(self, path: str) -> str:
        """安全解析容器路径，防止路径遍历。

        安全编码关键点:
        - 检测路径中的".."模式，防止目录遍历攻击
        - 处理相对路径和绝对路径
        - 始终将相对路径解析为工作目录的子路径

        这是一种防御性编程技术，即使其他安全层失效也能提供保护。

        Args:
            path: 原始路径。

        Returns:
            解析后的绝对路径。

        Raises:
            ValueError: 如果路径包含潜在不安全的模式。
        """
        # 检查路径遍历尝试
        if ".." in path.split("/"):
            raise ValueError("Path contains potentially unsafe patterns")

        resolved = (
            os.path.join(self.config.work_dir, path)
            if not os.path.isabs(path)
            else path
        )
        return resolved

    async def copy_from(self, src_path: str, dst_path: str) -> None:
        """从容器复制文件。

        这个方法演示了更复杂的文件操作:
        1. 目录与文件的自动检测与处理
        2. 临时目录的使用进行中间处理
        3. 两种复制模式: 保留目录结构或单文件提取

        教学点:
        - 资源管理使用上下文管理器(with语句)
        - 异步与同步操作的混合处理
        - 文件系统异常处理

        Args:
            src_path: 源文件路径(容器)。
            dst_path: 目标路径(主机)。

        Raises:
            FileNotFoundError: 如果源文件不存在。
            RuntimeError: 如果复制操作失败。
        """
        try:
            # 确保目标文件的父目录存在
            parent_dir = os.path.dirname(dst_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # 获取文件流
            resolved_src = self._safe_resolve_path(src_path)
            stream, stat = await asyncio.to_thread(
                self.container.get_archive, resolved_src
            )

            # 创建临时目录提取文件
            with tempfile.TemporaryDirectory() as tmp_dir:
                # 将流写入临时文件
                tar_path = os.path.join(tmp_dir, "temp.tar")
                with open(tar_path, "wb") as f:
                    for chunk in stream:
                        f.write(chunk)

                # 提取文件
                with tarfile.open(tar_path) as tar:
                    members = tar.getmembers()
                    if not members:
                        raise FileNotFoundError(f"Source file is empty: {src_path}")

                    # 如果目标是目录，我们应该保留相对路径结构
                    if os.path.isdir(dst_path):
                        tar.extractall(dst_path)
                    else:
                        # 如果目标是文件，我们只提取源文件的内容
                        if len(members) > 1:
                            raise RuntimeError(
                                f"Source path is a directory but destination is a file: {src_path}"
                            )

                        with open(dst_path, "wb") as dst:
                            src_file = tar.extractfile(members[0])
                            if src_file is None:
                                raise RuntimeError(
                                    f"Failed to extract file: {src_path}"
                                )
                            dst.write(src_file.read())

        except docker.errors.NotFound:
            raise FileNotFoundError(f"Source file not found: {src_path}")
        except Exception as e:
            raise RuntimeError(f"Failed to copy file: {e}")

    async def copy_to(self, src_path: str, dst_path: str) -> None:
        """复制文件到容器。

        比起write_file方法，这个方法提供更强大的功能:
        1. 支持复制整个目录树而不仅是单个文件
        2. 处理源路径是目录或文件的不同情况
        3. 自动创建目标目录结构
        4. 验证复制操作成功

        编程范式:
        嵌套的上下文管理器(with语句)用于资源清理

        Args:
            src_path: 源文件路径(主机)。
            dst_path: 目标路径(容器)。

        Raises:
            FileNotFoundError: 如果源文件不存在。
            RuntimeError: 如果复制操作失败。
        """
        try:
            if not os.path.exists(src_path):
                raise FileNotFoundError(f"Source file not found: {src_path}")

            # 在容器中创建目标目录
            resolved_dst = self._safe_resolve_path(dst_path)
            container_dir = os.path.dirname(resolved_dst)
            if container_dir:
                await self.run_command(f"mkdir -p {container_dir}")

            # 创建要上传的tar文件
            with tempfile.TemporaryDirectory() as tmp_dir:
                tar_path = os.path.join(tmp_dir, "temp.tar")
                with tarfile.open(tar_path, "w") as tar:
                    # 处理目录源路径
                    if os.path.isdir(src_path):
                        os.path.basename(src_path.rstrip("/"))
                        for root, _, files in os.walk(src_path):
                            for file in files:
                                file_path = os.path.join(root, file)
                                arcname = os.path.join(
                                    os.path.basename(dst_path),
                                    os.path.relpath(file_path, src_path),
                                )
                                tar.add(file_path, arcname=arcname)
                    else:
                        # 添加单个文件到tar
                        tar.add(src_path, arcname=os.path.basename(dst_path))

                # 读取tar文件内容
                with open(tar_path, "rb") as f:
                    data = f.read()

                # 上传到容器
                await asyncio.to_thread(
                    self.container.put_archive,
                    os.path.dirname(resolved_dst) or "/",
                    data,
                )

                # 验证文件是否成功创建
                try:
                    await self.run_command(f"test -e {resolved_dst}")
                except Exception:
                    raise RuntimeError(f"Failed to verify file creation: {dst_path}")

        except FileNotFoundError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to copy file: {e}")

    @staticmethod
    async def _create_tar_stream(name: str, content: bytes) -> io.BytesIO:
        """创建tar文件流。

        这个辅助方法展示了:
        1. 使用内存中文件流而非磁盘文件提高效率
        2. Python tarfile模块的高级用法
        3. 文件元数据(tarinfo)的设置

        静态方法设计:
        此方法是无状态的工具函数，适合作为静态方法

        Args:
            name: 文件名。
            content: 文件内容。

        Returns:
            Tar文件流。
        """
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            tarinfo = tarfile.TarInfo(name=name)
            tarinfo.size = len(content)
            tar.addfile(tarinfo, io.BytesIO(content))
        tar_stream.seek(0)
        return tar_stream

    @staticmethod
    async def _read_from_tar(tar_stream) -> bytes:
        """从tar流中读取文件内容。

        处理流程:
        1. 将流写入临时文件
        2. 打开tar文件并提取内容
        3. 读取第一个文件的内容

        异常处理策略:
        为常见错误提供明确的错误消息

        Args:
            tar_stream: Tar文件流。

        Returns:
            文件内容。

        Raises:
            RuntimeError: 如果读取操作失败。
        """
        with tempfile.NamedTemporaryFile() as tmp:
            for chunk in tar_stream:
                tmp.write(chunk)
            tmp.seek(0)

            with tarfile.open(fileobj=tmp) as tar:
                member = tar.next()
                if not member:
                    raise RuntimeError("Empty tar archive")

                file_content = tar.extractfile(member)
                if not file_content:
                    raise RuntimeError("Failed to extract file content")

                return file_content.read()

    async def cleanup(self) -> None:
        """清理沙箱资源。

        资源清理的最佳实践:
        1. 终端关闭先于容器停止，确保所有进程正确终止
        2. 容器停止使用超时，防止无限等待
        3. 强制移除确保清理完成
        4. 收集错误但不中断清理过程

        这是健壮系统的关键部分，确保资源不会泄漏。
        """
        errors = []
        try:
            if self.terminal:
                try:
                    await self.terminal.close()
                except Exception as e:
                    errors.append(f"Terminal cleanup error: {e}")
                finally:
                    self.terminal = None

            if self.container:
                try:
                    await asyncio.to_thread(self.container.stop, timeout=5)
                except Exception as e:
                    errors.append(f"Container stop error: {e}")

                try:
                    await asyncio.to_thread(self.container.remove, force=True)
                except Exception as e:
                    errors.append(f"Container remove error: {e}")
                finally:
                    self.container = None

        except Exception as e:
            errors.append(f"General cleanup error: {e}")

        if errors:
            print(f"Warning: Errors during cleanup: {', '.join(errors)}")

    async def __aenter__(self) -> "DockerSandbox":
        """异步上下文管理器入口。

        支持Python的异步上下文管理协议，使沙箱可以在async with语句中使用:

        ```python
        async with DockerSandbox() as sandbox:
            # 在这里使用沙箱
        # 超出作用域后自动清理
        ```
        """
        return await self.create()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器退出。

        不管是否发生异常，确保资源被清理，防止资源泄漏。
        这是Python资源管理的最佳实践。
        """
        await self.cleanup()
