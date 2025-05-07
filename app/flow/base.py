from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union

from pydantic import BaseModel

from app.agent.base import BaseAgent


class BaseFlow(BaseModel, ABC):
    """
    流程(Flow)基类：用于支持多智能体协作执行任务的框架

    流程(Flow)是一种高级抽象，它协调多个智能体(Agent)一起工作，
    按照特定规则或顺序完成复杂任务。这种设计模式让我们可以组合
    不同专长的智能体，实现更强大的功能。

    这个类同时继承自两个基类：
    - BaseModel：来自Pydantic，提供数据验证和模型定义功能
    - ABC：抽象基类，用于定义接口
    """

    agents: Dict[str, BaseAgent]
    tools: Optional[List] = None
    primary_agent_key: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(
        self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], **data
    ):
        """
        初始化流程实例

        这个构造函数很灵活，支持三种不同方式提供智能体：
        1. 单个智能体实例
        2. 智能体列表
        3. 已命名的智能体字典

        参数:
            agents: 智能体实例、列表或字典
            **data: 其他关键字参数，用于设置流程属性
        """
        # Handle different ways of providing agents
        if isinstance(agents, BaseAgent):
            agents_dict = {"default": agents}
        elif isinstance(agents, list):
            agents_dict = {f"agent_{i}": agent for i, agent in enumerate(agents)}
        else:
            agents_dict = agents

        # If primary agent not specified, use first agent
        primary_key = data.get("primary_agent_key")
        if not primary_key and agents_dict:
            primary_key = next(iter(agents_dict))
            data["primary_agent_key"] = primary_key

        # Set the agents dictionary
        data["agents"] = agents_dict

        # Initialize using BaseModel's init
        super().__init__(**data)

    @property
    def primary_agent(self) -> Optional[BaseAgent]:
        """
        获取流程的主智能体

        使用@property装饰器可以让这个方法像属性一样被访问，
        例如：flow.primary_agent 而不是 flow.primary_agent()

        返回值:
            主智能体实例，如果未设置则返回None
        """
        return self.agents.get(self.primary_agent_key)

    def get_agent(self, key: str) -> Optional[BaseAgent]:
        """
        通过键获取特定的智能体

        参数:
            key: 智能体的键名
        返回值:
            指定的智能体实例，如果不存在则返回None
        """
        return self.agents.get(key)

    def add_agent(self, key: str, agent: BaseAgent) -> None:
        """
        向流程中添加新的智能体

        参数:
            key: 新智能体的键名
            agent: 要添加的智能体实例
        """
        self.agents[key] = agent

    @abstractmethod
    async def execute(self, input_text: str) -> str:
        """
        执行流程的抽象方法

        这是一个抽象方法（使用@abstractmethod装饰器），表示子类必须实现此方法。
        它定义了流程执行的接口，接收输入文本并返回结果。

        参数:
            input_text: 用户输入或任务描述
        返回值:
            执行结果的文本表示

        注意: 使用async关键字表示这是一个异步方法，允许在等待I/O操作时执行其他任务
        """
        # 具体实现由子类提供
        pass
