"""
终止工具模块 (Termination Tool Module)

这个模块实现了一个简单但重要的工具，允许智能体明确表示任务的完成或失败，
从而正式结束交互过程。尽管结构简单，但该工具在智能体工作流程中扮演着关键角色。

教学点:
1. 工具简约设计: 最小功能集的工具实现
2. 状态枚举: 使用预定义常量表示任务状态
3. 控制流: 在智能体工作流中实现显式终止点
4. 协议设计: 定义智能体和环境之间的交互边界
"""

from app.tool.base import BaseTool

_TERMINATE_DESCRIPTION = """Terminate the interaction when the request is met OR if the assistant cannot proceed further with the task.
When you have finished all the tasks, call this tool to end the work."""


class Terminate(BaseTool):
    """终止工具类。

    这个工具使智能体能够明确标记任务的完成状态（成功或失败），
    并正式结束当前交互会话。尽管功能简单，但它在智能体工作流中
    扮演着重要角色，确保智能体能够清晰地传达任务结束信号。

    设计理念:
    1. 明确性: 提供明确的终止点，而不是依赖隐式终止
    2. 状态传达: 区分成功完成和失败终止两种情况
    3. 职责单一: 工具只负责终止操作，不处理其他逻辑

    属性:
        name: 工具的名称标识符。
        description: 工具功能的描述文本。
        parameters: 工具参数的JSON Schema定义，定义了状态字段。
    """

    name: str = "terminate"
    description: str = _TERMINATE_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "The finish status of the interaction.",
                "enum": ["success", "failure"],
            }
        },
        "required": ["status"],
    }

    async def execute(self, status: str) -> str:
        """执行终止操作。

        这个方法实现了BaseTool的抽象execute方法，处理终止请求。
        它接受任务状态参数，并返回确认终止的消息。

        参数的使用:
        - status参数使用枚举约束，限制为"success"或"failure"
        - 返回字符串消息而非ToolResult，作为简化设计的例子

        参数:
            status: 终止状态，"success"表示成功完成，"failure"表示失败终止。

        返回:
            包含终止状态的确认消息字符串。
        """
        return f"The interaction has been completed with status: {status}"
