#!/usr/bin/env python
# 指定解释器路径，使脚本可以作为可执行文件直接运行

import argparse  # 用于解析命令行参数
import asyncio  # 提供异步编程支持
import sys  # 访问Python解释器变量和函数

# 导入自定义的MCPAgent类和配置
from app.agent.mcp import MCPAgent
from app.config import config  # 从配置模块导入全局配置
from app.logger import logger  # 导入日志记录器


class MCPRunner:
    """Runner class for MCP Agent with proper path handling and configuration."""

    # 【基本结构】Runner负责MCP Agent的生命周期管理，是代理模式的应用

    def __init__(self):
        # 初始化时从全局配置获取必要的路径信息
        self.root_path = config.root_path  # 项目根路径
        self.server_reference = config.mcp_config.server_reference  # MCP服务器引用
        self.agent = MCPAgent()  # 创建MCPAgent实例但不初始化连接

    async def initialize(
        self,
        connection_type: str,
        server_url: str | None = None,
    ) -> None:
        """Initialize the MCP agent with the appropriate connection."""
        # 【核心方法】根据指定的连接类型初始化agent
        logger.info(f"Initializing MCPAgent with {connection_type} connection...")

        if connection_type == "stdio":
            # stdio模式：直接启动Python模块作为服务器，通过标准输入输出通信
            # 这种模式适合本地开发和测试
            await self.agent.initialize(
                connection_type="stdio",
                command=sys.executable,  # 使用当前Python解释器
                args=["-m", self.server_reference],  # 作为模块运行服务器
            )
        else:  # sse
            # SSE(Server-Sent Events)模式：连接到现有的服务器
            # 这种模式适合生产环境和远程连接
            await self.agent.initialize(connection_type="sse", server_url=server_url)

        logger.info(f"Connected to MCP server via {connection_type}")

    async def run_interactive(self) -> None:
        """Run the agent in interactive mode."""
        # 【优化部分】交互式模式，支持连续对话
        print("\nMCP Agent Interactive Mode (type 'exit' to quit)\n")
        while True:
            user_input = input("\nEnter your request: ")  # 从命令行获取用户输入
            if user_input.lower() in ["exit", "quit", "q"]:
                break  # 用户输入退出命令时结束循环
            response = await self.agent.run(user_input)  # 异步运行agent处理请求
            print(f"\nAgent: {response}")  # 打印agent的响应

    async def run_single_prompt(self, prompt: str) -> None:
        """Run the agent with a single prompt."""
        # 【基本结构】单次提示模式，执行一次请求后退出
        await self.agent.run(prompt)  # 异步运行agent处理单个请求

    async def run_default(self) -> None:
        """Run the agent in default mode."""
        # 【基本结构】默认模式，从命令行获取一次输入后处理
        prompt = input("Enter your prompt: ")
        if not prompt.strip():
            logger.warning("Empty prompt provided.")
            return  # 输入为空时直接返回

        logger.warning("Processing your request...")
        await self.agent.run(prompt)  # 异步运行agent处理请求
        logger.info("Request processing completed.")

    async def cleanup(self) -> None:
        """Clean up agent resources."""
        # 【优化部分】资源清理，确保agent正确关闭
        await self.agent.cleanup()  # 调用agent的清理方法
        logger.info("Session ended")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    # 【基本结构】命令行参数解析，提供灵活的运行选项
    parser = argparse.ArgumentParser(description="Run the MCP Agent")
    parser.add_argument(
        "--connection",
        "-c",
        choices=["stdio", "sse"],
        default="stdio",
        help="Connection type: stdio or sse",
    )
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:8000/sse",
        help="URL for SSE connection",
    )
    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Run in interactive mode"
    )
    parser.add_argument("--prompt", "-p", help="Single prompt to execute and exit")
    return parser.parse_args()


async def run_mcp() -> None:
    """Main entry point for the MCP runner."""
    # 【核心方法】主入口函数，协调整个执行流程
    args = parse_args()  # 解析命令行参数
    runner = MCPRunner()  # 创建MCPRunner实例

    try:
        # 初始化runner
        await runner.initialize(args.connection, args.server_url)

        # 根据不同的命令行参数选择运行模式
        if args.prompt:
            # 单次提示模式
            await runner.run_single_prompt(args.prompt)
        elif args.interactive:
            # 交互式模式
            await runner.run_interactive()
        else:
            # 默认模式
            await runner.run_default()

    except KeyboardInterrupt:
        # 处理用户中断（Ctrl+C）
        logger.info("Program interrupted by user")
    except Exception as e:
        # 处理所有其他异常
        logger.error(f"Error running MCPAgent: {str(e)}", exc_info=True)
        sys.exit(1)  # 异常退出，返回错误码1
    finally:
        # 无论如何都会执行清理
        await runner.cleanup()  # 确保资源被正确释放


if __name__ == "__main__":
    # 当文件作为脚本直接运行时执行
    asyncio.run(run_mcp())  # 使用asyncio.run运行主异步函数
