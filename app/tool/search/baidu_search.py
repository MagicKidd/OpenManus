"""
百度搜索引擎模块 (Baidu Search Engine Module)

这个模块提供了面向百度搜索的WebSearchEngine实现，使智能体能够使用百度搜索获取信息。
它将第三方百度搜索库与项目的搜索抽象结合，处理不同格式的搜索结果。

教学点:
1. 适配器模式: 将第三方API适配到统一接口
2. 多态处理: 处理不同形式的搜索结果
3. 鲁棒性设计: 实现多层次的异常处理和后备方案
4. 数据标准化: 将多种数据格式转换为标准化模型
"""

from typing import List

from baidusearch.baidusearch import search

from app.tool.search.base import SearchItem, WebSearchEngine


class BaiduSearchEngine(WebSearchEngine):
    """百度搜索引擎实现类。

    这个类继承WebSearchEngine基类，实现了针对百度的具体搜索功能。
    它使用第三方库'baidusearch'执行实际的搜索操作，然后将结果转换为标准格式。

    设计模式:
    1. 适配器模式: 将百度API的特定输出转换为通用SearchItem格式
    2. 策略模式: 作为WebSearchEngine抽象策略的具体实现

    教学要点:
    - 如何处理不一致的第三方API返回格式
    - 通过适配器模式实现系统解耦
    - 实现异常处理和健壮的数据转换
    """

    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """执行百度搜索并格式化结果。

        这个方法覆盖了基类的抽象方法，提供百度特定的搜索实现。
        它展示了如何处理不同形式的搜索结果，并将它们统一转换为标准格式。

        转换策略:
        1. 字符串类型结果 -> 仅包含URL的SearchItem
        2. 字典类型结果 -> 从键值对提取信息的SearchItem
        3. 对象类型结果 -> 使用反射从属性获取信息的SearchItem
        4. 其他类型 -> 生成基本后备项的SearchItem

        参数:
            query: 搜索查询字符串。
            num_results: 要返回的结果数量，默认为10。
            *args, **kwargs: 额外参数，传递给底层搜索函数。

        返回:
            标准化SearchItem对象列表。
        """
        # 调用底层百度搜索API
        raw_results = search(query, num_results=num_results)

        # 将原始结果转换为统一的SearchItem格式
        results = []
        for i, item in enumerate(raw_results):
            if isinstance(item, str):
                # 如果结果是简单字符串（URL）
                results.append(
                    SearchItem(title=f"Baidu Result {i+1}", url=item, description=None)
                )
            elif isinstance(item, dict):
                # 如果结果是字典（包含详细信息）
                results.append(
                    SearchItem(
                        title=item.get("title", f"Baidu Result {i+1}"),
                        url=item.get("url", ""),
                        description=item.get("abstract", None),
                    )
                )
            else:
                # 尝试直接获取属性（对象类型）
                try:
                    results.append(
                        SearchItem(
                            title=getattr(item, "title", f"Baidu Result {i+1}"),
                            url=getattr(item, "url", ""),
                            description=getattr(item, "abstract", None),
                        )
                    )
                except Exception:
                    # 后备方案：生成基本结果
                    results.append(
                        SearchItem(
                            title=f"Baidu Result {i+1}", url=str(item), description=None
                        )
                    )

        return results
