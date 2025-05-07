# app/flow/__init__.py
# 流程(Flow)包初始化文件

"""
流程(Flow)模块是智能体系统的高级抽象，用于协调多个智能体协同工作。

这个模块实现了不同的流程模式，使智能体可以按照特定方式组织起来，
共同解决复杂问题。相比单个智能体，流程提供了更强大、更灵活的
任务处理能力。

主要组件:
- BaseFlow: 所有流程的抽象基类，定义了流程接口
- FlowFactory: 使用工厂模式创建不同类型的流程实例
- PlanningFlow: 实现基于计划的任务执行流程

学习路径:
1. 从base.py了解流程的基本概念和接口
2. 学习flow_factory.py中的工厂模式应用
3. 深入研究planning.py中的计划流程实现

流程与智能体的关系:
流程(Flow)管理和协调多个智能体(Agent)，智能体是执行具体任务的实体。
这种设计遵循组合优于继承的原则，提高了系统的灵活性和可扩展性。
"""

# 导出主要的类，便于直接从包导入
from app.flow.base import BaseFlow
from app.flow.flow_factory import FlowFactory, FlowType
from app.flow.planning import PlanningFlow

__all__ = ["BaseFlow", "FlowFactory", "FlowType", "PlanningFlow"]
