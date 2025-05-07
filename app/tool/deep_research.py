"""
深度研究工具模块 (Deep Research Tool Module)

这个模块实现了智能体的高级研究能力，通过迭代式Web搜索、内容分析和跟进查询探索复杂主题。
它使用LLM优化查询、提取洞见并生成后续问题，实现类似于人类研究者的深度理解过程。

教学点:
1. 递归与迭代研究: 模拟人类研究过程的深度优先探索模式
2. LLM任务分解: 将复杂研究任务分解为多个LLM子任务
3. 异步并发: 使用asyncio实现高效并行处理
4. 结构化数据流: 使用Pydantic模型进行类型安全的状态管理
5. 时间约束处理: 实现带有截止时间的任务
"""

import asyncio
import json
import re
import time
from typing import List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.exceptions import ToolError
from app.llm import LLM
from app.logger import logger
from app.schema import ToolChoice
from app.tool.base import BaseTool, ToolResult
from app.tool.web_search import SearchResult, WebSearch

# LLM提示词模板 - 每个模板专注于研究过程中的特定阶段
# 查询优化: 将用户问题转换为更有效的搜索关键词
OPTIMIZE_QUERY_PROMPT = """
You are a research assistant helping to optimize a search query for web research.
Your task is to reformulate the given query to be more effective for web searches.
Make it specific, use relevant keywords, and ensure it's clear and concise.

Original query: {query}

Provide only the optimized query text without any explanation or additional formatting.
"""

# 洞见提取: 从网页内容中提取关键信息并评估相关性
EXTRACT_INSIGHTS_PROMPT = """
Analyze the following content and extract key insights related to the research query.
For each insight, assess its relevance to the query on a scale of 0.0 to 1.0.

Research query: {query}
Content to analyze:
{content}

Extract up to 3 most important insights from this content. For each insight:
1. Provide the insight content
2. Provide relevance score (0.0-1.0)
"""

# 跟进问题生成: 基于当前发现创建新的探索方向
GENERATE_FOLLOW_UPS_PROMPT = """
Based on the insights discovered so far, generate follow-up research queries to explore gaps or related areas.
These should help deepen our understanding of the topic.

Original query: {original_query}
Current query: {current_query}
Key insights so far:
{insights}

Generate up to 3 specific follow-up queries that would help address gaps in our current knowledge.
Each query should be concise and focused on a specific aspect of the research topic.
"""

# 洞见解析相关常量 - 用于从LLM响应中提取结构化信息
DEFAULT_RELEVANCE_SCORE = 1.0  # 默认相关性分数
FALLBACK_RELEVANCE_SCORE = 0.7  # 当无法提取分数时的后备值
FALLBACK_CONTENT_LIMIT = 500  # 后备内容的最大长度限制

# 正则表达式模式用于解析非结构化LLM输出
# 用于检测洞见条目的开始(如数字、短横线、星号等)
INSIGHT_MARKER_PATTERN = re.compile(r"^\s*(?:\d+\.|-|\*|•)\s*(.*)")
# 用于提取相关性分数(不区分大小写)
RELEVANCE_SCORE_PATTERN = re.compile(r"relevance.*?:.*?(\d\.?\d*)", re.IGNORECASE)


class ResearchInsight(BaseModel):
    """研究洞见类 - 表示从内容中提取的单个关键发现。

    这个类封装了研究过程中发现的单个洞见，包括内容、来源和相关性评分。
    它通过不可变设计(frozen=True)防止洞见被意外修改，确保数据一致性。

    设计特点:
    1. 不可变对象: 使用ConfigDict(frozen=True)确保洞见一旦创建就不可更改
    2. 源归属: 始终包含来源信息，确保可追溯性
    3. 相关性量化: 使用0-1的浮点数表示洞见与研究问题的相关性

    属性:
        content: 洞见的具体内容文本。
        source_url: 发现该洞见的网页URL。
        source_title: 来源网页的标题(可选)。
        relevance_score: 相关性评分，范围0.0-1.0。
    """

    model_config = ConfigDict(frozen=True)  # Make insights immutable

    content: str = Field(description="The insight content")
    source_url: str = Field(description="URL where this insight was found")
    source_title: Optional[str] = Field(default=None, description="Title of the source")
    relevance_score: float = Field(
        default=1.0, description="Relevance score (0.0-1.0)", ge=0.0, le=1.0
    )

    def __str__(self) -> str:
        """将洞见格式化为带有来源引用的字符串。

        这提供了一种人类可读的表示，便于显示与调试。

        返回:
            格式化的洞见字符串，包含内容和来源信息。
        """
        source = self.source_title or self.source_url
        return f"{self.content} [Source: {source}]"


class ResearchContext(BaseModel):
    """研究上下文类 - 跟踪和管理整个研究过程的状态。

    这个类维护研究过程的全局状态，包括已收集的洞见、已访问的URL和研究深度。
    它作为研究过程中的状态容器，支持递归研究和并行探索。

    设计特点:
    1. 状态集中管理: 将研究状态集中在单一对象中
    2. 递归边界控制: 通过深度限制防止无限递归
    3. 资源有效利用: 通过跟踪已访问URL避免重复处理

    属性:
        query: 原始研究查询。
        insights: 已发现的洞见列表。
        follow_up_queries: 生成的后续查询问题列表。
        visited_urls: 已访问URL的集合(使用Set确保唯一性)。
        current_depth: 当前研究的深度级别。
        max_depth: 最大允许的研究深度。
    """

    query: str = Field(description="The original research query")
    insights: List[ResearchInsight] = Field(
        default_factory=list, description="Key insights discovered"
    )
    follow_up_queries: List[str] = Field(
        default_factory=list, description="Generated follow-up queries"
    )
    visited_urls: Set[str] = Field(
        default_factory=set, description="URLs visited during research"
    )
    current_depth: int = Field(
        default=0, description="Current depth of research exploration", ge=0
    )
    max_depth: int = Field(
        default=2, description="Maximum depth of research to reach", ge=1
    )


class ResearchSummary(ToolResult):
    """研究总结类 - 深度研究结果的全面摘要。

    这个类继承自ToolResult，提供结构化的研究结果输出。
    它不仅存储原始数据，还通过model_validator自动生成格式化的可读输出。

    设计特点:
    1. 后处理验证: 使用model_validator在验证后填充输出字段
    2. 分层组织: 按相关性分组和分类洞见
    3. 丰富的元数据: 包含覆盖范围和深度指标

    属性:
        query: 原始研究查询。
        insights: 发现的洞见列表。
        visited_urls: 已访问URL的集合。
        depth_reached: 达到的最大研究深度。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    query: str = Field(description="The original research query")
    insights: List[ResearchInsight] = Field(
        default_factory=list, description="Key insights discovered"
    )
    visited_urls: Set[str] = Field(
        default_factory=set, description="URLs visited during research"
    )
    depth_reached: int = Field(
        default=0, description="Maximum depth of research reached", ge=0
    )

    @model_validator(mode="after")
    def populate_output(self) -> "ResearchSummary":
        """验证后填充输出字段。

        这个方法演示了Pydantic的高级功能 - 在模型验证后进行自定义处理。
        它根据相关性对洞见进行分组，并生成结构化的Markdown格式输出。

        格式化策略:
        1. 按相关性分为3个层次(关键发现、额外信息、补充信息)
        2. 为每个洞见添加来源引用
        3. 包含元数据统计(来源数量、研究深度)

        返回:
            填充了output字段的研究总结对象。
        """
        # 按相关性分组洞见
        grouped_insights = {
            "Key Findings": [i for i in self.insights if i.relevance_score >= 0.8],
            "Additional Information": [
                i for i in self.insights if 0.5 <= i.relevance_score < 0.8
            ],
            "Supplementary Information": [
                i for i in self.insights if i.relevance_score < 0.5
            ],
        }

        sections = [
            f"# Research: {self.query}\n",
            f"**Sources**: {len(self.visited_urls)} | **Depth**: {self.depth_reached + 1}\n",
        ]

        for section_title, insights in grouped_insights.items():
            if insights:
                sections.append(f"## {section_title}")
                for i, insight in enumerate(insights, 1):
                    sections.extend(
                        [
                            insight.content,
                            f"> Source: [{insight.source_title or 'Link'}]({insight.source_url})\n",
                        ]
                    )

        # 将格式化字符串赋值给从ToolResult继承的'output'字段
        self.output = "\n".join(sections)
        return self


class DeepResearch(BaseTool):
    """深度研究工具 - 通过迭代Web搜索和内容分析进行全面研究。

    这个工具实现了一个多层次的研究过程，模拟人类研究者的方法:
    1. 优化初始查询
    2. 搜索相关内容
    3. 提取关键洞见
    4. 生成后续问题
    5. 递归探索新方向

    设计模式:
    1. 递归探索: 使用深度优先方式深入研究主题
    2. 并行处理: 使用asyncio.gather并行执行多个查询
    3. 依赖注入: 通过Field工厂函数注入依赖工具
    4. 约束执行: 使用时间限制和深度限制控制资源使用

    教学要点:
    - 异步编程中的任务组织和并行执行
    - 通过依赖注入实现松耦合和可测试性
    - 复杂任务的结构化分解与组合
    """

    name: str = "deep_research"
    description: str = """
    Performs comprehensive research on a topic through multi-level web searches
    and content analysis. Returns a structured summary of findings with source
    attribution and relevance ratings.
    """
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The research question or topic to investigate.",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum depth of iterative research (1-5). Default is 2.",
                "default": 2,
            },
            "results_per_search": {
                "type": "integer",
                "description": "Number of search results to analyze per search (1-20). Default is 5.",
                "default": 5,
            },
            "max_insights": {
                "type": "integer",
                "description": "Maximum number of insights to return. Default is 20.",
                "default": 20,
            },
            "time_limit_seconds": {
                "type": "integer",
                "description": "Maximum execution time in seconds. Default is 120.",
                "default": 120,
            },
        },
        "required": ["query"],
    }

    # 通过依赖注入实现松耦合和可测试性
    search_tool: WebSearch = Field(default_factory=WebSearch)
    llm: LLM = Field(default_factory=LLM)

    async def execute(
        self,
        query: str,
        max_depth: int = 2,
        results_per_search: int = 5,
        max_insights: int = 20,
        time_limit_seconds: int = 120,
    ) -> ResearchSummary:
        """执行深度研究。

        这是工具的主入口点，它协调整个研究过程，包括参数校验、
        状态初始化、研究执行和结果汇总。

        实现策略:
        1. 参数规范化: 确保参数在合理范围内
        2. 时间限制: 设置截止时间防止无限执行
        3. 错误容忍: 捕获并记录错误但不中断整体流程

        参数:
            query: 研究的问题或主题。
            max_depth: 迭代研究的最大深度(1-5)。
            results_per_search: 每次搜索分析的结果数(1-20)。
            max_insights: 返回的最大洞见数。
            time_limit_seconds: 执行时间限制(秒)。

        返回:
            包含研究结果的结构化摘要对象。
        """
        # 规范化参数
        max_depth = max(1, min(max_depth, 5))
        results_per_search = max(1, min(results_per_search, 20))

        # 初始化研究上下文并设置截止时间
        context = ResearchContext(query=query, max_depth=max_depth)
        deadline = time.time() + time_limit_seconds

        try:
            # 使用优化查询启动研究过程
            optimized_query = await self._generate_optimized_query(query)
            await self._research_graph(
                context=context,
                query=optimized_query,
                results_count=results_per_search,
                deadline=deadline,
            )
        except ToolError as e:
            logger.error(f"Research error: {str(e)}")

        # 准备最终摘要
        return ResearchSummary(
            query=query,
            insights=sorted(
                context.insights, key=lambda x: x.relevance_score, reverse=True
            )[:max_insights],
            visited_urls=context.visited_urls,
            depth_reached=context.current_depth,
        )

    async def _generate_optimized_query(self, query: str) -> str:
        """使用LLM生成优化的搜索查询。

        这个方法演示了如何使用LLM的工具调用模式来生成结构化输出。
        它通过prompt工程将原始查询转换为更有效的搜索术语。

        LLM工具交互模式:
        1. 构建针对性prompt
        2. 使用工具定义指导LLM生成结构化输出
        3. 解析工具调用响应
        4. 实现错误处理和后备策略

        参数:
            query: 原始查询字符串。

        返回:
            优化后的查询字符串，或在错误情况下返回原始查询。
        """
        try:
            prompt = OPTIMIZE_QUERY_PROMPT.format(query=query)
            response = await self.llm.ask_tool(
                [{"role": "user", "content": prompt}],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "optimize_query",
                            "description": "Generate an optimized search query",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "query": {
                                        "type": "string",
                                        "description": "The optimized search query",
                                    }
                                },
                                "required": ["query"],
                            },
                        },
                    }
                ],
                tool_choice=ToolChoice.REQUIRED,
                stream=False,
            )

            # 从工具调用响应中提取查询
            if response and response.tool_calls and len(response.tool_calls) > 0:
                tool_call = response.tool_calls[0]
                arguments = json.loads(tool_call.function.arguments)
                optimized_query = arguments.get("query", "")
            else:
                # 如果工具调用失败，返回原始查询
                logger.warning("Tool call failed to return a valid response")
                return query

            if not optimized_query:
                logger.warning("Generated empty optimized query, using original")
                return query

            logger.info(f"Optimized query: '{optimized_query}'")
            return optimized_query
        except Exception as e:
            logger.warning(f"Failed to optimize query: {str(e)}")
            return query  # 错误时返回原始查询

    async def _research_graph(
        self,
        context: ResearchContext,
        query: str,
        results_count: int,
        deadline: float,
    ) -> None:
        """执行完整的研究周期(搜索、分析、生成后续问题)。

        这个方法是研究过程的核心，实现了递归式研究图的构建。
        它通过深度优先方式构建研究树，每个节点代表一个查询方向。

        研究周期步骤:
        1. 执行Web搜索获取内容
        2. 分析内容提取洞见
        3. 基于洞见生成后续问题
        4. 递归深入探索后续问题

        并发处理策略:
        - 使用asyncio.gather并行探索多个后续问题
        - 随着深度增加减少每个分支的结果数量

        参数:
            context: 研究上下文对象。
            query: 当前查询字符串。
            results_count: 要分析的搜索结果数量。
            deadline: 执行截止时间戳。
        """
        # 检查终止条件
        if time.time() >= deadline or context.current_depth >= context.max_depth:
            return

        # 记录当前研究步骤
        logger.info(f"Research cycle at depth {context.current_depth + 1}")

        # 1. Web搜索
        search_results = await self._search_web(query, results_count)
        if not search_results:
            return

        # 2. 提取洞见
        new_insights = await self._extract_insights(
            context, search_results, context.query, deadline
        )
        if not new_insights:
            return

        # 3. 生成后续问题
        follow_up_queries = await self._generate_follow_ups(
            new_insights, query, context.query
        )
        context.follow_up_queries.extend(follow_up_queries)

        # 更新深度并进入下一级
        context.current_depth += 1

        # 4. 使用后续问题继续研究
        if follow_up_queries and context.current_depth < context.max_depth:
            tasks = []  # 创建任务列表
            for follow_up in follow_up_queries[:2]:  # 限制分支因子
                if time.time() >= deadline:
                    break

                # 创建递归研究调用的协程
                task = self._research_graph(
                    context=context,
                    query=follow_up,
                    results_count=max(1, results_count - 1),  # 减少结果数量
                    deadline=deadline,
                )
                tasks.append(task)  # 将任务添加到列表

            # 并发运行所有创建的任务
            if tasks:
                await asyncio.gather(*tasks)

    async def _search_web(self, query: str, results_count: int) -> List[SearchResult]:
        """执行Web搜索。

        这个辅助方法封装了与搜索工具的交互，展示了工具组合模式。

        参数:
            query: 搜索查询。
            results_count: 要获取的结果数量。

        返回:
            搜索结果列表，如果出错则返回空列表。
        """
        search_response = await self.search_tool.execute(
            query=query, num_results=results_count, fetch_content=True
        )
        return [] if search_response.error else search_response.results

    async def _extract_insights(
        self,
        context: ResearchContext,
        results: List[SearchResult],
        original_query: str,
        deadline: float,
    ) -> List[ResearchInsight]:
        """从搜索结果中提取洞见。

        这个方法处理搜索结果集，从内容中提取洞见，并更新上下文。
        它实现了资源效率优化，通过跳过已访问URL和限制内容大小。

        设计考虑:
        1. URL去重: 避免分析同一网页多次
        2. 时间管理: 检查截止时间避免超时
        3. 内容限制: 截断过长内容以提高LLM处理效率

        参数:
            context: 研究上下文。
            results: 搜索结果列表。
            original_query: 原始研究查询。
            deadline: 执行截止时间。

        返回:
            从本次分析中提取的新洞见列表。
        """
        all_insights = []

        for rst in results:
            # 如果URL已访问或时间已超过，则跳过
            if rst.url in context.visited_urls or time.time() >= deadline:
                continue

            context.visited_urls.add(rst.url)

            # 如果没有可用内容，则跳过
            if not rst.raw_content:
                continue

            # 使用LLM提取洞见
            insights = await self._analyze_content(
                content=rst.raw_content[:10000],  # 限制内容大小
                url=rst.url,
                title=rst.title,
                query=original_query,
            )

            all_insights.extend(insights)
            context.insights.extend(insights)

            # 记录发现的洞见
            logger.info(f"Extracted {len(insights)} insights from {rst.url}")

        return all_insights

    async def _generate_follow_ups(
        self, insights: List[ResearchInsight], current_query: str, original_query: str
    ) -> List[str]:
        """基于洞见生成后续查询。

        这个方法使用LLM基于已收集的洞见生成新的研究方向。
        它展示了如何引导LLM生成有针对性的扩展问题。

        实现细节:
        1. 上下文构建: 将洞见格式化为LLM可消费的形式
        2. 工具输出定义: 使用JSON Schema定义期望的输出结构
        3. 结果验证: 确保输出符合预期格式并限制数量

        参数:
            insights: 已收集的洞见列表。
            current_query: 当前查询字符串。
            original_query: 原始研究查询。

        返回:
            后续查询列表(最多3个)。
        """
        if not insights:
            return []

        # 为prompt格式化洞见
        insights_text = "\n".join([f"- {insight.content}" for insight in insights[:5]])

        # 创建生成后续问题的prompt
        prompt = GENERATE_FOLLOW_UPS_PROMPT.format(
            original_query=original_query,
            current_query=current_query,
            insights=insights_text,
        )

        # 使用结构化输出从LLM获取后续问题
        response = await self.llm.ask_tool(
            [{"role": "user", "content": prompt}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "generate_follow_ups",
                        "description": "Generate follow-up queries based on research insights",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "follow_up_queries": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of follow-up queries (max 3) that would help address gaps in current knowledge",
                                    "maxItems": 3,
                                }
                            },
                            "required": ["follow_up_queries"],
                        },
                    },
                }
            ],
            tool_choice=ToolChoice.REQUIRED,
            stream=False,
        )

        # 从工具响应中提取查询
        queries = []
        if response and response.tool_calls and len(response.tool_calls) > 0:
            tool_call = response.tool_calls[0]
            arguments = json.loads(tool_call.function.arguments)
            queries = arguments.get("follow_up_queries", [])

        # 确保不返回超过3个查询
        return queries[:3]

    async def _analyze_content(
        self, content: str, url: str, title: str, query: str
    ) -> List[ResearchInsight]:
        """基于与查询的相关性分析内容并提取洞见。

        这个方法是内容理解的核心，它使用LLM从原始内容中提取结构化洞见。
        它实现了结构化信息提取和异常处理策略。

        提取策略:
        1. 内容截断: 限制分析内容大小，确保LLM处理效率
        2. 结构化输出: 使用工具调用模式获取格式一致的洞见
        3. 后备机制: 当结构化提取失败时提供替代洞见

        参数:
            content: 要分析的内容文本。
            url: 内容的来源URL。
            title: 内容的标题。
            query: 研究查询。

        返回:
            从内容中提取的洞见列表。
        """
        prompt = EXTRACT_INSIGHTS_PROMPT.format(
            query=query, content=content[:5000]  # 限制内容大小
        )

        response = await self.llm.ask_tool(
            [{"role": "user", "content": prompt}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "extract_insights",
                        "description": "Extract key insights from content with relevance scores",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "insights": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "content": {
                                                "type": "string",
                                                "description": "The insight content",
                                            },
                                            "relevance_score": {
                                                "type": "number",
                                                "description": "Relevance score between 0.0 and 1.0",
                                                "minimum": 0.0,
                                                "maximum": 1.0,
                                            },
                                        },
                                        "required": ["content", "relevance_score"],
                                    },
                                    "description": "List of key insights extracted from the content",
                                    "maxItems": 3,
                                }
                            },
                            "required": ["insights"],
                        },
                    },
                }
            ],
            tool_choice=ToolChoice.REQUIRED,
            stream=False,
        )

        insights = []

        # 处理结构化JSON响应
        if response and response.tool_calls and len(response.tool_calls) > 0:
            tool_call = response.tool_calls[0]
            arguments = json.loads(tool_call.function.arguments)
            extracted_insights = arguments.get("insights", [])

            for insight_data in extracted_insights:
                insights.append(
                    ResearchInsight(
                        content=insight_data.get("content", ""),
                        source_url=url,
                        source_title=title,
                        relevance_score=insight_data.get(
                            "relevance_score", FALLBACK_RELEVANCE_SCORE
                        ),
                    )
                )

        # 后备策略: 如果没有找到结构化洞见，使用后备方法
        if not insights:
            logger.warning(
                f"Could not parse structured insights from LLM response for {url}. Using fallback."
            )
            insights.append(
                ResearchInsight(
                    content=f"Failed to extract structured insights from content about {title or url}."[
                        :FALLBACK_CONTENT_LIMIT
                    ],
                    source_url=url,
                    source_title=title,
                    relevance_score=FALLBACK_RELEVANCE_SCORE,
                )
            )

        return insights


if __name__ == "__main__":
    deep_research = DeepResearch()
    result = asyncio.run(
        deep_research.execute(
            "What is deep learning", max_depth=1, results_per_search=2
        )
    )
    print(result)
