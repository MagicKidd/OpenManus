"""
必应搜索引擎模块 (Bing Search Engine Module)

这个模块实现了基于必应搜索引擎的网页搜索功能，通过直接解析HTML结果页面而非API。
它演示了如何使用Web抓取和HTML解析技术构建搜索工具，处理分页和结果提取。

教学点:
1. Web抓取: 使用请求会话和请求头模拟浏览器行为
2. HTML解析: 使用BeautifulSoup提取结构化数据
3. 分页处理: 实现多页结果的抓取和合并
4. 异常处理: 防御式编程处理网络和解析错误
"""

from typing import List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from app.logger import logger
from app.tool.search.base import SearchItem, WebSearchEngine

# 摘要最大长度限制，防止过长文本
ABSTRACT_MAX_LENGTH = 300

# 用户代理字符串列表，模拟不同浏览器，降低被识别为爬虫的可能性
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Ubuntu Chromium/49.0.2623.108 Chrome/49.0.2623.108 Safari/537.36",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; pt-BR) AppleWebKit/533.3 (KHTML, like Gecko) QtWeb Internet Browser/3.7 http://www.QtWeb.net",
    "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US) AppleWebKit/532.2 (KHTML, like Gecko) ChromePlus/4.0.222.3 Chrome/4.0.222.3 Safari/532.2",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.4pre) Gecko/20070404 K-Ninja/2.1.3",
    "Mozilla/5.0 (Future Star Technologies Corp.; Star-Blade OS; x86_64; U; en-US) iNet Browser 4.7",
    "Mozilla/5.0 (Windows; U; Windows NT 6.1; rv:2.2) Gecko/20110201",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.13) Gecko/20080414 Firefox/2.0.0.13 Pogo/2.0.0.13.6866",
]

# HTTP请求头，模拟正常浏览器行为，减少被拦截的可能性
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": USER_AGENTS[0],
    "Referer": "https://www.bing.com/",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 必应搜索的基础URL
BING_HOST_URL = "https://www.bing.com"
BING_SEARCH_URL = "https://www.bing.com/search?q="


class BingSearchEngine(WebSearchEngine):
    """必应搜索引擎实现类。

    这个类提供了基于HTML抓取的必应搜索引擎实现，而非依赖官方API。
    它展示了如何使用请求会话、HTML解析和分页处理来构建实用的搜索工具。

    设计模式:
    1. 会话管理: 使用请求会话维护cookie和连接状态
    2. 策略模式: 作为WebSearchEngine抽象策略的具体实现
    3. 模板方法: 拆分搜索逻辑为多个可重用步骤

    教学要点:
    - HTTP会话管理和请求头配置
    - BeautifulSoup的高效HTML解析
    - 网页抓取的健壮性和错误处理
    """

    session: Optional[requests.Session] = None

    def __init__(self, **data):
        """初始化必应搜索引擎，创建并配置HTTP会话。

        这个方法设置了持久化HTTP会话，配置请求头来模拟浏览器行为。
        它展示了如何初始化需要网络资源的工具。

        参数:
            **data: 传递给父类构造函数的额外数据。
        """
        super().__init__(**data)
        # 创建持久会话，减少连接开销并保持cookie
        self.session = requests.Session()
        # 设置通用请求头，模拟浏览器行为
        self.session.headers.update(HEADERS)

    def _search_sync(self, query: str, num_results: int = 10) -> List[SearchItem]:
        """同步执行必应搜索并处理分页。

        这个方法实现了搜索的核心逻辑，包括查询提交、结果页解析和分页处理。
        它展示了如何处理多页结果以满足请求的结果数量。

        算法设计:
        1. 初始化空结果列表和起始URL
        2. 循环抓取结果页面直到满足数量要求或没有更多结果
        3. 跟踪和增加分页参数(first)
        4. 截断结果到请求的数量

        参数:
            query: 搜索查询字符串。
            num_results: a返回的最大结果数，默认为10。

        返回:
            SearchItem对象列表，包含标题、URL和描述信息。
        """
        if not query:
            return []

        list_result = []
        first = 1  # 必应分页参数，表示结果起始位置
        next_url = BING_SEARCH_URL + query

        # 循环直到收集足够的结果或没有下一页
        while len(list_result) < num_results:
            # 解析当前页并获取下一页URL
            data, next_url = self._parse_html(
                next_url, rank_start=len(list_result), first=first
            )
            if data:
                list_result.extend(data)
            if not next_url:
                break  # 没有更多页面
            first += 10  # 增加必应的分页参数，每页10个结果

        # 确保不超过请求的结果数量
        return list_result[:num_results]

    def _parse_html(
        self, url: str, rank_start: int = 0, first: int = 1
    ) -> Tuple[List[SearchItem], str]:
        """解析必应搜索结果HTML页面。

        这个方法使用BeautifulSoup从HTML中提取搜索结果和下一页URL。
        它展示了如何从复杂的网页结构中定位和提取特定信息。

        实现细节:
        1. 使用CSS选择器定位结果容器和项目
        2. 从每个结果项提取标题、URL和摘要
        3. 处理结果格式和长度限制
        4. 提取"下一页"按钮的URL

        参数:
            url: 要解析的搜索结果页面URL。
            rank_start: 当前结果的起始排名，用于生成后备标题。
            first: 必应分页参数，用于URL构建。

        返回:
            元组: (SearchItem对象列表, 下一页URL或None)
        """
        try:
            # 发送HTTP请求并获取页面内容
            res = self.session.get(url=url)
            res.encoding = "utf-8"  # 确保正确的字符编码
            # 使用lxml解析器创建BeautifulSoup对象，速度更快
            root = BeautifulSoup(res.text, "lxml")

            list_data = []
            # 查找搜索结果列表容器
            ol_results = root.find("ol", id="b_results")
            if not ol_results:
                return [], None  # 没有找到结果容器

            # 遍历每个结果项
            for li in ol_results.find_all("li", class_="b_algo"):
                title = ""
                url = ""
                abstract = ""
                try:
                    # 提取标题和URL
                    h2 = li.find("h2")
                    if h2:
                        title = h2.text.strip()
                        url = h2.a["href"].strip()

                    # 提取摘要/描述
                    p = li.find("p")
                    if p:
                        abstract = p.text.strip()

                    # 限制摘要长度
                    if ABSTRACT_MAX_LENGTH and len(abstract) > ABSTRACT_MAX_LENGTH:
                        abstract = abstract[:ABSTRACT_MAX_LENGTH]

                    rank_start += 1

                    # 创建SearchItem对象并添加到结果列表
                    list_data.append(
                        SearchItem(
                            title=title or f"Bing Result {rank_start}",
                            url=url,
                            description=abstract,
                        )
                    )
                except Exception:
                    # 忽略单个结果项的解析错误，继续处理其他项
                    continue

            # 查找"下一页"按钮并提取URL
            next_btn = root.find("a", title="Next page")
            if not next_btn:
                return list_data, None

            # 构建完整的下一页URL
            next_url = BING_HOST_URL + next_btn["href"]
            return list_data, next_url
        except Exception as e:
            # 记录错误并返回空结果
            logger.warning(f"Error parsing HTML: {e}")
            return [], None

    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """执行必应搜索并返回格式化结果。

        这个方法实现了WebSearchEngine基类的抽象方法，为必应搜索提供统一接口。
        它将内部搜索逻辑与标准接口连接起来。

        参数:
            query: 搜索查询字符串。
            num_results: 要返回的结果数量，默认为10。
            *args, **kwargs: 额外参数，未使用但保留兼容性。

        返回:
            SearchItem对象列表，符合标准格式。
        """
        return self._search_sync(query, num_results=num_results)
