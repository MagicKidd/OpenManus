import json  # 导入处理JSON数据的标准库
from typing import (
    TYPE_CHECKING,
    Optional,
)  # 导入类型提示工具，TYPE_CHECKING用于避免循环导入

from pydantic import Field, model_validator  # 用于数据验证的Pydantic库工具

from app.agent.toolcall import ToolCallAgent  # 导入基础工具调用智能体类
from app.logger import logger  # 导入日志记录工具
from app.prompt.browser import (
    NEXT_STEP_PROMPT,
    SYSTEM_PROMPT,
)  # 导入预定义的浏览器提示模板
from app.schema import Message, ToolChoice  # 导入消息和工具选择模式的数据模型
from app.tool import Terminate  # 导入浏览器工具和其他基础工具
from app.tool import BrowserUseTool, ToolCollection

# 避免循环导入问题，仅在类型检查时导入BaseAgent
# TYPE_CHECKING是Python的特殊变量，只在类型检查阶段为True，运行时为False
if TYPE_CHECKING:
    from app.agent.base import BaseAgent  # Or wherever memory is defined


class BrowserContextHelper:
    """
    浏览器上下文助手类

    这个类负责处理浏览器状态并格式化浏览器相关提示。
    它帮助智能体了解当前浏览页面的状态，从而做出更好的决策。
    """

    def __init__(self, agent: "BaseAgent"):
        """
        初始化浏览器上下文助手

        参数:
            agent: 智能体实例，通常是BrowserAgent
        """
        self.agent = agent  # 保存对智能体的引用
        self._current_base64_image: Optional[str] = (
            None  # 存储当前浏览器截图的base64编码
        )

    async def get_browser_state(self) -> Optional[dict]:
        """
        获取当前浏览器状态

        这个异步方法使用BrowserUseTool从浏览器获取当前状态信息，
        包括URL、标题、可用标签等。

        返回值:
            包含浏览器状态的字典，如果获取失败则返回None
        """
        # 从可用工具中获取浏览器工具实例
        browser_tool = self.agent.available_tools.get_tool(BrowserUseTool().name)
        # 检查工具是否可用且有get_current_state方法
        if not browser_tool or not hasattr(browser_tool, "get_current_state"):
            logger.warning("BrowserUseTool not found or doesn't have get_current_state")
            return None
        try:
            # 调用浏览器工具获取当前状态
            result = await browser_tool.get_current_state()
            # 检查返回结果是否有错误
            if result.error:
                logger.debug(f"Browser state error: {result.error}")
                return None
            # 处理返回的base64图像（如果有）
            if hasattr(result, "base64_image") and result.base64_image:
                self._current_base64_image = result.base64_image
            else:
                self._current_base64_image = None
            # 解析并返回JSON格式的输出结果
            return json.loads(result.output)
        except Exception as e:
            # 异常处理：记录错误并返回None
            logger.debug(f"Failed to get browser state: {str(e)}")
            return None

    async def format_next_step_prompt(self) -> str:
        """
        格式化下一步提示词

        根据当前浏览器状态，生成包含浏览器信息的下一步提示词，
        帮助智能体理解当前上下文并决定下一步行动。

        返回值:
            格式化后的提示词字符串
        """
        # 获取浏览器状态
        browser_state = await self.get_browser_state()
        # 初始化提示词中使用的变量
        url_info, tabs_info, content_above_info, content_below_info = "", "", "", ""
        results_info = ""  # 或从智能体获取（如果需要在其他地方使用）

        # 如果成功获取浏览器状态且没有错误
        if browser_state and not browser_state.get("error"):
            # 提取URL和标题信息
            url_info = f"\n   URL: {browser_state.get('url', 'N/A')}\n   Title: {browser_state.get('title', 'N/A')}"
            # 提取标签信息
            tabs = browser_state.get("tabs", [])
            if tabs:
                tabs_info = f"\n   {len(tabs)} tab(s) available"
            # 提取页面滚动信息
            pixels_above = browser_state.get("pixels_above", 0)
            pixels_below = browser_state.get("pixels_below", 0)
            if pixels_above > 0:
                content_above_info = f" ({pixels_above} pixels)"
            if pixels_below > 0:
                content_below_info = f" ({pixels_below} pixels)"

            # 如果有浏览器截图，将其添加到消息中
            if self._current_base64_image:
                image_message = Message.user_message(
                    content="Current browser screenshot:",
                    base64_image=self._current_base64_image,
                )
                self.agent.memory.add_message(image_message)
                self._current_base64_image = None  # 使用后清除图像数据

        # 使用收集到的信息格式化提示词模板
        return NEXT_STEP_PROMPT.format(
            url_placeholder=url_info,
            tabs_placeholder=tabs_info,
            content_above_placeholder=content_above_info,
            content_below_placeholder=content_below_info,
            results_placeholder=results_info,
        )

    async def cleanup_browser(self):
        """
        清理浏览器资源

        在智能体完成任务后，确保关闭浏览器并释放相关资源，
        防止资源泄漏和不必要的进程残留。
        """
        # 获取浏览器工具实例
        browser_tool = self.agent.available_tools.get_tool(BrowserUseTool().name)
        # 如果浏览器工具存在且有清理方法，则调用它
        if browser_tool and hasattr(browser_tool, "cleanup"):
            await browser_tool.cleanup()


class BrowserAgent(ToolCallAgent):
    """
    浏览器智能体类

    这个智能体专门用于控制浏览器执行各种任务，包括网页导航、
    内容提取、表单填写以及与网页元素交互等功能。

    它继承自ToolCallAgent，增加了浏览器特定的功能和上下文处理。
    """

    # 类属性定义
    name: str = "browser"  # 智能体名称
    description: str = (
        "A browser agent that can control a browser to accomplish tasks"  # 智能体描述
    )

    # 浏览器特定的提示词模板
    system_prompt: str = SYSTEM_PROMPT  # 系统提示词
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示词

    # 执行限制
    max_observe: int = 10000  # 观察结果的最大长度，浏览器通常需要更大的观察结果
    max_steps: int = 20  # 最大执行步骤数

    # 配置可用工具，使用Field来初始化默认值
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(BrowserUseTool(), Terminate())
    )

    # 使用AUTO工具选择模式，允许同时使用工具和自由格式响应
    tool_choices: ToolChoice = ToolChoice.AUTO
    # 特殊工具名称列表
    special_tool_names: list[str] = Field(default_factory=lambda: [Terminate().name])

    # 浏览器上下文助手，初始为None，将在模型验证后初始化
    browser_context_helper: Optional[BrowserContextHelper] = None

    @model_validator(mode="after")
    def initialize_helper(self) -> "BrowserAgent":
        """
        模型验证后初始化助手

        这是一个Pydantic的模型验证器，会在模型实例化后自动调用，
        用于初始化浏览器上下文助手。

        返回值:
            初始化后的浏览器智能体实例
        """
        self.browser_context_helper = BrowserContextHelper(self)
        return self

    async def think(self) -> bool:
        """
        重写基础智能体的思考方法

        在思考过程中，首先获取当前浏览器状态并格式化提示词，
        然后调用父类的think方法进行实际思考过程。

        返回值:
            布尔值，表示是否应该继续执行
        """
        # 使用浏览器上下文助手获取并格式化下一步提示词
        self.next_step_prompt = (
            await self.browser_context_helper.format_next_step_prompt()
        )
        # 调用父类的think方法进行实际思考
        return await super().think()

    async def cleanup(self):
        """
        清理浏览器智能体资源

        这个方法会在智能体执行结束时调用，确保浏览器资源正确释放，
        防止资源泄漏和浏览器进程残留。
        """
        # 调用浏览器上下文助手的清理方法
        await self.browser_context_helper.cleanup_browser()
