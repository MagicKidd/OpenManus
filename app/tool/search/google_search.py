"""
Google搜索引擎模块 (Google Search Engine Module)

这个模块实现了Google搜索引擎，使用第三方googlesearch库与Google搜索服务交互。
它展示了如何将外部搜索API适配到统一的搜索引擎接口，处理不同的结果格式。

教学点:
1. 接口实现: 基于抽象基类实现具体功能
2. 第三方库集成: 封装外部库为统一接口
3. 数据适配: 将多种格式的外部数据转换为标准模型
4. 结果处理: 处理不同类型的搜索结果
5. 错误处理: 优雅地处理可能的异常情况
"""

from typing import List

from googlesearch import search

from app.tool.search.base import SearchItem, WebSearchEngine


class GoogleSearchEngine(WebSearchEngine):
    """Google搜索引擎实现类。

    这个类继承自WebSearchEngine基类，实现了Google搜索的具体逻辑，
    使用googlesearch库与Google搜索服务交互。它解析结果并转换为
    标准的SearchItem格式，确保与其他搜索引擎接口一致。

    设计模式:
    1. 适配器模式: 将googlesearch库的结果适配为标准SearchItem
    2. 模板方法模式: 实现抽象基类定义的搜索方法模板

    特性:
    - 支持高级搜索选项
    - 处理不同格式的搜索结果
    - 自动处理分页和结果数量
    """

    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """执行Google搜索并返回格式化结果。

        这个方法实现了WebSearchEngine.perform_search抽象方法，
        使用googlesearch库执行实际的搜索操作，并将结果转换为标准格式。

        实现流程:
        1. 使用搜索库执行查询获取原始结果
        2. 检测结果类型（字符串URL或高级结果对象）
        3. 根据类型构建适当的SearchItem对象
        4. 返回统一格式的结果列表

        参数:
            query: 要搜索的查询字符串。
            num_results: 要返回的结果数量，默认为10。
            args: 传递给搜索库的额外位置参数。
            kwargs: 传递给搜索库的额外关键字参数。

        返回:
            包含搜索结果的SearchItem对象列表。

        注意:
            googlesearch库可能返回两种格式的结果：简单的URL字符串
            或包含标题和描述的高级结果对象，此方法处理两种情况。
        """
        # 使用advanced=True获取更详细的搜索结果
        raw_results = search(query, num_results=num_results, advanced=True)

        results = []
        for i, item in enumerate(raw_results):
            if isinstance(item, str):
                # 如果结果只是一个URL字符串
                results.append(
                    {"title": f"Google Result {i+1}", "url": item, "description": ""}
                )
            else:
                # 如果是包含更多信息的高级结果对象
                results.append(
                    SearchItem(
                        title=item.title, url=item.url, description=item.description
                    )
                )

        return results
