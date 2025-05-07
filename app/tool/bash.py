"""
命令行工具模块 (Command Line Tool Module)

这个模块实现了智能体执行命令行操作的能力，通过异步的方式与系统shell交互。
它展示了如何安全地封装底层命令行操作，处理输入/输出，并管理进程生命周期。

教学点:
1. 异步编程: 使用asyncio实现非阻塞命令执行
2. 进程管理: 创建、交互和终止子进程
3. 流控制: 处理标准输入/输出/错误流
4. 超时处理: 实现命令执行的超时机制
5. 上下文隔离: 会话管理与状态保持
"""

import asyncio
import os
from typing import Optional

from app.exceptions import ToolError
from app.tool.base import BaseTool, CLIResult

_BASH_DESCRIPTION = """Execute a bash command in the terminal.
* Long running commands: For commands that may run indefinitely, it should be run in the background and the output should be redirected to a file, e.g. command = `python3 app.py > server.log 2>&1 &`.
* Interactive: If a bash command returns exit code `-1`, this means the process is not yet finished. The assistant must then send a second call to terminal with an empty `command` (which will retrieve any additional logs), or it can send additional text (set `command` to the text) to STDIN of the running process, or it can send command=`ctrl+c` to interrupt the process.
* Timeout: If a command execution result says "Command timed out. Sending SIGINT to the process", the assistant should retry running the command in the background.
"""


class _BashSession:
    """Bash会话管理类。

    这个类管理与bash shell的持续会话，处理进程创建、命令执行、输出捕获等低级操作。
    它使用了单一职责原则，专注于维护与shell的交互，而不涉及更高级的工具逻辑。

    设计理念:
    1. 封装复杂性: 隐藏与底层进程通信的复杂细节
    2. 状态管理: 维护会话状态（已启动/已超时等）
    3. 资源清理: 确保进程在不需要时被终止

    属性:
        _started: 指示会话是否已启动。
        _process: 底层子进程对象。
        command: 要执行的shell命令（默认为/bin/bash）。
        _output_delay: 读取输出的延迟时间。
        _timeout: 命令执行超时时间。
        _sentinel: 用于标记命令执行完成的特殊字符串。
    """

    _started: bool
    _process: asyncio.subprocess.Process

    command: str = "/bin/bash"
    _output_delay: float = 0.2  # 秒
    _timeout: float = 120.0  # 秒
    _sentinel: str = "<<exit>>"

    def __init__(self):
        """初始化Bash会话。

        创建一个新的会话管理器，但不立即启动进程。
        这遵循了惰性初始化原则，只在需要时分配资源。
        """
        self._started = False
        self._timed_out = False

    async def start(self):
        """启动bash会话。

        创建一个新的bash子进程，并设置用于交互的管道。

        异步编程要点:
        - 使用asyncio.create_subprocess_shell创建非阻塞子进程
        - 配置管道用于双向通信(stdin/stdout/stderr)

        系统编程要点:
        - 使用preexec_fn设置进程组ID，便于后续发送信号
        - 设置bufsize=0禁用缓冲，确保实时数据流
        """
        if self._started:
            return

        self._process = await asyncio.create_subprocess_shell(
            self.command,
            preexec_fn=os.setsid,  # 在新的进程组中启动shell
            shell=True,
            bufsize=0,  # 无缓冲，确保实时输出
            stdin=asyncio.subprocess.PIPE,  # 允许向进程写入
            stdout=asyncio.subprocess.PIPE,  # 捕获标准输出
            stderr=asyncio.subprocess.PIPE,  # 捕获标准错误
        )

        self._started = True

    def stop(self):
        """终止bash会话。

        结束底层进程，释放资源。这是资源管理的重要环节，
        确保不再需要的进程被正确终止，避免资源泄露。

        错误处理策略:
        - 检查会话是否已启动，防止终止不存在的进程
        - 检查进程是否已结束，避免重复终止操作

        异常:
            ToolError: 如果会话未启动。
        """
        if not self._started:
            raise ToolError("Session has not started.")
        if self._process.returncode is not None:
            return
        self._process.terminate()

    async def run(self, command: str):
        """在bash会话中执行命令。

        这是会话的核心方法，负责:
        1. 向bash进程发送命令
        2. 等待并收集输出结果
        3. 处理超时情况
        4. 清理输出流中的数据

        实现技巧:
        - 使用哨兵值(sentinel)标记命令完成，避免无限等待
        - 使用asyncio.timeout管理超时，防止命令挂起
        - 直接访问缓冲区获取数据，避免阻塞

        参数:
            command: 要执行的bash命令。

        返回:
            CLIResult: 包含命令输出和错误信息的结果对象。

        异常:
            ToolError: 如果会话未启动、已超时或需要重启。
        """
        if not self._started:
            raise ToolError("Session has not started.")
        if self._process.returncode is not None:
            return CLIResult(
                system="tool must be restarted",
                error=f"bash has exited with returncode {self._process.returncode}",
            )
        if self._timed_out:
            raise ToolError(
                f"timed out: bash has not returned in {self._timeout} seconds and must be restarted",
            )

        # 确保标准流已初始化（非None）
        assert self._process.stdin
        assert self._process.stdout
        assert self._process.stderr

        # 向进程发送命令，并添加哨兵标记来检测命令完成
        self._process.stdin.write(
            command.encode() + f"; echo '{self._sentinel}'\n".encode()
        )
        await self._process.stdin.drain()  # 确保命令被完全写入

        # 读取进程输出直到找到哨兵标记或超时
        try:
            async with asyncio.timeout(self._timeout):  # 使用上下文管理器管理超时
                while True:
                    await asyncio.sleep(self._output_delay)  # 短暂睡眠避免CPU忙等待
                    # 直接访问缓冲区读取数据，而不是等待EOF
                    output = (
                        self._process.stdout._buffer.decode()
                    )  # pyright: ignore[reportAttributeAccessIssue]
                    if self._sentinel in output:
                        # 找到哨兵标记，清理输出并结束循环
                        output = output[: output.index(self._sentinel)]
                        break
        except asyncio.TimeoutError:
            # 超时处理：标记会话已超时，并抛出异常
            self._timed_out = True
            raise ToolError(
                f"timed out: bash has not returned in {self._timeout} seconds and must be restarted",
            ) from None

        # 清理输出末尾的换行符
        if output.endswith("\n"):
            output = output[:-1]

        # 读取标准错误流
        error = (
            self._process.stderr._buffer.decode()
        )  # pyright: ignore[reportAttributeAccessIssue]
        if error.endswith("\n"):
            error = error[:-1]

        # 清理缓冲区，为下一次命令做准备
        self._process.stdout._buffer.clear()  # pyright: ignore[reportAttributeAccessIssue]
        self._process.stderr._buffer.clear()  # pyright: ignore[reportAttributeAccessIssue]

        return CLIResult(output=output, error=error)


class Bash(BaseTool):
    """Bash命令执行工具。

    这个类是高层的工具接口，继承自BaseTool，提供了执行bash命令的功能。
    它管理一个长期运行的bash会话，允许多次命令执行，保持会话状态。

    设计模式:
    1. 外观模式(Facade Pattern): 为复杂的底层_BashSession提供简化的接口
    2. 状态模式: 维护会话状态并根据需要重启

    教学点:
    - 面向对象设计中的层次结构（高级接口 vs 低级实现）
    - 如何在异步环境中管理有状态会话

    属性:
        name: 工具的名称标识符。
        description: 工具功能的描述文本。
        parameters: 工具参数的JSON Schema定义。
        _session: 内部的bash会话对象。
    """

    name: str = "bash"
    description: str = _BASH_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute. Can be empty to view additional logs when previous exit code is `-1`. Can be `ctrl+c` to interrupt the currently running process.",
            },
        },
        "required": ["command"],
    }

    _session: Optional[_BashSession] = None

    async def execute(
        self, command: str | None = None, restart: bool = False, **kwargs
    ) -> CLIResult:
        """执行bash命令或管理会话。

        这个方法实现了BaseTool的抽象execute方法，是工具的主要入口点。
        它管理bash会话的生命周期，并处理命令执行。

        会话管理策略:
        1. 如果指定了restart参数，重新创建会话
        2. 如果会话不存在，自动创建新会话
        3. 执行提供的命令并返回结果

        参数:
            command: 要执行的bash命令，或None。
            restart: 是否重启会话。
            **kwargs: 其他参数（未使用）。

        返回:
            CLIResult: 包含命令执行结果的对象。

        异常:
            ToolError: 如果遇到会话管理相关的错误。
        """
        if restart or self._session is None:
            # 如果指定了重启或会话不存在，创建新会话
            if self._session:
                try:
                    self._session.stop()  # 尝试停止现有会话
                except Exception:
                    pass  # 忽略停止失败的错误
            self._session = _BashSession()
            await self._session.start()

        # 对特殊命令"ctrl+c"的处理
        if command == "ctrl+c":
            # 使用SIGINT中断当前进程
            try:
                import os
                import signal

                pgid = os.getpgid(self._session._process.pid)
                os.killpg(pgid, signal.SIGINT)
                return CLIResult(output="Sent SIGINT (Ctrl+C) to process.")
            except Exception as e:
                return CLIResult(
                    output="Failed to send interrupt", error=f"Error: {str(e)}"
                )

        # 处理空命令（可能用于获取更多输出）
        if not command:
            command = ""  # 确保命令是空字符串而非None

        try:
            # 执行命令并处理结果
            result = await self._session.run(command)
            return result
        except ToolError as e:
            # 如果出现会话错误，尝试重新启动会话并再次执行
            if "timed out" in str(e) or "must be restarted" in str(e):
                # 记录错误并重新初始化会话
                error_message = str(e)
                self._session = _BashSession()
                await self._session.start()

                if "timed out" in error_message:
                    return CLIResult(
                        error=f"Command timed out. Sending SIGINT to the process. Try running the command in the background."
                    )
                return CLIResult(
                    error=f"Session was restarted due to error: {error_message}"
                )
            raise  # 重新抛出其他类型的工具错误


# 自测代码，仅在直接运行文件时执行
if __name__ == "__main__":
    bash = Bash()
    rst = asyncio.run(bash.execute("ls -l"))  # 同步上下文中运行异步代码的方法
    print(rst)
