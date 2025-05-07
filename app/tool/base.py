"""
工具基础类模块 (Tool Base Module)

该模块定义了智能体工具系统的基础抽象类和结果表示类。工具是智能体与外部世界交互的关键组件，
使智能体能够执行各种操作，如执行命令、搜索网络或操作文件等。

教学点:
1. 抽象基类(ABC): 如何使用Python的ABC模块创建接口和抽象类
2. Pydantic模型: 使用Pydantic进行数据验证和模型定义
3. 元编程: 使用类级别的配置和描述性属性
4. 设计模式: 工厂模式和适配器模式的应用
5. 函数式编程: 使用可调用类（__call__方法）
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class BaseTool(ABC, BaseModel):
    """工具基础抽象类。

    所有智能体工具都继承自这个基类，它结合了Python的抽象基类(ABC)和Pydantic的
    BaseModel，提供了类型验证和接口规范。

    设计理念:
    1. 接口一致性: 所有工具遵循相同的接口，便于智能体调用
    2. 声明式定义: 使用类属性声明工具的名称、描述和参数
    3. 元数据驱动: 参数结构使用JSON Schema描述，支持自动验证

    属性:
        name: 工具的名称标识符。
        description: 工具功能的描述文本。
        parameters: 工具参数的JSON Schema定义。
    """

    name: str
    description: str
    parameters: Optional[dict] = None

    class Config:
        """Pydantic配置类。

        允许模型包含任意类型，这对于工具类很重要，因为它们可能包含
        不是普通Python数据类型的属性（如连接、会话等）。
        """

        arbitrary_types_allowed = True

    async def __call__(self, **kwargs) -> Any:
        """执行工具的快捷方法。

        这个方法使工具实例可以像函数一样被调用，是Python双下方法(dunder methods)的
        一个示例。当你看到 tool(arg1=val1, arg2=val2) 这样的代码时，实际上在调用
        这个__call__方法。

        参数:
            **kwargs: 传递给工具execute方法的关键字参数。

        返回:
            工具执行的结果。
        """
        return await self.execute(**kwargs)

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """执行工具的抽象方法。

        这是一个必须由所有子类实现的抽象方法，使用@abstractmethod装饰器确保这一点。
        这种模式强制所有工具类必须提供execute方法的具体实现。

        参数:
            **kwargs: 工具执行需要的关键字参数。

        返回:
            工具执行的结果。
        """

    def to_param(self) -> Dict:
        """将工具转换为函数调用格式。

        这个方法将工具的元数据转换为标准化的字典格式，便于在各种环境中使用，
        特别是当需要将工具描述发送给语言模型时。

        教学点:
        函数式接口 - 将对象表示转换为纯数据结构，便于序列化和传输

        返回:
            包含工具名称、描述和参数的字典。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolResult(BaseModel):
    """工具执行结果的表示类。

    这个类使用Pydantic模型表示工具执行的结果，包括输出、错误和额外信息。
    它为所有工具提供了统一的结果格式，简化了结果处理逻辑。

    设计理念:
    1. 统一接口: 所有工具返回相同结构的结果
    2. 错误处理: 包含专门的错误字段，便于区分成功和失败
    3. 多模态支持: 支持文本和图像等多种输出类型

    属性:
        output: 工具执行的主要输出内容。
        error: 如果执行出错，这里包含错误信息。
        base64_image: 可选的base64编码图像结果(用于视觉输出)。
        system: 可选的系统级消息，通常用于元信息或调试。
    """

    output: Any = Field(default=None)
    error: Optional[str] = Field(default=None)
    base64_image: Optional[str] = Field(default=None)
    system: Optional[str] = Field(default=None)

    class Config:
        """允许模型包含任意类型。"""

        arbitrary_types_allowed = True

    def __bool__(self):
        """布尔转换方法。

        当对ToolResult实例进行布尔评估时调用此方法。
        如果任何字段有值，返回True；否则返回False。

        这是Python特殊方法的一个例子，实现了自定义的真值测试逻辑。

        返回:
            如果结果中有任何内容，则为True，否则为False。
        """
        return any(getattr(self, field) for field in self.__fields__)

    def __add__(self, other: "ToolResult"):
        """加法运算符重载。

        允许结果对象相加，将两个结果的内容合并成一个新结果。
        这是运算符重载的一个例子，为对象定义了"+"操作的含义。

        参数:
            other: 另一个要合并的ToolResult实例。

        返回:
            合并后的新ToolResult实例。

        异常:
            ValueError: 当某些字段不能合并时抛出。
        """

        def combine_fields(
            field: Optional[str], other_field: Optional[str], concatenate: bool = True
        ):
            if field and other_field:
                if concatenate:
                    return field + other_field
                raise ValueError("Cannot combine tool results")
            return field or other_field

        return ToolResult(
            output=combine_fields(self.output, other.output),
            error=combine_fields(self.error, other.error),
            base64_image=combine_fields(self.base64_image, other.base64_image, False),
            system=combine_fields(self.system, other.system),
        )

    def __str__(self):
        """字符串表示方法。

        当对ToolResult实例调用str()函数时调用此方法。
        如果有错误，返回错误信息；否则返回输出内容。

        返回:
            结果的字符串表示。
        """
        return f"Error: {self.error}" if self.error else self.output

    def replace(self, **kwargs):
        """返回具有替换字段的新ToolResult。

        这个方法创建当前结果的副本，但用提供的值替换特定字段。
        这是不可变编程风格的一个例子，而不是直接修改对象，创建新对象。

        参数:
            **kwargs: 要替换的字段及其新值。

        返回:
            更新后的新ToolResult实例。
        """
        return type(self)(**{**self.dict(), **kwargs})


class CLIResult(ToolResult):
    """命令行结果类。

    这是ToolResult的一个特化子类，专门用于表示命令行操作的结果。
    它继承了ToolResult的所有功能，但可以添加CLI特定的行为或字段。

    子类继承是面向对象编程的核心概念，允许代码重用和特化。
    """


class ToolFailure(ToolResult):
    """工具失败结果类。

    这是ToolResult的另一个特化子类，表示工具执行失败的情况。
    尽管目前没有添加额外字段，但它提供了语义上的区分，
    使代码可读性更高（知道是故意表示失败结果）。

    类型的语义分离是良好软件设计的一部分，即使底层实现相似。
    """
