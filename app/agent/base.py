from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from app.llm import LLM
from app.logger import logger
from app.sandbox.client import SANDBOX_CLIENT
from app.schema import ROLE_TYPE, AgentState, Memory, Message


class BaseAgent(BaseModel, ABC):
    """Abstract base class for managing agent state and execution.

    Provides foundational functionality for state transitions, memory management,
    and a step-based execution loop. Subclasses must implement the `step` method.
    """

    # ===== 基础设计：核心属性 =====
    # 这些属性定义了agent的基本身份和描述
    name: str = Field(
        ..., description="Unique name of the agent"
    )  # 必填字段，用于唯一标识agent
    description: Optional[str] = Field(
        None, description="Optional agent description"
    )  # 可选描述

    # ===== 基础设计：提示配置 =====
    # 这些提示决定了agent的行为方式和决策过程
    system_prompt: Optional[str] = Field(
        None,
        description="System-level instruction prompt",  # 系统级指令，用于设置agent的整体行为框架
    )
    next_step_prompt: Optional[str] = Field(
        None,
        description="Prompt for determining next action",  # 决定下一步行动的提示，用于引导agent的决策
    )

    # ===== 基础设计：依赖组件 =====
    # 这些组件提供了agent运行所需的核心功能
    llm: LLM = Field(
        default_factory=LLM, description="Language model instance"
    )  # 语言模型实例，用于智能决策
    memory: Memory = Field(
        default_factory=Memory, description="Agent's memory store"
    )  # 记忆存储，保存历史消息
    state: AgentState = Field(
        default=AgentState.IDLE,
        description="Current agent state",  # 当前状态，用于控制执行流程
    )

    # ===== 优化设计：执行控制 =====
    # 这些参数用于控制执行流程和防止无限循环
    max_steps: int = Field(
        default=10, description="Maximum steps before termination"
    )  # 最大步骤数，防止无限执行
    current_step: int = Field(
        default=0, description="Current step in execution"
    )  # 当前步骤计数

    # ===== 优化设计：防循环机制 =====
    duplicate_threshold: int = 2  # 重复阈值，用于检测并处理循环状态

    class Config:
        arbitrary_types_allowed = (
            True  # 允许使用任意类型（如LLM可能不是简单的Pydantic类型）
        )
        extra = "allow"  # 允许额外字段，增加子类实现的灵活性

    # ===== 优化设计：初始化验证 =====
    @model_validator(mode="after")
    def initialize_agent(self) -> "BaseAgent":
        """初始化agent并验证必要组件。

        确保LLM和Memory组件正确初始化，防止运行时错误。
        """
        if self.llm is None or not isinstance(self.llm, LLM):
            self.llm = LLM(
                config_name=self.name.lower()
            )  # 若未提供LLM或类型不正确，则创建默认实例
        if not isinstance(self.memory, Memory):
            self.memory = Memory()  # 确保memory为正确类型
        return self

    # ===== 优化设计：状态管理 =====
    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """状态转换的异步上下文管理器。

        提供安全的状态转换机制，确保异常时也能恢复状态，防止状态不一致。

        Args:
            new_state: 要转换到的新状态。

        Yields:
            None: 允许在新状态下执行操作。

        Raises:
            ValueError: 如果新状态无效。
        """
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state: {new_state}")  # 验证状态类型

        previous_state = self.state  # 记录先前状态
        self.state = new_state  # 转换到新状态
        try:
            yield  # 允许在新状态下执行代码
        except Exception as e:
            self.state = AgentState.ERROR  # 发生异常时转为错误状态
            raise e  # 重新抛出异常
        finally:
            self.state = previous_state  # 恢复到先前状态，确保状态一致性

    # ===== 基础设计：内存管理 =====
    def update_memory(
        self,
        role: ROLE_TYPE,  # type: ignore
        content: str,
        base64_image: Optional[str] = None,
        **kwargs,
    ) -> None:
        """添加消息到agent的记忆中。

        统一的记忆更新接口，支持不同角色的消息格式。

        Args:
            role: 消息发送者的角色（用户、系统、助手、工具）。
            content: 消息内容。
            base64_image: 可选的base64编码图像。
            **kwargs: 额外参数（例如，工具消息的tool_call_id）。

        Raises:
            ValueError: 如果角色不受支持。
        """
        # 角色到消息创建函数的映射
        message_map = {
            "user": Message.user_message,  # 用户消息
            "system": Message.system_message,  # 系统消息
            "assistant": Message.assistant_message,  # 助手消息
            "tool": lambda content, **kw: Message.tool_message(
                content, **kw
            ),  # 工具消息
        }

        if role not in message_map:
            raise ValueError(f"Unsupported message role: {role}")  # 验证角色有效性

        # 根据角色使用相应参数创建消息
        kwargs = {"base64_image": base64_image, **(kwargs if role == "tool" else {})}
        self.memory.add_message(message_map[role](content, **kwargs))  # 向记忆添加消息

    # ===== 基础设计：主执行循环 =====
    async def run(self, request: Optional[str] = None) -> str:
        """异步执行agent的主循环。

        Management整个执行流程，包括状态转换、步骤执行和资源清理。

        Args:
            request: 可选的初始用户请求。

        Returns:
            执行结果的摘要字符串。

        Raises:
            RuntimeError: 如果agent不在IDLE状态下启动。
        """
        if self.state != AgentState.IDLE:
            raise RuntimeError(
                f"Cannot run agent from state: {self.state}"
            )  # 确保从IDLE状态开始

        if request:
            self.update_memory("user", request)  # 如果提供了请求，将其添加到记忆中

        results: List[str] = []  # 存储执行结果
        async with self.state_context(
            AgentState.RUNNING
        ):  # 使用上下文管理器转换状态为RUNNING
            while (
                self.current_step < self.max_steps and self.state != AgentState.FINISHED
            ):  # 当步骤未达上限且状态未完成时循环
                self.current_step += 1  # 步骤计数递增
                logger.info(
                    f"Executing step {self.current_step}/{self.max_steps}"
                )  # 记录步骤信息
                step_result = await self.step()  # 执行单步（子类必须实现）

                # ===== 优化设计：循环检测 =====
                if self.is_stuck():  # 检查是否陷入循环
                    self.handle_stuck_state()  # 处理卡住状态

                results.append(
                    f"Step {self.current_step}: {step_result}"
                )  # 记录步骤结果

            if self.current_step >= self.max_steps:  # 检查是否达到最大步骤
                self.current_step = 0  # 重置步骤计数
                self.state = AgentState.IDLE  # 重置状态为IDLE
                results.append(
                    f"Terminated: Reached max steps ({self.max_steps})"
                )  # 记录终止信息
        await SANDBOX_CLIENT.cleanup()  # 清理沙盒资源
        return (
            "\n".join(results) if results else "No steps executed"
        )  # 返回执行结果摘要

    # ===== 基础设计：抽象步骤方法 =====
    @abstractmethod
    async def step(self) -> str:
        """执行agent工作流中的单个步骤。

        子类必须实现此方法来定义特定行为，这是策略模式的一部分。
        """
        pass  # 抽象方法，必须由子类实现

    # ===== 优化设计：卡住状态处理 =====
    def handle_stuck_state(self):
        """处理卡住状态，添加提示以改变策略。

        当检测到agent可能陷入循环时，通过修改提示来改变其行为。
        """
        stuck_prompt = "\
        Observed duplicate responses. Consider new strategies and avoid repeating ineffective paths already attempted."
        self.next_step_prompt = (
            f"{stuck_prompt}\n{self.next_step_prompt}"  # 在下一步提示前添加警告
        )
        logger.warning(
            f"Agent detected stuck state. Added prompt: {stuck_prompt}"
        )  # 记录警告

    # ===== 优化设计：循环检测 =====
    def is_stuck(self) -> bool:
        """通过检测重复内容判断agent是否陷入循环。

        分析近期消息，检测是否有重复回答，表明可能陷入循环思维。
        """
        if len(self.memory.messages) < 2:
            return False  # 消息不足以判断

        last_message = self.memory.messages[-1]  # 获取最后一条消息
        if not last_message.content:
            return False  # 内容为空，无法判断

        # 计算相同内容出现次数
        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == "assistant" and msg.content == last_message.content
        )

        return duplicate_count >= self.duplicate_threshold  # 超过阈值判定为卡住

    # ===== 基础设计：属性访问器 =====
    @property
    def messages(self) -> List[Message]:
        """获取agent记忆中的消息列表。

        提供对内部存储消息的便捷访问。
        """
        return self.memory.messages

    @messages.setter
    def messages(self, value: List[Message]):
        """设置agent记忆中的消息列表。

        允许直接替换整个消息历史。
        """
        self.memory.messages = value
