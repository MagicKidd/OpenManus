from typing import Optional

from pydantic import Field, model_validator

from app.agent.browser import BrowserContextHelper
from app.agent.toolcall import ToolCallAgent
from app.config import config
from app.prompt.manus import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.tool import Terminate, ToolCollection
from app.tool.browser_use_tool import BrowserUseTool
from app.tool.python_execute import PythonExecute
from app.tool.str_replace_editor import StrReplaceEditor


class Manus(ToolCallAgent):
    """A versatile general-purpose agent."""

    # ===== 基本属性定义 - Agent身份 =====
    name: str = "Manus"
    description: str = (
        "A versatile agent that can solve various tasks using multiple tools"
    )

    # ===== 基本属性定义 - 提示模板 =====
    system_prompt: str = SYSTEM_PROMPT.format(directory=config.workspace_root)
    next_step_prompt: str = NEXT_STEP_PROMPT

    # ===== 基本配置 - 执行限制 =====
    max_observe: int = 10000
    max_steps: int = 20

    # ===== 核心功能部分 - 工具集合 =====
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            PythonExecute(), BrowserUseTool(), StrReplaceEditor(), Terminate()
        )
    )

    # ===== 优化部分 - 特殊工具处理 =====
    special_tool_names: list[str] = Field(default_factory=lambda: [Terminate().name])

    # ===== 优化部分 - 浏览器上下文助手 =====
    browser_context_helper: Optional[BrowserContextHelper] = None

    @model_validator(mode="after")
    def initialize_helper(self) -> "Manus":
        """初始化浏览器上下文助手。

        这是一个模型验证方法，会在Manus实例创建后自动调用。
        它创建一个BrowserContextHelper实例，并将当前Agent传递给它，
        使助手能够访问Agent的状态和记忆。

        Returns:
            当前Manus实例，支持链式调用
        """
        self.browser_context_helper = BrowserContextHelper(self)
        return self

    async def think(self) -> bool:
        """处理当前状态并决定下一步操作，提供适当的上下文。

        这个方法重写了ToolCallAgent的think方法，添加了上下文感知功能：
        1. 保存原始提示
        2. 检查是否正在使用浏览器
        3. 如果是，提供浏览器特定的上下文
        4. 调用父类think方法进行决策
        5. 恢复原始提示

        这种设计使Agent能够根据当前使用的工具动态调整提示，
        提供更相关的上下文信息。

        Returns:
            布尔值，表示是否应该继续执行
        """
        # 保存原始提示，以便后续恢复
        original_prompt = self.next_step_prompt

        # 获取最近的三条消息，用于检测是否在使用浏览器
        recent_messages = self.memory.messages[-3:] if self.memory.messages else []

        # 检查最近的消息中是否有浏览器工具调用
        # 这是一个优化点：根据当前上下文动态调整行为
        browser_in_use = any(
            tc.function.name == BrowserUseTool().name
            for msg in recent_messages
            if msg.tool_calls
            for tc in msg.tool_calls
        )

        # 如果正在使用浏览器，获取特定于浏览器的上下文提示
        if browser_in_use:
            self.next_step_prompt = (
                await self.browser_context_helper.format_next_step_prompt()
            )

        # 调用父类的think方法，使用新的提示
        result = await super().think()

        # 恢复原始提示，不影响后续步骤
        self.next_step_prompt = original_prompt

        return result

    async def cleanup(self):
        """清理Manus Agent资源。

        确保在Agent执行完成后释放资源，
        特别是关闭任何打开的浏览器实例。
        这是资源管理的最佳实践，避免资源泄漏。
        """
        # 如果浏览器上下文助手存在，清理浏览器资源
        if self.browser_context_helper:
            await self.browser_context_helper.cleanup_browser()
