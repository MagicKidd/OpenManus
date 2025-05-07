"""
Web搜索工具模块 (Web Search Tool Module)

这个模块实现了智能体的网络搜索能力，允许查询多个搜索引擎并处理结果。
它展示了如何构建与外部Web服务交互的工具，处理并格式化返回的数据。

教学点:
1. 外部API集成: 如何与外部搜索引擎交互
2. 数据建模: 使用Pydantic定义结构化数据模型
3. 异步网络请求: 使用asyncio处理网络IO
4. 故障恢复: 实现搜索引擎回退机制
5. 数据转换: 解析和格式化搜索结果
"""

import asyncio
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, model_validator
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import config
from app.logger import logger
from app.tool.base import BaseTool, ToolResult
from app.tool.search import (
    BaiduSearchEngine,
    BingSearchEngine,
    DuckDuckGoSearchEngine,
    GoogleSearchEngine,
    WebSearchEngine,
)
from app.tool.search.base import SearchItem


class SearchResult(BaseModel):
    """搜索结果数据模型。

    表示从搜索引擎返回的单个搜索结果，包含URL、标题、描述等信息。
    这是一个Pydantic模型，提供数据验证和序列化功能。

    数据建模特点:
    1. 字段验证: 定义字段类型和必需性
    2. 字段描述: 使用Field添加字段文档
    3. 配置: 使用ConfigDict设置模型配置

    属性:
        position: 结果在搜索结果中的位置。
        url: 结果的URL。
        title: 结果的标题。
        description: 结果的描述或摘要。
        source: 提供此结果的搜索引擎。
        raw_content: 可选的页面原始内容。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    position: int = Field(description="Position in search results")
    url: str = Field(description="URL of the search result")
    title: str = Field(default="", description="Title of the search result")
    description: str = Field(
        default="", description="Description or snippet of the search result"
    )
    source: str = Field(description="The search engine that provided this result")
    raw_content: Optional[str] = Field(
        default=None, description="Raw content from the search result page if available"
    )

    def __str__(self) -> str:
        """字符串表示方法。

        提供对象的可读字符串表示，用于日志记录和调试。

        返回:
            结果标题和URL的字符串表示。
        """
        return f"{self.title} ({self.url})"


class SearchMetadata(BaseModel):
    """搜索元数据模型。

    包含关于搜索操作的元数据，如结果总数和语言设置。
    这使搜索工具可以提供有关搜索上下文的附加信息。

    教学点:
    使用单独的模型表示元数据，遵循关注点分离原则

    属性:
        total_results: 找到的结果总数。
        language: 用于搜索的语言代码。
        country: 用于搜索的国家代码。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    total_results: int = Field(description="Total number of results found")
    language: str = Field(description="Language code used for the search")
    country: str = Field(description="Country code used for the search")


class SearchResponse(ToolResult):
    """Web搜索响应模型。

    继承自ToolResult的Web搜索特定响应类，包含搜索结果和元数据。
    展示了如何扩展基础结果类以包含特定工具的数据结构。

    设计模式:
    1. 继承: 扩展基本ToolResult类
    2. 组合: 包含SearchResult列表和SearchMetadata
    3. 验证器: 使用model_validator自定义验证和后处理

    属性:
        query: 执行的搜索查询。
        results: 搜索结果列表。
        metadata: 关于搜索的元数据。
    """

    query: str = Field(description="The search query that was executed")
    results: List[SearchResult] = Field(
        default_factory=list, description="List of search results"
    )
    metadata: Optional[SearchMetadata] = Field(
        default=None, description="Metadata about the search"
    )

    @model_validator(mode="after")
    def populate_output(self) -> "SearchResponse":
        """填充输出字段。

        这个验证器在模型创建后运行，将搜索结果转换为格式化文本。
        它展示了Pydantic的模型验证器如何用于后处理和派生字段。

        处理逻辑:
        1. 如果有错误，保留错误信息
        2. 构建格式化的搜索结果文本
        3. 添加结果摘要和元数据

        返回:
            更新后的SearchResponse实例。
        """
        if self.error:
            return self

        result_text = [f"Search results for '{self.query}':"]

        for i, result in enumerate(self.results, 1):
            # 添加带有位置编号的标题
            title = result.title.strip() or "No title"
            result_text.append(f"\n{i}. {title}")

            # 添加带有适当缩进的URL
            result_text.append(f"   URL: {result.url}")

            # 如果有描述则添加
            if result.description.strip():
                result_text.append(f"   Description: {result.description}")

            # 如果有内容预览则添加
            if result.raw_content:
                content_preview = result.raw_content[:1000].replace("\n", " ").strip()
                if len(result.raw_content) > 1000:
                    content_preview += "..."
                result_text.append(f"   Content: {content_preview}")

        # 在底部添加元数据（如果有）
        if self.metadata:
            result_text.extend(
                [
                    f"\nMetadata:",
                    f"- Total results: {self.metadata.total_results}",
                    f"- Language: {self.metadata.language}",
                    f"- Country: {self.metadata.country}",
                ]
            )

        self.output = "\n".join(result_text)
        return self


class WebContentFetcher:
    """网页内容获取器。

    用于从网页URL获取和提取主要文本内容的工具类。
    它展示了如何安全地发出HTTP请求并解析HTML内容。

    设计模式:
    工具类模式 - 将相关功能组织在一个类中，但不要求实例化

    教学点:
    1. 异步网络请求: 在事件循环中运行同步网络调用
    2. HTML解析: 使用BeautifulSoup解析和清理HTML
    3. 异常处理: 优雅处理网络错误和解析问题
    """

    @staticmethod
    async def fetch_content(url: str, timeout: int = 10) -> Optional[str]:
        """获取并提取网页的主要内容。

        这个方法展示了如何:
        1. 发出HTTP请求获取网页内容
        2. 解析HTML提取主要文本
        3. 清理文本内容以便于处理
        4. 安全处理各种错误情况

        技术细节:
        - 使用用户代理头避免被屏蔽
        - 使用asyncio.get_event_loop().run_in_executor将同步请求转为异步
        - 使用BeautifulSoup解析和清理HTML

        参数:
            url: 要获取内容的URL
            timeout: 请求超时时间（秒）

        返回:
            提取的文本内容，或者在获取失败时返回None
        """
        headers = {
            "WebSearch": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        try:
            # 使用asyncio在线程池中运行请求
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: requests.get(url, headers=headers, timeout=timeout)
            )

            if response.status_code != 200:
                logger.warning(
                    f"Failed to fetch content from {url}: HTTP {response.status_code}"
                )
                return None

            # 使用BeautifulSoup解析HTML
            soup = BeautifulSoup(response.text, "html.parser")

            # 移除脚本和样式元素
            for script in soup(["script", "style", "header", "footer", "nav"]):
                script.extract()

            # 获取文本内容
            text = soup.get_text(separator="\n", strip=True)

            # 清理空白并限制大小（最大100KB）
            text = " ".join(text.split())
            return text[:10000] if text else None

        except Exception as e:
            logger.warning(f"Error fetching content from {url}: {e}")
            return None


class WebSearch(BaseTool):
    """Web搜索工具。

    这个工具允许智能体通过多个搜索引擎搜索网络获取信息。
    它展示了如何构建复杂工具，集成外部服务并处理结果。

    设计特点:
    1. 多引擎支持: 可使用多个不同的搜索引擎
    2. 故障恢复: 一个搜索引擎失败时自动回退到其他引擎
    3. 灵活配置: 支持语言、国家和结果数量配置
    4. 内容获取: 可选地获取结果页面的完整内容

    属性:
        name: 工具名称。
        description: 工具功能描述。
        parameters: 工具参数的JSON Schema定义。
        _search_engine: 搜索引擎实例的字典。
        content_fetcher: 用于获取页面内容的实用工具。
    """

    name: str = "web_search"
    description: str = """Search the web for real-time information about any topic.
    This tool returns comprehensive search results with relevant information, URLs, titles, and descriptions.
    If the primary search engine fails, it automatically falls back to alternative engines."""
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "(required) The search query to submit to the search engine.",
            },
            "num_results": {
                "type": "integer",
                "description": "(optional) The number of search results to return. Default is 5.",
                "default": 5,
            },
            "lang": {
                "type": "string",
                "description": "(optional) Language code for search results (default: en).",
                "default": "en",
            },
            "country": {
                "type": "string",
                "description": "(optional) Country code for search results (default: us).",
                "default": "us",
            },
            "fetch_content": {
                "type": "boolean",
                "description": "(optional) Whether to fetch full content from result pages. Default is false.",
                "default": False,
            },
        },
        "required": ["query"],
    }
    _search_engine: dict[str, WebSearchEngine] = {
        "google": GoogleSearchEngine(),
        "baidu": BaiduSearchEngine(),
        "duckduckgo": DuckDuckGoSearchEngine(),
        "bing": BingSearchEngine(),
    }
    content_fetcher: WebContentFetcher = WebContentFetcher()

    async def execute(
        self,
        query: str,
        num_results: int = 5,
        lang: Optional[str] = None,
        country: Optional[str] = None,
        fetch_content: bool = False,
    ) -> SearchResponse:
        """执行Web搜索。

        这个方法实现了BaseTool的抽象execute方法，是工具的主要入口点。
        它组织搜索流程，处理结果，并在需要时获取页面内容。

        执行流程:
        1. 准备搜索参数和元数据
        2. 尝试所有配置的搜索引擎直到成功
        3. 如果需要，获取页面内容
        4. 创建并返回格式化的结果

        错误处理:
        使用try-except块捕获和处理各种异常，确保优雅地处理错误

        参数:
            query: 要搜索的查询字符串
            num_results: 要返回的结果数
            lang: 搜索语言代码（如en、zh）
            country: 搜索国家代码（如us、cn）
            fetch_content: 是否获取结果页面的完整内容

        返回:
            包含搜索结果的SearchResponse对象
        """
        try:
            # 使用配置中的默认值或传入的值
            lang = lang or config.search.lang or "en"
            country = country or config.search.country or "us"

            logger.info(f"Searching for: {query} (lang: {lang}, country: {country})")

            # 准备搜索参数
            search_params = {
                "lang": lang,
                "country": country,
            }

            # 尝试所有搜索引擎
            results = await self._try_all_engines(query, num_results, search_params)

            # 检查是否有结果
            if not results:
                return SearchResponse(
                    query=query,
                    error="No search results found or all search engines failed.",
                    metadata=SearchMetadata(
                        total_results=0, language=lang, country=country
                    ),
                )

            # 如果需要，获取页面内容
            if fetch_content and results:
                results = await self._fetch_content_for_results(results)

            # 创建搜索元数据
            metadata = SearchMetadata(
                total_results=len(results), language=lang, country=country
            )

            # 返回搜索响应
            return SearchResponse(query=query, results=results, metadata=metadata)

        except Exception as e:
            logger.error(f"Error in web search: {e}")
            return SearchResponse(
                query=query, error=f"Error performing web search: {str(e)}"
            )

    async def _try_all_engines(
        self, query: str, num_results: int, search_params: Dict[str, Any]
    ) -> List[SearchResult]:
        """尝试所有搜索引擎直到成功。

        这个方法实现了引擎回退逻辑，如果一个引擎失败，尝试下一个。
        它展示了如何在复杂系统中实现故障恢复机制。

        策略:
        1. 首先尝试首选搜索引擎
        2. 如果失败，按优先级尝试其他引擎
        3. 合并和去重结果

        参数:
            query: 搜索查询
            num_results: 结果数量
            search_params: 搜索参数字典

        返回:
            搜索结果列表，如果全部引擎失败则为空列表
        """
        all_results = []
        used_urls = set()  # 跟踪已见过的URL以避免重复

        # 获取搜索引擎优先级顺序
        engines = self._get_engine_order()

        # 尝试每个搜索引擎直到成功或全部失败
        for engine_name in engines:
            if engine_name not in self._search_engine:
                logger.warning(f"Search engine {engine_name} not found, skipping")
                continue

            engine = self._search_engine[engine_name]
            try:
                # 执行搜索
                raw_results = await self._perform_search_with_engine(
                    engine, query, num_results * 2, search_params
                )  # 获取更多结果以允许去重

                if not raw_results:
                    continue

                # 将原始结果转换为SearchResult模型
                position = len(all_results) + 1
                for item in raw_results:
                    # 跳过重复URL
                    if item.url in used_urls:
                        continue

                    result = SearchResult(
                        position=position,
                        url=item.url,
                        title=item.title,
                        description=item.snippet,
                        source=engine_name,
                    )
                    all_results.append(result)
                    used_urls.add(item.url)
                    position += 1

                    # 如果达到所需结果数，停止
                    if len(all_results) >= num_results:
                        break

                # 如果找到了足够的结果，停止尝试其他引擎
                if len(all_results) >= num_results:
                    break

            except Exception as e:
                logger.warning(f"Search engine {engine_name} failed: {e}")
                continue  # 尝试下一个引擎

        return all_results[:num_results]  # 限制结果数量

    async def _fetch_content_for_results(
        self, results: List[SearchResult]
    ) -> List[SearchResult]:
        """获取结果页面的内容。

        这个方法展示了如何并行执行多个异步任务以提高效率。
        它使用asyncio.gather来并发获取多个页面的内容。

        技术亮点:
        1. 并发获取: 同时获取多个URL的内容
        2. 任务协调: 使用asyncio.gather来管理多个协程任务
        3. 不阻塞主事件循环: 所有网络操作都是异步的

        参数:
            results: 要获取内容的搜索结果列表

        返回:
            更新了raw_content字段的结果列表
        """
        # 创建获取内容的任务列表
        content_tasks = [
            self._fetch_single_result_content(result) for result in results
        ]

        # 并行执行所有任务
        updated_results = await asyncio.gather(*content_tasks)
        return updated_results

    async def _fetch_single_result_content(self, result: SearchResult) -> SearchResult:
        """获取单个结果的内容。

        为单个搜索结果获取和更新页面内容的辅助方法。
        它展示了不可变数据处理模式，不直接修改对象而是创建新实例。

        参数:
            result: 要获取内容的搜索结果

        返回:
            更新了raw_content的搜索结果（如果成功）
        """
        content = await self.content_fetcher.fetch_content(result.url)
        if content:
            return result.model_copy(update={"raw_content": content})
        return result

    def _get_engine_order(self) -> List[str]:
        """获取搜索引擎优先级顺序。

        这个方法定义了引擎使用的优先级顺序，可以基于配置或其他因素。
        它展示了如何实现优先级策略，在故障恢复场景中很有用。

        策略模式:
        通过配置或代码定义策略顺序，使实现可灵活调整

        用例:
        - 基于首选引擎的可用性
        - 基于搜索查询的特性选择合适的引擎
        - 基于用户位置选择区域特定的引擎

        返回:
            按优先级排序的引擎名称列表
        """
        # 默认优先级顺序
        default_order = ["google", "bing", "duckduckgo", "baidu"]

        # 从配置中获取首选搜索引擎
        primary_engine = config.search.engine.lower() if config.search.engine else None

        # 如果配置了首选引擎并且它存在，将其置于优先级列表首位
        if primary_engine and primary_engine in self._search_engine:
            engines = [primary_engine]
            # 添加其他引擎（不包括主引擎）
            engines.extend([e for e in default_order if e != primary_engine])
            return engines

        # 如果没有配置首选引擎，使用默认顺序
        return default_order

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    async def _perform_search_with_engine(
        self,
        engine: WebSearchEngine,
        query: str,
        num_results: int,
        search_params: Dict[str, Any],
    ) -> List[SearchItem]:
        """使用指定引擎执行搜索。

        这个方法处理与特定搜索引擎的通信，并包含重试逻辑以处理临时故障。
        它展示了如何使用装饰器实现重试模式。

        技术亮点:
        1. 重试装饰器: 使用tenacity库实现指数退避重试
        2. 异步接口: 调用异步搜索引擎方法
        3. 异常处理: 捕获并记录搜索错误

        参数:
            engine: 使用的搜索引擎实例
            query: 搜索查询
            num_results: 需要的结果数
            search_params: 搜索参数字典

        返回:
            搜索结果列表或空列表（如果搜索失败）

        异常:
            Exception: 如果在所有重试后搜索仍然失败
        """
        try:
            logger.info(f"Searching with engine: {engine.__class__.__name__}")
            results = await engine.search(query, num_results, **search_params)
            return results
        except Exception as e:
            logger.error(f"Error with search engine {engine.__class__.__name__}: {e}")
            raise  # 重新抛出以触发重试


if __name__ == "__main__":
    web_search = WebSearch()
    search_response = asyncio.run(
        web_search.execute(
            query="Python programming", fetch_content=True, num_results=1
        )
    )
    print(search_response.to_tool_result())
