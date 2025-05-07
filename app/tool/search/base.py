"""
搜索引擎基础模块 (Search Engine Base Module)

这个模块定义了搜索引擎功能的基础数据模型和接口，为所有具体搜索引擎实现提供统一的抽象。
它使用Pydantic模型来确保数据验证和类型安全，同时提供了一个清晰的搜索结果表示结构。

教学点:
1. 抽象接口: 使用抽象基类定义通用接口
2. 数据建模: 使用Pydantic进行数据验证和序列化
3. 继承与多态: 通过继承实现接口多态性
4. 标准化表示: 创建搜索结果的统一表示
5. 类型注解: 使用Python类型提示增强代码可读性和安全性
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class SearchItem(BaseModel):
    """搜索结果项模型。

    这个类表示单个搜索结果，包含标题、URL和可选的描述。
    使用Pydantic模型确保数据验证和类型安全，同时提供清晰的字段描述。

    设计思路:
    1. 数据验证: 使用Pydantic自动验证输入数据
    2. 文档化字段: 使用Field注解提供字段描述
    3. 可选字段: 允许某些字段为空，增加灵活性
    4. 字符串表示: 自定义字符串表示方式，方便打印和日志记录

    属性:
        title: 搜索结果的标题。
        url: 搜索结果的URL链接。
        description: 可选的搜索结果描述或摘要。
    """

    title: str = Field(description="The title of the search result")
    url: str = Field(description="The URL of the search result")
    description: Optional[str] = Field(
        default=None, description="A description or snippet of the search result"
    )

    def __str__(self) -> str:
        """搜索结果项的字符串表示。

        重写默认的字符串表示方法，以简洁格式显示搜索结果的标题和URL。
        这有助于在日志记录和调试时快速识别搜索项。

        返回:
            格式化的搜索结果字符串表示。
        """
        return f"{self.title} - {self.url}"


class WebSearchEngine(BaseModel):
    """Web搜索引擎基类。

    这个抽象基类定义了所有搜索引擎实现必须遵循的标准接口。
    它使用Pydantic模型作为基类，提供数据验证功能，同时定义了执行搜索的抽象方法。

    设计模式:
    1. 模板方法模式: 定义算法骨架，让子类实现具体细节
    2. 策略模式: 允许不同搜索引擎采用不同实现策略
    3. 工厂模式: 可以结合工厂模式创建不同的搜索引擎实例

    模型配置:
        arbitrary_types_allowed: 允许模型包含任意类型的属性，这对于存储复杂对象很有用。
    """

    model_config = {"arbitrary_types_allowed": True}

    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """执行Web搜索并返回结果列表。

        这是搜索引擎的核心抽象方法，所有子类必须实现此方法来提供实际的搜索功能。
        方法定义了统一的搜索接口，包括统一的参数和返回类型。

        设计思路:
        1. 接口统一: 所有搜索引擎使用相同的接口
        2. 参数灵活: 通过*args和**kwargs支持额外参数
        3. 结果标准化: 返回统一的SearchItem列表
        4. 抽象要求: 子类必须实现此方法

        参数:
            query: 要提交给搜索引擎的查询字符串。
            num_results: 要返回的搜索结果数量，默认为10。
            args: 额外的位置参数。
            kwargs: 额外的关键字参数。

        返回:
            匹配搜索查询的SearchItem对象列表。

        异常:
            NotImplementedError: 基类使用此异常表明这是一个必须由子类实现的抽象方法。
        """
        raise NotImplementedError
