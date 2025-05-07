"""
模型上下文协议客户端模块 (Model Context Protocol Client Module)

这个模块实现了MCP(Model Context Protocol)客户端功能，允许智能体与支持MCP协议的服务器
通信并动态发现和使用远程工具。MCP是一种标准化协议，用于AI系统之间的通信和工具调用。

教学点:
1. 协议集成: 与标准化协议(MCP)的交互实现
2. 远程工具代理: 使用代理模式访问远程功能
3. 网络通信: 使用不同传输方式(SSE/stdio)的客户端-服务器通信
4. 上下文管理: 使用AsyncExitStack管理多个异步资源
5. 动态工具发现: 运行时工具注册和管理
"""

from contextlib import AsyncExitStack
from typing import List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from app.logger import logger
from app.tool.base import BaseTool, ToolResult
from app.tool.tool_collection import ToolCollection


class MCPClientTool(BaseTool):
    """MCP客户端工具代理类。

    这个类代表一个可从客户端调用的远程MCP服务器工具。
    它使用代理模式将本地工具调用转发到远程MCP服务器。

    设计模式:
    1. 代理模式: 作为远程工具的本地代理
    2. 适配器模式: 将MCP响应适配为工具系统的ToolResult格式

    属性:
        session: 与MCP服务器的会话连接，用于发送请求。
    """

    session: Optional[ClientSession] = None

    async def execute(self, **kwargs) -> ToolResult:
        """执行MCP远程工具。

        这个方法实现了BaseTool的抽象execute方法，发送请求到MCP服务器执行远程工具，
        并将结果转换为标准的ToolResult格式。

        实现细节:
        1. 会话状态检查: 确保与服务器的连接已建立
        2. 远程调用: 通过session.call_tool发送请求
        3. 响应解析: 从复杂响应中提取文本内容
        4. 错误处理: 捕获并转换异常为错误结果

        参数:
            **kwargs: 传递给工具的参数字典。

        返回:
            包含远程工具执行结果或错误的ToolResult对象。
        """
        if not self.session:
            return ToolResult(error="Not connected to MCP server")

        try:
            # 调用远程工具并等待响应
            result = await self.session.call_tool(self.name, kwargs)

            # 从MCP响应中提取文本内容
            content_str = ", ".join(
                item.text for item in result.content if isinstance(item, TextContent)
            )
            return ToolResult(output=content_str or "No output returned.")
        except Exception as e:
            return ToolResult(error=f"Error executing tool: {str(e)}")


class MCPClients(ToolCollection):
    """MCP客户端工具集合类。

    这个类管理与MCP服务器的连接，发现和注册可用的远程工具，
    并将它们作为本地工具集合暴露给智能体。它展示了如何动态构建
    工具集合并管理复杂的网络连接生命周期。

    设计模式:
    1. 工厂模式: 动态创建远程工具的本地代理
    2. 门面模式: 为整个MCP交互提供简化的接口
    3. 策略模式: 支持多种连接方式(SSE/stdio)

    属性:
        session: 与MCP服务器的会话连接。
        exit_stack: 异步资源管理器，用于清理多个上下文。
        description: 工具集合的描述文本。
    """

    session: Optional[ClientSession] = None
    exit_stack: AsyncExitStack = None
    description: str = "MCP client tools for server interaction"

    def __init__(self):
        """初始化MCP客户端工具集合。

        创建一个新的工具集合，初始化状态但不立即连接服务器。
        这遵循惰性初始化原则，按需建立连接。
        """
        super().__init__()  # 使用空工具列表初始化
        self.name = "mcp"  # 保持向后兼容性
        self.exit_stack = AsyncExitStack()  # 用于管理多个异步上下文

    async def connect_sse(self, server_url: str) -> None:
        """使用SSE传输方式连接到MCP服务器。

        这个方法使用Server-Sent Events(SSE)协议连接到MCP服务器。
        SSE是一种HTTP长连接，适用于服务器向客户端持续推送数据的场景。

        资源管理策略:
        1. 使用AsyncExitStack管理多个异步上下文资源
        2. 确保之前的连接被正确关闭
        3. 在成功连接后自动初始化和获取工具列表

        参数:
            server_url: MCP服务器的URL。

        异常:
            ValueError: 如果未提供服务器URL。
        """
        if not server_url:
            raise ValueError("Server URL is required.")
        if self.session:
            await self.disconnect()  # 断开现有连接

        # 建立SSE连接并存入上下文栈中
        streams_context = sse_client(url=server_url)
        streams = await self.exit_stack.enter_async_context(streams_context)

        # 创建客户端会话并存入上下文栈中
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(*streams)
        )

        # 初始化并获取工具列表
        await self._initialize_and_list_tools()

    async def connect_stdio(self, command: str, args: List[str]) -> None:
        """使用stdio传输方式连接到MCP服务器。

        这个方法通过标准输入输出流连接到MCP服务器，适用于通过命令行
        启动的本地服务器进程。它展示了如何使用进程间通信作为工具通信渠道。

        进程连接流程:
        1. 创建服务器进程参数描述
        2. 建立stdio通道
        3. 使用读写流创建客户端会话
        4. 初始化并发现可用工具

        参数:
            command: 要执行的服务器命令。
            args: 命令行参数列表。

        异常:
            ValueError: 如果未提供服务器命令。
        """
        if not command:
            raise ValueError("Server command is required.")
        if self.session:
            await self.disconnect()  # 断开现有连接

        # 创建服务器进程参数
        server_params = StdioServerParameters(command=command, args=args)

        # 建立stdio连接并获取读写流
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read, write = stdio_transport

        # 创建客户端会话
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(read, write)
        )

        # 初始化并获取工具列表
        await self._initialize_and_list_tools()

    async def _initialize_and_list_tools(self) -> None:
        """初始化会话并填充工具映射。

        这个私有方法处理MCP会话初始化、工具发现和本地工具代理创建过程。
        它展示了如何动态构建基于远程发现的工具集合。

        实现步骤:
        1. 初始化MCP会话
        2. 请求可用工具列表
        3. 清除现有工具
        4. 为每个远程工具创建本地代理
        5. 更新工具集合和映射

        异常:
            RuntimeError: 如果会话未初始化。
        """
        if not self.session:
            raise RuntimeError("Session not initialized.")

        # 初始化会话
        await self.session.initialize()

        # 获取工具列表
        response = await self.session.list_tools()

        # 清除现有工具
        self.tools = tuple()
        self.tool_map = {}

        # 为每个服务器工具创建代理对象
        for tool in response.tools:
            server_tool = MCPClientTool(
                name=tool.name,
                description=tool.description,
                parameters=tool.inputSchema,
                session=self.session,
            )
            self.tool_map[tool.name] = server_tool

        # 更新工具元组
        self.tools = tuple(self.tool_map.values())
        logger.info(
            f"Connected to server with tools: {[tool.name for tool in response.tools]}"
        )

    async def disconnect(self) -> None:
        """断开与MCP服务器的连接并清理资源。

        这个方法负责正确地关闭连接和清理资源，展示了
        资源生命周期管理的最佳实践。

        清理流程:
        1. 关闭所有异步上下文（通过exit_stack）
        2. 重置会话状态
        3. 清空工具集合和映射
        4. 记录断开连接事件
        """
        if self.session and self.exit_stack:
            # 关闭所有异步上下文
            await self.exit_stack.aclose()

            # 重置状态
            self.session = None
            self.tools = tuple()
            self.tool_map = {}

            logger.info("Disconnected from MCP server")
