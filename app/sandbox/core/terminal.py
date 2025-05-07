"""
异步Docker终端 (Asynchronous Docker Terminal)

这个模块提供了Docker容器的异步终端功能，允许带有超时控制的交互式命令执行。

教学点:
1. 异步编程: 使用Python的asyncio库实现非阻塞I/O操作
2. 套接字通信: 底层套接字编程实现与Docker容器的实时通信
3. 资源管理: 使用上下文管理器确保资源正确关闭
4. 安全性: 命令注入防护与超时控制机制
5. 抽象分层: 低级会话管理(DockerSession)与高级终端接口(AsyncDockerizedTerminal)的分离
"""

import asyncio
import re
import socket
from typing import Dict, Optional, Tuple, Union

import docker
from docker import APIClient
from docker.errors import APIError
from docker.models.containers import Container


class DockerSession:
    def __init__(self, container_id: str) -> None:
        """初始化Docker会话。

        这个类处理与Docker容器的低级别套接字通信，管理执行环境和命令处理。

        设计理念:
        - 单一责任原则: 这个类只负责底层与Docker的通信
        - 封装: 隐藏通信细节，提供简洁的接口给上层调用

        Args:
            container_id: Docker容器的ID
        """
        self.api = APIClient()  # 使用Docker低级API客户端
        self.container_id = container_id
        self.exec_id = None  # 执行实例ID
        self.socket = None  # 通信套接字

    async def create(self, working_dir: str, env_vars: Dict[str, str]) -> None:
        """创建与容器的交互会话。

        这个方法执行几个关键步骤:
        1. 创建bash执行环境，配置提示符和工作目录
        2. 建立双向通信通道(通过套接字)
        3. 等待shell准备就绪

        异步编程要点:
        - 非阻塞套接字操作
        - 等待提示符出现而不阻塞主事件循环

        Args:
            working_dir: 容器内的工作目录
            env_vars: 要设置的环境变量

        Raises:
            RuntimeError: 如果套接字连接失败
        """
        # 设置启动命令，配置干净的bash环境
        startup_command = [
            "bash",
            "-c",
            f"cd {working_dir} && "
            "PROMPT_COMMAND='' "  # 删除任何额外的提示命令
            "PS1='$ ' "  # 设置简单的提示符，便于识别
            "exec bash --norc --noprofile",  # 不加载额外配置文件，确保干净环境
        ]

        # 创建执行实例
        exec_data = self.api.exec_create(
            self.container_id,
            startup_command,
            stdin=True,  # 允许输入
            tty=True,  # 分配TTY终端
            stdout=True,  # 捕获标准输出
            stderr=True,  # 捕获标准错误
            privileged=True,  # 特权模式
            user="root",  # 以root用户运行
            environment={**env_vars, "TERM": "dumb", "PS1": "$ ", "PROMPT_COMMAND": ""},
        )
        self.exec_id = exec_data["Id"]

        # 启动执行实例并获取套接字
        socket_data = self.api.exec_start(
            self.exec_id,
            socket=True,  # 返回套接字对象
            tty=True,  # 启用TTY
            stream=True,  # 流式传输
            demux=True,  # 分离标准输出和标准错误
        )

        # 获取并配置套接字
        if hasattr(socket_data, "_sock"):
            self.socket = socket_data._sock
            self.socket.setblocking(False)  # 设置为非阻塞模式，关键点！
        else:
            raise RuntimeError("Failed to get socket connection")

        # 等待提示符出现，确认shell准备就绪
        await self._read_until_prompt()

    async def close(self) -> None:
        """清理会话资源。

        资源管理最佳实践:
        1. 发送exit命令，优雅地关闭bash会话
        2. 关闭套接字连接
        3. 检查并清理执行实例

        错误处理策略:
        - 使用try/except捕获所有清理过程中的错误
        - 继续完成所有清理步骤，即使某一步失败
        - 打印警告而不是抛出异常，确保清理过程不中断
        """
        try:
            if self.socket:
                # 发送exit命令来关闭bash会话
                try:
                    self.socket.sendall(b"exit\n")
                    # 允许命令执行的时间
                    await asyncio.sleep(0.1)
                except:
                    pass  # 忽略发送错误，继续清理

                # 关闭套接字连接
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                except:
                    pass  # 某些平台可能不支持shutdown

                self.socket.close()
                self.socket = None

            if self.exec_id:
                try:
                    # 检查执行实例状态
                    exec_inspect = self.api.exec_inspect(self.exec_id)
                    if exec_inspect.get("Running", False):
                        # 如果仍在运行，等待其完成
                        await asyncio.sleep(0.5)
                except:
                    pass  # 忽略检查错误，继续清理

                self.exec_id = None

        except Exception as e:
            # 记录错误但不抛出，确保清理继续
            print(f"Warning: Error during session cleanup: {e}")

    async def _read_until_prompt(self) -> str:
        """读取输出直到发现提示符。

        这是一个关键的辅助方法，用于同步与shell的交互。通过等待提示符($ )，
        我们知道先前的命令已完成执行，shell准备接收新命令。

        异步I/O模式:
        - 非阻塞套接字读取
        - 短暂睡眠以避免CPU忙等待
        - 持续累积输出直到找到提示符

        Returns:
            包含直到提示符的输出的字符串

        Raises:
            socket.error: 如果套接字通信失败
        """
        buffer = b""
        while b"$ " not in buffer:
            try:
                chunk = self.socket.recv(4096)  # 非阻塞读取
                if chunk:
                    buffer += chunk
            except socket.error as e:
                if e.errno == socket.EWOULDBLOCK:
                    # 没有可用数据时会出现此错误，这是正常的非阻塞行为
                    await asyncio.sleep(0.1)  # 短睡眠避免忙等待
                    continue
                raise  # 其他套接字错误则抛出
        return buffer.decode("utf-8")

    async def execute(self, command: str, timeout: Optional[int] = None) -> str:
        """执行命令并返回清理后的输出。

        这个方法的设计展示了几个高级技术：
        1. 命令清理和安全检查以防止注入
        2. 使用嵌套的async函数进行复杂的异步数据处理
        3. 输出解析和过滤以提供干净的结果
        4. 超时机制避免命令挂起

        Args:
            command: 要执行的shell命令
            timeout: 最大执行时间（秒）

        Returns:
            命令输出字符串，已移除提示符标记

        Raises:
            RuntimeError: 如果会话未初始化或执行失败
            TimeoutError: 如果命令执行超过超时时间
        """
        if not self.socket:
            raise RuntimeError("Session not initialized")

        try:
            # 清理命令以防止shell注入
            sanitized_command = self._sanitize_command(command)
            # 添加回显退出状态码，帮助我们后续处理
            full_command = f"{sanitized_command}\necho $?\n"
            self.socket.sendall(full_command.encode())

            # 定义异步函数来读取并处理输出
            async def read_output() -> str:
                buffer = b""
                result_lines = []
                command_sent = False

                while True:
                    try:
                        chunk = self.socket.recv(4096)
                        if not chunk:
                            break

                        buffer += chunk
                        lines = buffer.split(b"\n")

                        buffer = lines[-1]  # 保留最后一个（可能不完整的）行
                        lines = lines[:-1]  # 处理所有完整行

                        for line in lines:
                            line = line.rstrip(b"\r")  # 移除Windows风格的行尾

                            # 忽略我们发送的命令行
                            if not command_sent:
                                command_sent = True
                                continue

                            # 忽略我们添加的echo命令和退出码
                            if line.strip() == b"echo $?" or line.strip().isdigit():
                                continue

                            # 只添加非空行
                            if line.strip():
                                result_lines.append(line)

                        # 如果看到提示符，表示命令执行完毕
                        if buffer.endswith(b"$ "):
                            break

                    except socket.error as e:
                        if e.errno == socket.EWOULDBLOCK:
                            await asyncio.sleep(0.1)
                            continue
                        raise

                # 将结果合并为单个字符串并清理
                output = b"\n".join(result_lines).decode("utf-8")
                # 移除可能混入的提示符和回显命令
                output = re.sub(r"\n\$ echo \$\$?.*$", "", output)

                return output

            # 应用超时控制（如果指定）
            if timeout:
                result = await asyncio.wait_for(read_output(), timeout)
            else:
                result = await read_output()

            return result.strip()

        except asyncio.TimeoutError:
            raise TimeoutError(f"Command execution timed out after {timeout} seconds")
        except Exception as e:
            raise RuntimeError(f"Failed to execute command: {e}")

    def _sanitize_command(self, command: str) -> str:
        """清理命令字符串以防止shell注入。

        安全最佳实践:
        - 检查危险命令模式
        - 拒绝可能会损坏系统的命令

        这是一种基础的安全措施。在完整的实现中，可能还会添加更复杂的命令解析、
        字符转义和沙箱限制。

        Args:
            command: 原始命令字符串

        Returns:
            清理后的命令字符串

        Raises:
            ValueError: 如果命令包含潜在危险的模式
        """

        # 检查特定的危险命令
        risky_commands = [
            "rm -rf /",  # 删除整个文件系统
            "rm -rf /*",  # 删除根目录下所有内容
            "mkfs",  # 格式化文件系统
            "dd if=/dev/zero",  # 磁盘操作可能导致数据丢失
            ":(){:|:&};:",  # Fork炸弹
            "chmod -R 777 /",  # 危险的权限更改
            "chown -R",  # 危险的所有权更改
        ]

        for risky in risky_commands:
            if risky in command.lower():
                raise ValueError(
                    f"Command contains potentially dangerous operation: {risky}"
                )

        return command


class AsyncDockerizedTerminal:
    def __init__(
        self,
        container: Union[str, Container],
        working_dir: str = "/workspace",
        env_vars: Optional[Dict[str, str]] = None,
        default_timeout: int = 60,
    ) -> None:
        """初始化Docker容器的异步终端。

        这个类是对底层DockerSession的高级封装，提供简洁的API接口。
        它展示了以下设计模式:

        1. 门面模式(Facade Pattern): 为复杂的底层会话提供简化接口
        2. 策略模式(Strategy Pattern): 允许配置工作目录、环境变量等
        3. 工厂方法: 负责创建和初始化底层会话对象

        Args:
            container: Docker容器ID或Container对象
            working_dir: 容器内的工作目录
            env_vars: 环境变量字典
            default_timeout: 默认命令执行超时时间(秒)
        """
        self.client = docker.from_env()
        # 支持灵活的输入类型 - 字符串ID或Container对象
        self.container = (
            container
            if isinstance(container, Container)
            else self.client.containers.get(container)
        )
        self.working_dir = working_dir
        self.env_vars = env_vars or {}
        self.default_timeout = default_timeout
        self.session = None  # 将在init()中创建

    async def init(self) -> None:
        """初始化终端环境。

        执行两个关键步骤:
        1. 确保工作目录存在
        2. 创建交互式会话

        初始化模式:
        明确分离构造函数和初始化逻辑，允许异步初始化

        Raises:
            RuntimeError: 如果初始化失败
        """
        await self._ensure_workdir()

        self.session = DockerSession(self.container.id)
        await self.session.create(self.working_dir, self.env_vars)

    async def _ensure_workdir(self) -> None:
        """确保容器中工作目录存在。

        教学点:
        1. 辅助方法使用下划线前缀(_)，表明它是私有实现细节
        2. 使用独立方法分离关注点，遵循单一责任原则

        Raises:
            RuntimeError: 如果目录创建失败
        """
        try:
            await self._exec_simple(f"mkdir -p {self.working_dir}")
        except APIError as e:
            raise RuntimeError(f"Failed to create working directory: {e}")

    async def _exec_simple(self, cmd: str) -> Tuple[int, str]:
        """使用Docker的exec_run执行简单命令。

        这个辅助方法用于直接调用Docker API进行简单的命令执行，
        不使用交互式会话。适用于初始化步骤等特殊情况。

        教学点:
        使用"asyncio.to_thread"将同步操作转为异步操作，这是Python 3.9+的新功能，
        用于避免阻塞事件循环。

        Args:
            cmd: 要执行的命令

        Returns:
            (退出代码, 输出)的元组
        """
        result = await asyncio.to_thread(
            self.container.exec_run, cmd, environment=self.env_vars
        )
        return result.exit_code, result.output.decode("utf-8")

    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> str:
        """在容器中运行带超时的命令。

        这是公共API的主要入口点，提供简洁的命令执行接口。

        Args:
            cmd: 要执行的shell命令
            timeout: 最大执行时间(秒)

        Returns:
            命令输出字符串

        Raises:
            RuntimeError: 如果终端未初始化
        """
        if not self.session:
            raise RuntimeError("Terminal not initialized")

        return await self.session.execute(cmd, timeout=timeout or self.default_timeout)

    async def close(self) -> None:
        """关闭终端会话，释放资源。"""
        if self.session:
            await self.session.close()

    async def __aenter__(self) -> "AsyncDockerizedTerminal":
        """异步上下文管理器入口。

        支持Python的'async with'语句，实现资源管理的现代模式。
        """
        await self.init()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器退出。

        确保无论代码块如何退出(正常或异常)，资源都被清理。
        """
        await self.close()
