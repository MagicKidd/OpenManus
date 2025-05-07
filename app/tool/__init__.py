"""
工具包初始化模块 (Tool Package Initialization)

这个模块定义了智能体可用的工具集合，通过导入和导出各种工具类使它们可被全局访问。
工具是智能体与外部世界交互的关键组件，每个工具都实现了一种特定的能力。

教学点:
1. 包结构: Python包的组织和初始化
2. 模块导入: 从子模块导入类
3. 符号导出: 使用__all__控制包级导出
4. 工具集成: 将独立工具组织成统一接口
5. 模块化设计: 每个工具作为独立模块实现特定功能
"""

from app.tool.base import BaseTool
from app.tool.bash import Bash
from app.tool.browser_use_tool import BrowserUseTool
from app.tool.create_chat_completion import CreateChatCompletion
from app.tool.deep_research import DeepResearch
from app.tool.planning import PlanningTool
from app.tool.str_replace_editor import StrReplaceEditor
from app.tool.terminate import Terminate
from app.tool.tool_collection import ToolCollection
from app.tool.web_search import WebSearch

# __all__变量定义了从这个包中导出的公共符号
# 当其他模块执行"from app.tool import *"时，只有这些列出的类会被导入
# 这是一种控制包公共API的方式，遵循了"显式优于隐式"的Python哲学
__all__ = [
    "BaseTool",  # 工具基础抽象类，所有工具的父类
    "Bash",  # 命令行工具，执行系统命令
    "BrowserUseTool",  # 浏览器自动化工具，用于网页交互
    "DeepResearch",  # 深度研究工具，用于复杂问题分析
    "Terminate",  # 终止工具，用于结束进程或操作
    "StrReplaceEditor",  # 字符串替换工具，用于文本编辑
    "WebSearch",  # 网络搜索工具，用于获取在线信息
    "ToolCollection",  # 工具集合，组织和管理多个工具
    "CreateChatCompletion",  # 聊天完成工具，与语言模型交互
    "PlanningTool",  # 规划工具，创建和管理任务计划
]
