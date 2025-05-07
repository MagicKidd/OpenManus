"""
聊天完成工具模块 (Chat Completion Tool Module)

这个模块实现了一个用于生成结构化文本输出的工具，允许智能体以指定的格式创建响应。
它使用类型提示和动态生成的JSON Schema来确保输出格式符合预期。

教学点:
1. 类型反射: 使用Python类型提示生成JSON Schema
2. 动态Schema构建: 根据响应类型动态创建参数模式
3. 泛型支持: 使用类型变量支持多种返回类型
4. 参数验证: 确保输入参数的有效性
5. 类型转换: 在不同数据表示之间进行转换
"""

from typing import Any, List, Optional, Type, Union, get_args, get_origin

from pydantic import BaseModel, Field

from app.tool import BaseTool


class CreateChatCompletion(BaseTool):
    """聊天完成工具类。

    这个工具允许智能体生成结构化的输出响应，可以是简单的字符串或复杂的Pydantic模型。
    它通过反射输出类型，自动生成适当的JSON Schema来指导响应格式。

    设计模式:
    1. 工厂模式: 根据输出类型创建不同的参数模式
    2. 类型映射: 将Python类型映射到JSON Schema类型
    3. 动态构建: 在运行时创建模式结构

    属性:
        name: 工具的名称标识符。
        description: 工具功能的描述。
        type_mapping: Python类型到JSON Schema类型的映射字典。
        response_type: 期望的响应类型（可以是str或Pydantic模型）。
        required: 必需参数的列表。
        parameters: 工具参数的JSON Schema定义（动态生成）。
    """

    name: str = "create_chat_completion"
    description: str = (
        "Creates a structured completion with specified output formatting."
    )

    # Type mapping for JSON schema
    type_mapping: dict = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        dict: "object",
        list: "array",
    }
    response_type: Optional[Type] = None
    required: List[str] = Field(default_factory=lambda: ["response"])

    def __init__(self, response_type: Optional[Type] = str):
        """初始化聊天完成工具。

        创建一个带有指定响应类型的工具实例，并生成相应的参数模式。
        这展示了如何基于输入参数动态配置工具行为。

        参数:
            response_type: 期望的响应类型，默认为字符串。
        """
        super().__init__()
        self.response_type = response_type
        self.parameters = self._build_parameters()

    def _build_parameters(self) -> dict:
        """构建参数模式。

        根据响应类型创建JSON Schema参数模式。这是一个工厂方法，
        它根据不同的输入类型生成不同的模式结构。

        工厂设计:
        - 为字符串响应创建简单模式
        - 为Pydantic模型使用其内置的模式生成
        - 为其他类型调用自定义类型模式创建

        返回:
            包含参数模式的字典。
        """
        if self.response_type == str:
            return {
                "type": "object",
                "properties": {
                    "response": {
                        "type": "string",
                        "description": "The response text that should be delivered to the user.",
                    },
                },
                "required": self.required,
            }

        if isinstance(self.response_type, type) and issubclass(
            self.response_type, BaseModel
        ):
            schema = self.response_type.model_json_schema()
            return {
                "type": "object",
                "properties": schema["properties"],
                "required": schema.get("required", self.required),
            }

        return self._create_type_schema(self.response_type)

    def _create_type_schema(self, type_hint: Type) -> dict:
        """为给定类型创建JSON Schema。

        这个方法使用类型反射分析类型提示并生成相应的JSON Schema。
        它处理原始类型、列表、字典和联合类型，展示了如何将Python类型
        系统映射到JSON Schema规范。

        类型处理策略:
        1. 原始类型直接映射到简单Schema
        2. 容器类型（列表、字典）递归处理内部类型
        3. 联合类型使用anyOf组合多个类型模式

        参数:
            type_hint: 要创建Schema的类型提示。

        返回:
            表示类型的JSON Schema字典。
        """
        origin = get_origin(type_hint)
        args = get_args(type_hint)

        # Handle primitive types
        if origin is None:
            return {
                "type": "object",
                "properties": {
                    "response": {
                        "type": self.type_mapping.get(type_hint, "string"),
                        "description": f"Response of type {type_hint.__name__}",
                    }
                },
                "required": self.required,
            }

        # Handle List type
        if origin is list:
            item_type = args[0] if args else Any
            return {
                "type": "object",
                "properties": {
                    "response": {
                        "type": "array",
                        "items": self._get_type_info(item_type),
                    }
                },
                "required": self.required,
            }

        # Handle Dict type
        if origin is dict:
            value_type = args[1] if len(args) > 1 else Any
            return {
                "type": "object",
                "properties": {
                    "response": {
                        "type": "object",
                        "additionalProperties": self._get_type_info(value_type),
                    }
                },
                "required": self.required,
            }

        # Handle Union type
        if origin is Union:
            return self._create_union_schema(args)

        return self._build_parameters()

    def _get_type_info(self, type_hint: Type) -> dict:
        """获取单个类型的类型信息。

        这个辅助方法提取类型提示的元信息，为Schema生成提供类型细节。
        它处理Pydantic模型和基本类型。

        参数:
            type_hint: 要获取信息的类型提示。

        返回:
            包含类型信息的字典。
        """
        if isinstance(type_hint, type) and issubclass(type_hint, BaseModel):
            return type_hint.model_json_schema()

        return {
            "type": self.type_mapping.get(type_hint, "string"),
            "description": f"Value of type {getattr(type_hint, '__name__', 'any')}",
        }

    def _create_union_schema(self, types: tuple) -> dict:
        """为联合类型创建Schema。

        这个方法处理Python的Union类型，在JSON Schema中使用anyOf表示。
        它展示了如何处理复杂的类型联合。

        参数:
            types: 联合类型中的类型元组。

        返回:
            表示联合类型的Schema字典。
        """
        return {
            "type": "object",
            "properties": {
                "response": {"anyOf": [self._get_type_info(t) for t in types]}
            },
            "required": self.required,
        }

    async def execute(self, required: list | None = None, **kwargs) -> Any:
        """执行聊天完成并进行类型转换。

        这个方法实现了BaseTool的抽象execute方法，处理响应数据并根据
        指定的响应类型进行转换。它展示了如何处理动态参数并应用类型转换。

        数据处理流程:
        1. 确定需要的字段列表
        2. 从kwargs提取字段值
        3. 根据响应类型执行类型转换
        4. 返回最终结果

        参数:
            required: 必需字段名称列表或None
            **kwargs: 响应数据

        返回:
            基于response_type转换后的响应
        """
        required = required or self.required

        # Handle case when required is a list
        if isinstance(required, list) and len(required) > 0:
            if len(required) == 1:
                required_field = required[0]
                result = kwargs.get(required_field, "")
            else:
                # Return multiple fields as a dictionary
                return {field: kwargs.get(field, "") for field in required}
        else:
            required_field = "response"
            result = kwargs.get(required_field, "")

        # Type conversion logic
        if self.response_type == str:
            return result

        if isinstance(self.response_type, type) and issubclass(
            self.response_type, BaseModel
        ):
            return self.response_type(**kwargs)

        if get_origin(self.response_type) in (list, dict):
            return result  # Assuming result is already in correct format

        try:
            return self.response_type(result)
        except (ValueError, TypeError):
            return result
