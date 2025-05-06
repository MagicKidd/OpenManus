from abc import ABC, abstractmethod  # 使用抽象基类确保ReAct的核心方法被实现
from typing import Optional

from pydantic import Field  # 使用Pydantic进行数据验证，确保ReAct代理状态的一致性

from app.agent.base import BaseAgent  # 继承基础代理类，ReAct是一种特殊的代理实现模式
from app.llm import LLM  # 语言模型用于ReAct的推理过程，是"思考"能力的来源
from app.schema import (
    AgentState,
    Memory,
)  # 状态和记忆是ReAct循环的关键组件，记录思考-行动历史


class ReActAgent(BaseAgent, ABC):
    """
    ReAct (Reasoning + Acting) 代理实现

    ReAct原理：
    1. Reasoning (推理)：分析当前状态并决定下一步行动
    2. Acting (行动)：执行推理后决定的动作
    3. 观察反馈并迭代这个过程

    这种方法结合了语言模型的推理能力和与环境交互的能力，使代理能够更有效地完成复杂任务。
    """

    name: str  # 代理标识符，便于追踪ReAct代理的行为和日志分析
    description: Optional[str] = None  # 代理描述，有助于定义ReAct代理的领域和能力范围

    system_prompt: Optional[str] = None  # 系统级提示词设定ReAct的整体行为框架和思考模式
    next_step_prompt: Optional[str] = (
        None  # 用于引导下一步推理的提示词，辅助ReAct的思考过程
    )

    llm: Optional[LLM] = Field(
        default_factory=LLM
    )  # 语言模型是ReAct的"大脑"，负责推理部分
    memory: Memory = Field(
        default_factory=Memory
    )  # 记忆组件存储历史推理和行动，是ReAct迭代改进的基础
    state: AgentState = AgentState.IDLE  # 代理状态跟踪ReAct循环的当前阶段，控制工作流

    max_steps: int = 10  # 防止无限循环，限制最大迭代次数，确保ReAct的可控性
    current_step: int = 0  # 追踪当前执行到第几轮ReAct循环，监控进度

    @abstractmethod
    async def think(self) -> bool:
        """
        Process current state and decide next action

        实现ReAct的Reasoning(推理)阶段：
        - 分析当前环境和历史记忆
        - 推理出下一步最佳行动
        - 返回是否需要执行行动
        """

    @abstractmethod
    async def act(self) -> str:
        """
        Execute decided actions

        实现ReAct的Acting(行动)阶段：
        - 执行推理阶段决定的动作
        - 与环境交互并获取反馈
        - 返回执行结果，为下一轮推理做准备
        """

    async def step(self) -> str:
        """
        Execute a single step: think and act.

        整合ReAct的完整循环：
        1. 调用think()方法进行推理
        2. 根据推理结果决定是否执行行动
        3. 如需行动，调用act()方法
        4. 返回结果，为下一个ReAct循环做准备

        这个方法实现了ReAct的核心循环机制，每次调用代表一个完整的思考-行动周期。
        """
        should_act = await self.think()  # ReAct的推理阶段，决定是否需要执行行动
        if not should_act:
            return "Thinking complete - no action needed"  # 如果推理结果是不需要行动，则完成当前循环
        return await self.act()  # ReAct的行动阶段，执行推理决定的行动并返回结果
