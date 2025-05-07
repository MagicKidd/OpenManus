from enum import Enum
from typing import Dict, List, Union

from app.agent.base import BaseAgent
from app.flow.base import BaseFlow
from app.flow.planning import PlanningFlow


class FlowType(str, Enum):
    """
    流程类型枚举

    这个类定义了系统支持的流程类型，使用Enum可以限制可选值，
    并提供更好的类型检查。继承自str是为了方便序列化和使用字符串方法。

    当前支持的流程类型:
    - PLANNING: 计划执行型流程，用于任务分解和顺序执行
    """

    PLANNING = "planning"  # 计划执行型流程


class FlowFactory:
    """
    流程工厂类

    这个类实现了工厂设计模式(Factory Pattern)，用于创建不同类型的流程实例。
    工厂模式的主要优点:
    1. 封装了对象创建的复杂逻辑
    2. 使客户端与具体实现类解耦
    3. 方便添加新的流程类型

    使用示例:
    ```python
    agent = SomeAgent()
    flow = FlowFactory.create_flow(FlowType.PLANNING, agent)
    result = await flow.execute("用户请求")
    ```
    """

    @staticmethod
    def create_flow(
        flow_type: FlowType,
        agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]],
        **kwargs,
    ) -> BaseFlow:
        """
        创建指定类型的流程实例

        这是一个静态方法(@staticmethod)，不需要实例化工厂类就可以直接调用

        参数:
            flow_type: 要创建的流程类型，必须是FlowType枚举中的值
            agents: 用于流程的智能体，可以是单个实例、列表或字典
            **kwargs: 额外的关键字参数，会传递给流程的构造函数

        返回值:
            创建好的流程实例，类型为BaseFlow的子类

        异常:
            ValueError: 当指定的流程类型不支持时抛出
        """
        # 支持的流程类型映射字典
        flows = {
            FlowType.PLANNING: PlanningFlow,  # 计划类型流程
        }

        # 查找对应的流程类
        flow_class = flows.get(flow_type)
        if not flow_class:
            # 如果未找到对应的流程类，抛出异常
            raise ValueError(f"Unknown flow type: {flow_type}")

        # 创建并返回流程实例
        return flow_class(agents, **kwargs)
