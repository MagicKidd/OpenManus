"""
搜索引擎包初始化模块 (Search Engine Package Initialization)

这个模块是搜索引擎包的入口点，它导入并重新导出所有可用的搜索引擎实现，
使它们可以通过统一的命名空间访问。这种设计允许用户以一致的方式导入任何搜索引擎。

教学点:
1. 包结构设计: 使用__init__.py组织模块结构
2. 重新导出: 简化外部导入路径
3. 命名空间管理: 使用__all__控制包导出的符号
4. 接口与实现: 同时导出接口和具体实现
5. 插件式架构: 便于添加新的搜索引擎实现
"""

from app.tool.search.baidu_search import BaiduSearchEngine
from app.tool.search.base import WebSearchEngine
from app.tool.search.bing_search import BingSearchEngine
from app.tool.search.duckduckgo_search import DuckDuckGoSearchEngine
from app.tool.search.google_search import GoogleSearchEngine

# __all__列表明确定义了从这个包中导出的符号
# 这样当使用from app.tool.search import *时，只有这些符号会被导入
__all__ = [
    "WebSearchEngine",  # 基类接口
    "BaiduSearchEngine",  # 百度搜索引擎实现
    "DuckDuckGoSearchEngine",  # DuckDuckGo搜索引擎实现
    "GoogleSearchEngine",  # Google搜索引擎实现
    "BingSearchEngine",  # Bing搜索引擎实现
]
