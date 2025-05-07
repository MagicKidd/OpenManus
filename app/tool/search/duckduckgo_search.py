"""
DuckDuckGo搜索引擎模块 (DuckDuckGo Search Engine Module)

这个模块提供了对DuckDuckGo搜索引擎的集成，使智能体能够使用注重隐私的搜索服务。
它展示了如何封装第三方搜索库，处理多种结果格式，并提供统一的接口。

教学点:
1. 第三方库集成: 使用duckduckgo_search库进行搜索
2. 多态性处理: 识别并处理不同类型的搜索结果
3. 容错式编程: 实现多层次的错误处理和后备策略
4. 类型转换: 将多样化的输入转换为标准化的数据模型
"""

from typing import List

from duckduckgo_search import DDGS

from app.tool.search.base import SearchItem, WebSearchEngine


class DuckDuckGoSearchEngine(WebSearchEngine):
    """DuckDuckGo搜索引擎实现类。

    这个类封装了DuckDuckGo搜索的特定功能，使用官方的Python库执行搜索，
    并将结果转换为统一的SearchItem格式。它展示了简洁的库集成模式。

    设计模式:
    1. 适配器模式: 将DuckDuckGo API的输出转换为通用SearchItem格式
    2. 策略模式: 作为WebSearchEngine抽象策略的具体实现

    教学要点:
    - 如何简洁地集成第三方库
    - 如何处理不一致的返回格式
    - 优雅地降级处理意外的数据结构
    """

    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """执行DuckDuckGo搜索并格式化结果。

        这个方法是核心搜索实现，它调用DuckDuckGo搜索API并处理结果。
        它展示了如何处理不同格式的结果，并将它们统一为标准格式。

        转换策略:
        1. 字符串结果: 转换为仅包含URL的基本结果
        2. 字典结果: 从键值对中提取标题、URL和描述
        3. 对象结果: 使用getattr()从属性中提取信息
        4. 其他类型: 生成包含最小信息的后备结果

        参数:
            query: 搜索查询字符串。
            num_results: 要返回的结果数量，默认为10。
            *args, **kwargs: 额外参数，未使用但保留兼容性。

        返回:
            标准化的SearchItem对象列表。
        """
        # 使用DDGS库执行文本搜索
        raw_results = DDGS().text(query, max_results=num_results)

        results = []
        for i, item in enumerate(raw_results):
            if isinstance(item, str):
                # 处理简单字符串结果(URL)
                results.append(
                    SearchItem(
                        title=f"DuckDuckGo Result {i + 1}", url=item, description=None
                    )
                )
            elif isinstance(item, dict):
                # 处理字典格式的结果(最常见)
                # DuckDuckGo通常返回包含title、href和body字段的字典
                results.append(
                    SearchItem(
                        title=item.get("title", f"DuckDuckGo Result {i + 1}"),
                        url=item.get("href", ""),
                        description=item.get("body", None),
                    )
                )
            else:
                # 尝试将结果作为对象处理，使用getattr获取属性
                try:
                    results.append(
                        SearchItem(
                            title=getattr(item, "title", f"DuckDuckGo Result {i + 1}"),
                            url=getattr(item, "href", ""),
                            description=getattr(item, "body", None),
                        )
                    )
                except Exception:
                    # 最后的后备策略：创建最小化的结果对象
                    results.append(
                        SearchItem(
                            title=f"DuckDuckGo Result {i + 1}",
                            url=str(item),
                            description=None,
                        )
                    )

        return results
