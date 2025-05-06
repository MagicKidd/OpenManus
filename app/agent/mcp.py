from typing import Any, Dict, List, Optional, Tuple

from pydantic import Field

from app.agent.toolcall import ToolCallAgent
from app.logger import logger
from app.prompt.mcp import MULTIMEDIA_RESPONSE_PROMPT, NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.schema import AgentState, Message
from app.tool.base import ToolResult
from app.tool.mcp import MCPClients


class MCPAgent(ToolCallAgent):
    """Agent for interacting with MCP (Model Context Protocol) servers.

    This agent connects to an MCP server using either SSE or stdio transport
    and makes the server's tools available through the agent's tool interface.
    """

    # === 基本属性定义 - Agent身份与描述 ===
    name: str = "mcp_agent"  # Agent名称，用于标识和日志记录
    description: str = (
        "An agent that connects to an MCP server and uses its tools."  # Agent功能描述
    )

    # === 基本属性定义 - 提示模板 ===
    system_prompt: str = SYSTEM_PROMPT  # 系统提示，定义Agent角色和行为
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示，引导决策过程

    # === 核心功能部分 - MCP集成 ===
    # MCPClients封装了与MCP服务器的通信细节
    mcp_clients: MCPClients = Field(default_factory=MCPClients)  # 创建MCP客户端实例
    available_tools: MCPClients = None  # 将在initialize方法中设置，指向mcp_clients

    # === 基本配置部分 ===
    max_steps: int = 20  # 最大执行步数，防止无限循环
    connection_type: str = "stdio"  # 连接类型，默认为stdio（标准输入/输出）

    # === 优化部分 - 工具管理 ===
    # 跟踪工具架构以检测变化，允许动态更新可用工具
    tool_schemas: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict
    )  # 存储工具架构
    _refresh_tools_interval: int = 5  # 每N步刷新一次工具列表

    # === 优化部分 - 特殊工具处理 ===
    # 定义特殊工具名称，这些工具会触发终止
    special_tool_names: List[str] = Field(
        default_factory=lambda: ["terminate"]
    )  # 使用lambda避免可变默认值问题

    async def initialize(
        self,
        connection_type: Optional[str] = None,
        server_url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
    ) -> None:
        """初始化MCP连接。

        这个方法负责建立与MCP服务器的连接，并获取可用工具。
        支持两种连接方式：SSE（服务器发送事件）和stdio（标准输入/输出）。

        Args:
            connection_type: 连接类型 ("stdio" 或 "sse")
            server_url: MCP服务器URL（SSE连接需要）
            command: 要运行的命令（stdio连接需要）
            args: 命令参数（stdio连接使用）
        """
        # 如果提供了连接类型，则更新实例的连接类型
        if connection_type:
            self.connection_type = connection_type

        # 根据连接类型选择不同的连接方法
        if self.connection_type == "sse":
            # SSE连接需要服务器URL
            if not server_url:
                raise ValueError("Server URL is required for SSE connection")
            await self.mcp_clients.connect_sse(server_url=server_url)
        elif self.connection_type == "stdio":
            # stdio连接需要命令
            if not command:
                raise ValueError("Command is required for stdio connection")
            await self.mcp_clients.connect_stdio(command=command, args=args or [])
        else:
            # 不支持的连接类型
            raise ValueError(f"Unsupported connection type: {self.connection_type}")

        # 设置available_tools为我们的MCP实例
        # 这使得ToolCallAgent基类可以访问MCP服务器提供的工具
        self.available_tools = self.mcp_clients

        # 获取并存储初始工具架构
        await self._refresh_tools()

        # 添加关于可用工具的系统消息
        # 这使LLM知道有哪些工具可用
        tool_names = list(self.mcp_clients.tool_map.keys())
        tools_info = ", ".join(tool_names)

        # 将系统提示和可用工具信息添加到Agent记忆中
        self.memory.add_message(
            Message.system_message(
                f"{self.system_prompt}\n\nAvailable MCP tools: {tools_info}"
            )
        )

    async def _refresh_tools(self) -> Tuple[List[str], List[str]]:
        """刷新MCP服务器提供的可用工具列表。

        这是一个优化功能，它允许Agent检测工具列表的变化，
        并在工具添加或移除时更新Agent的记忆，使LLM能够适应变化。

        Returns:
            包含(added_tools, removed_tools)的元组
        """
        # 检查会话是否存在
        if not self.mcp_clients.session:
            return [], []

        # 直接从服务器获取当前工具架构
        response = await self.mcp_clients.session.list_tools()
        current_tools = {tool.name: tool.inputSchema for tool in response.tools}

        # 确定添加、删除和更改的工具
        current_names = set(current_tools.keys())
        previous_names = set(self.tool_schemas.keys())

        # 计算新增和移除的工具
        added_tools = list(current_names - previous_names)
        removed_tools = list(previous_names - current_names)

        # 检查现有工具的架构变化
        changed_tools = []
        for name in current_names.intersection(previous_names):
            if current_tools[name] != self.tool_schemas.get(name):
                changed_tools.append(name)

        # 更新存储的架构
        self.tool_schemas = current_tools

        # 记录并通知变化
        # 这些通知会添加到Agent的记忆中，使LLM知道可用工具的变化
        if added_tools:
            logger.info(f"Added MCP tools: {added_tools}")
            self.memory.add_message(
                Message.system_message(f"New tools available: {', '.join(added_tools)}")
            )
        if removed_tools:
            logger.info(f"Removed MCP tools: {removed_tools}")
            self.memory.add_message(
                Message.system_message(
                    f"Tools no longer available: {', '.join(removed_tools)}"
                )
            )
        if changed_tools:
            logger.info(f"Changed MCP tools: {changed_tools}")

        return added_tools, removed_tools

    async def think(self) -> bool:
        """处理当前状态并决定下一步操作。

        这个方法重写了ToolCallAgent的think方法，添加了额外的逻辑：
        1. 检查MCP会话和工具可用性
        2. 定期刷新工具列表
        3. 如果所有工具都被移除，则终止交互

        Returns:
            布尔值，表示是否需要执行下一步
        """
        # === 优化部分：会话有效性检查 ===
        # 检查MCP会话和工具可用性
        if not self.mcp_clients.session or not self.mcp_clients.tool_map:
            logger.info("MCP service is no longer available, ending interaction")
            self.state = AgentState.FINISHED  # 设置状态为已完成
            return False  # 中止执行

        # === 优化部分：工具动态刷新 ===
        # 定期刷新工具
        if self.current_step % self._refresh_tools_interval == 0:
            await self._refresh_tools()
            # 如果所有工具都被移除，表示关闭
            if not self.mcp_clients.tool_map:
                logger.info("MCP service has shut down, ending interaction")
                self.state = AgentState.FINISHED
                return False

        # 使用父类的think方法
        # 这是ReAct框架的"思考"阶段
        return await super().think()

    async def _handle_special_tool(self, name: str, result: Any, **kwargs) -> None:
        """处理特殊工具执行和状态变化

        这个方法扩展了父类的特殊工具处理，添加了多媒体响应处理。
        当工具返回包含图像的结果时，会添加特殊提示消息。

        Args:
            name: 工具名称
            result: 工具执行结果
            **kwargs: 额外参数
        """
        # 首先用父类处理器处理
        await super()._handle_special_tool(name, result, **kwargs)

        # === 优化部分：多媒体响应处理 ===
        # 处理多媒体响应
        # 当工具返回base64编码的图像时，添加说明消息，帮助LLM理解结果
        if isinstance(result, ToolResult) and result.base64_image:
            self.memory.add_message(
                Message.system_message(
                    MULTIMEDIA_RESPONSE_PROMPT.format(tool_name=name)
                )
            )

    def _should_finish_execution(self, name: str, **kwargs) -> bool:
        """确定工具执行是否应该结束Agent

        这个方法实现了ToolCallAgent中的抽象方法，
        定义了哪些工具会导致Agent终止执行。

        Args:
            name: 工具名称
            **kwargs: 额外参数

        Returns:
            如果应该终止执行，则为True
        """
        # 如果工具名称是"terminate"，则终止
        return name.lower() == "terminate"

    async def cleanup(self) -> None:
        """清理MCP连接。

        在完成时关闭MCP连接，确保资源被正确释放。
        """
        # 关闭MCP连接
        if self.mcp_clients.session:
            await self.mcp_clients.disconnect()
            logger.info("MCP connection closed")

    async def run(self, request: Optional[str] = None) -> str:
        """运行Agent并在完成时清理。

        这个方法重写了BaseAgent的run方法，添加了异常处理和清理逻辑。
        使用try-finally确保即使出现错误，MCP连接也会被关闭。

        Args:
            request: 可选的初始用户请求

        Returns:
            执行结果字符串
        """
        try:
            # 调用父类的run方法执行主要逻辑
            result = await super().run(request)
            return result
        finally:
            # 确保即使出错也会进行清理
            await self.cleanup()
