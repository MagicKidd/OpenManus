# 这是agent包的初始化文件（__init__.py）
# 当Python导入一个包时，它会首先执行这个文件
# 这个文件的主要作用是:
# 1. 从各个模块导入相关类，使它们可以通过包直接访问
# 2. 定义__all__列表，指定当使用"from package import *"语法时应该导入哪些名称

# 从基础智能体模块导入BaseAgent类
# BaseAgent是所有智能体的基类，提供了基本的智能体功能
from app.agent.base import BaseAgent

# 从浏览器智能体模块导入BrowserAgent类
# BrowserAgent专门用于控制浏览器执行各种任务
from app.agent.browser import BrowserAgent

# 从MCP智能体模块导入MCPAgent类
# MCPAgent可能是一种特殊用途的智能体，具体功能需查看其实现
from app.agent.mcp import MCPAgent

# 从ReAct智能体模块导入ReActAgent类
# ReActAgent实现了ReAct(Reasoning+Acting)模式，能够推理并采取行动
from app.agent.react import ReActAgent

# 从软件工程智能体模块导入SWEAgent类
# SWEAgent专门用于软件工程任务，如代码生成、重构等
from app.agent.swe import SWEAgent

# 从工具调用智能体模块导入ToolCallAgent类
# ToolCallAgent专门处理工具/函数调用的智能体
from app.agent.toolcall import ToolCallAgent

# __all__列表定义了当使用"from app.agent import *"时会导入哪些名称
# 这是Python的一种命名空间控制机制，可以避免导入不必要的名称
__all__ = [
    "BaseAgent",  # 基础智能体类
    "BrowserAgent",  # 浏览器控制智能体
    "ReActAgent",  # 推理与行动智能体
    "SWEAgent",  # 软件工程智能体
    "ToolCallAgent",  # 工具调用智能体
    "MCPAgent",  # MCP智能体
]

# 智能体继承结构:
# BaseAgent (基类)
# └── ReActAgent (实现推理和行动循环的中间层类)
#     ├── ToolCallAgent (增加工具调用能力的中间层类)
#     │   ├── BrowserAgent (特化为浏览器控制)
#     │   └── MCPAgent (特定功能的智能体)
#     └── SWEAgent (特化为软件工程任务)
