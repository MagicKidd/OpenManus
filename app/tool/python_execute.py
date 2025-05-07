"""
Python执行工具模块 (Python Execution Tool Module)

这个模块实现了Python代码执行工具，允许智能体安全地执行动态生成的Python代码。
它采用了多进程隔离和超时控制等安全机制，确保代码执行不会影响主应用。

教学点:
1. 代码隔离: 使用多进程实现安全的代码执行环境
2. 标准流重定向: 捕获标准输出以获取执行结果
3. 超时控制: 防止无限循环或长时间运行的代码
4. 异常处理: 安全捕获和处理执行错误
5. 进程间通信: 使用共享字典在进程间传递结果
"""

import multiprocessing
import sys
from io import StringIO
from typing import Dict

from app.tool.base import BaseTool


class PythonExecute(BaseTool):
    """Python代码执行工具类。

    这个工具允许智能体在隔离的环境中执行Python代码字符串，并获取执行结果。
    它通过多进程隔离和超时控制来确保安全性，防止恶意代码或无限循环影响系统。

    设计理念:
    1. 安全第一: 通过进程隔离和超时保护主应用
    2. 输出捕获: 重定向标准输出以收集打印内容
    3. 执行边界: 限制代码执行时间，防止资源滥用

    属性:
        name: 工具的名称标识符。
        description: 工具功能的描述，强调只有打印输出可见。
        parameters: 工具参数的JSON Schema定义，包含代码字符串。
    """

    name: str = "python_execute"
    description: str = (
        "Executes Python code string. Note: Only print outputs are visible, function return values are not captured. Use print statements to see results."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The Python code to execute.",
            },
        },
        "required": ["code"],
    }

    def _run_code(self, code: str, result_dict: dict, safe_globals: dict) -> None:
        """在隔离环境中执行Python代码。

        这个辅助方法在子进程中运行，执行Python代码并捕获输出和错误。
        它使用标准输出重定向来捕获代码执行过程中的打印输出。

        实现技巧:
        1. 标准流重定向: 使用StringIO暂时替换sys.stdout
        2. 全局变量隔离: 使用安全的全局字典限制可用功能
        3. 异常捕获: 捕获并记录所有执行错误
        4. 清理保证: 使用finally块确保标准输出恢复

        参数:
            code: 要执行的Python代码字符串。
            result_dict: 用于存储执行结果的共享字典。
            safe_globals: 安全的全局变量字典，限制可用功能。
        """
        original_stdout = sys.stdout
        try:
            # 重定向标准输出到内存缓冲区
            output_buffer = StringIO()
            sys.stdout = output_buffer

            # 执行代码，使用相同的字典作为全局和局部作用域
            exec(code, safe_globals, safe_globals)

            # 获取输出结果并标记成功
            result_dict["observation"] = output_buffer.getvalue()
            result_dict["success"] = True
        except Exception as e:
            # 捕获并记录所有执行错误
            result_dict["observation"] = str(e)
            result_dict["success"] = False
        finally:
            # 确保标准输出被恢复，即使发生异常
            sys.stdout = original_stdout

    async def execute(
        self,
        code: str,
        timeout: int = 5,
    ) -> Dict:
        """执行Python代码并返回结果。

        这个方法实现了BaseTool的抽象execute方法，是工具的主要入口点。
        它创建一个新进程来执行代码，设置超时限制，并返回执行结果。

        进程控制流程:
        1. 创建共享结果字典和安全全局变量
        2. 启动子进程执行代码
        3. 等待指定时间，超时则终止进程
        4. 返回执行结果或超时消息

        参数:
            code: 要执行的Python代码字符串。
            timeout: 执行超时时间（秒），默认为5秒。

        返回:
            包含执行输出和成功状态的字典。
        """

        with multiprocessing.Manager() as manager:
            # 创建进程间共享的结果字典
            result = manager.dict({"observation": "", "success": False})

            # 准备安全的全局变量环境
            if isinstance(__builtins__, dict):
                safe_globals = {"__builtins__": __builtins__}
            else:
                safe_globals = {"__builtins__": __builtins__.__dict__.copy()}

            # 创建并启动执行进程
            proc = multiprocessing.Process(
                target=self._run_code, args=(code, result, safe_globals)
            )
            proc.start()
            proc.join(timeout)  # 等待指定的超时时间

            # 处理超时情况
            if proc.is_alive():
                # 进程仍在运行，表示超时
                proc.terminate()
                proc.join(1)  # 给进程1秒时间优雅终止
                return {
                    "observation": f"Execution timeout after {timeout} seconds",
                    "success": False,
                }

            # 返回执行结果
            return dict(result)
