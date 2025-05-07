"""
工具集合模块 (Tool Collection Module)

这个模块实现了工具集合类，用于组织和管理多个工具，提供统一的接口来访问和执行它们。
工具集合是智能体工具系统的关键组织结构，实现了工具的注册、查找和统一调用。

教学点:
1. 组合模式: 将多个对象组合成单一接口的设计模式
2. 动态注册: 在运行时添加和管理组件
3. 映射结构: 使用字典实现名称到对象的高效映射
4. 迭代器协议: 实现Python的迭代器接口
5. 错误处理: 统一处理工具执行中的异常
"""

from typing import Any, Dict, List

from app.exceptions import ToolError
from app.tool.base import BaseTool, ToolFailure, ToolResult


class ToolCollection:
    """工具集合类。

    这个类管理多个工具实例，提供统一的接口来注册、访问和执行它们。
    它实现了组合模式，允许将多个工具作为一个整体对待。

    设计模式:
    1. 组合模式: 将工具组合成集合，提供统一接口
    2. 工厂模式: 通过名称动态创建和访问工具实例
    3. 映射模式: 使用字典实现快速查找

    属性:
        tools: 工具实例的元组，保存所有已注册工具。
        tool_map: 名称到工具实例的映射字典，用于快速查找。
    """

    class Config:
        """Pydantic配置类。

        允许模型包含任意类型，这对于工具集合很重要，因为它包含
        各种工具实例，而这些实例可能有复杂的内部状态。
        """

        arbitrary_types_allowed = True

    def __init__(self, *tools: BaseTool):
        """初始化工具集合。

        创建一个新的工具集合，并注册提供的工具实例。
        这是依赖注入模式的一个例子，工具实例从外部传入而非内部创建。

        参数:
            *tools: 要注册的工具实例，可变参数允许注册任意数量的工具。
        """
        self.tools = tools
        self.tool_map = {tool.name: tool for tool in tools}  # 创建名称到工具的映射

    def __iter__(self):
        """实现迭代器协议。

        使集合可迭代，允许在for循环中直接使用工具集合。
        这是Python特殊方法的一个例子，为对象定义了迭代行为。

        返回:
            工具集合的迭代器，可以按顺序访问每个工具。
        """
        return iter(self.tools)

    def to_params(self) -> List[Dict[str, Any]]:
        """将所有工具转换为参数格式。

        这个方法将集合中的每个工具转换为标准化的参数字典，
        通常用于向语言模型传递工具描述。

        集合转换模式:
        对集合中的每个元素应用相同的转换函数，产生新的集合

        返回:
            包含所有工具参数描述的字典列表。
        """
        return [tool.to_param() for tool in self.tools]

    async def execute(
        self, *, name: str, tool_input: Dict[str, Any] = None
    ) -> ToolResult:
        """执行指定名称的工具。

        这个方法根据名称找到并执行相应的工具，处理可能的错误。
        它是命令模式的一个实现，通过名称来调用不同的工具执行逻辑。

        错误处理策略:
        1. 处理工具不存在的情况
        2. 捕获并转换工具执行时的异常

        参数:
            name: 要执行的工具名称。
            tool_input: 传递给工具的输入参数。

        返回:
            工具执行的结果或失败信息。
        """
        tool = self.tool_map.get(name)
        if not tool:
            return ToolFailure(error=f"Tool {name} is invalid")
        try:
            result = await tool(**tool_input)
            return result
        except ToolError as e:
            return ToolFailure(error=e.message)

    async def execute_all(self) -> List[ToolResult]:
        """顺序执行所有工具。

        这个方法按注册顺序执行集合中的每个工具，并收集所有结果。
        它展示了批处理模式，将相同操作应用于多个对象并收集结果。

        执行策略:
        1. 顺序执行而非并行，避免潜在的资源冲突
        2. 一个工具失败不会阻止其他工具执行
        3. 使用ToolFailure包装异常，保持结果列表的结构一致性

        返回:
            包含所有工具执行结果的列表。
        """
        results = []
        for tool in self.tools:
            try:
                result = await tool()
                results.append(result)
            except ToolError as e:
                results.append(ToolFailure(error=e.message))
        return results

    def get_tool(self, name: str) -> BaseTool:
        """获取指定名称的工具。

        这个方法根据名称查找并返回工具实例，是访问器模式的简单实现。

        参数:
            name: 要获取的工具名称。

        返回:
            对应的工具实例，如果不存在则返回None。
        """
        return self.tool_map.get(name)

    def add_tool(self, tool: BaseTool):
        """添加单个工具到集合。

        这个方法将一个新工具添加到集合中，同时更新工具映射。
        它展示了如何在不可变元组上实现"修改"操作。

        实现细节:
        1. 创建新元组而非修改现有元组（不可变数据模式）
        2. 同步更新tool_map字典
        3. 返回self支持方法链式调用

        参数:
            tool: 要添加的工具实例。

        返回:
            工具集合实例本身，用于链式调用。
        """
        self.tools += (tool,)  # 创建新元组并赋值
        self.tool_map[tool.name] = tool
        return self

    def add_tools(self, *tools: BaseTool):
        """添加多个工具到集合。

        这个方法允许一次添加多个工具，是批量操作的实现示例。
        它利用单个工具添加方法，避免代码重复。

        设计原则:
        1. DRY原则（Don't Repeat Yourself）- 重用add_tool逻辑
        2. 链式方法模式 - 返回self以支持链式调用

        参数:
            *tools: 要添加的工具实例列表，使用可变参数接收任意数量的工具。

        返回:
            工具集合实例本身，用于链式调用。
        """
        for tool in tools:
            self.add_tool(tool)
        return self
