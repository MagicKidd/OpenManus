import asyncio
import json
from typing import Any, List, Optional, Union

from pydantic import Field

from app.agent.react import ReActAgent
from app.exceptions import TokenLimitExceeded
from app.logger import logger
from app.prompt.toolcall import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.schema import TOOL_CHOICE_TYPE, AgentState, Message, ToolCall, ToolChoice
from app.tool import CreateChatCompletion, Terminate, ToolCollection

TOOL_CALL_REQUIRED = "Tool calls required but none provided"


class ToolCallAgent(ReActAgent):
    """
    工具调用智能体类

    这个类继承自ReActAgent，专门处理工具/函数调用的智能体。
    智能体(Agent)是一个能够感知环境并采取行动的计算系统。
    """

    # 类属性定义，描述智能体的基本信息
    name: str = "toolcall"  # 智能体名称
    description: str = "an agent that can execute tool calls."  # 智能体描述

    # 提示词模板，用于指导LLM的行为
    system_prompt: str = SYSTEM_PROMPT  # 系统提示词，设定智能体的整体行为
    next_step_prompt: str = (
        NEXT_STEP_PROMPT  # 下一步提示词，用于引导智能体思考下一步行动
    )

    # 可用工具集合，智能体可以调用这些工具完成任务
    available_tools: ToolCollection = ToolCollection(
        CreateChatCompletion(), Terminate()  # 初始化两个基本工具
    )
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.AUTO  # 工具选择模式，AUTO表示自动选择
    # 特殊工具名称列表，这些工具有特殊处理逻辑
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])

    # 实例属性
    tool_calls: List[ToolCall] = Field(default_factory=list)  # 当前工具调用列表
    _current_base64_image: Optional[str] = None  # 存储临时图像数据

    # 执行限制
    max_steps: int = 30  # 最大执行步骤数
    max_observe: Optional[Union[int, bool]] = None  # 观察结果的最大长度

    async def think(self) -> bool:
        """
        思考过程：处理当前状态并使用工具决定下一步行动

        这是智能体的核心思考函数，使用异步方式执行以提高效率
        返回值: 布尔值，表示是否应该继续执行
        """
        # 如果有下一步提示词，添加到消息列表中
        if self.next_step_prompt:
            user_msg = Message.user_message(self.next_step_prompt)
            self.messages += [user_msg]

        try:
            # 使用大语言模型获取带有工具选项的响应
            # await关键字表示这是一个异步调用，允许程序在等待响应时执行其他任务
            response = await self.llm.ask_tool(
                messages=self.messages,  # 传入历史消息
                system_msgs=(  # 系统消息设置
                    [Message.system_message(self.system_prompt)]
                    if self.system_prompt
                    else None
                ),
                tools=self.available_tools.to_params(),  # 传入可用工具参数
                tool_choice=self.tool_choices,  # 工具选择模式
            )
        except ValueError:
            # 直接抛出值错误
            raise
        except Exception as e:
            # 异常处理: 捕获其他所有异常
            # 检查是否为包含TokenLimitExceeded的RetryError
            if hasattr(e, "__cause__") and isinstance(e.__cause__, TokenLimitExceeded):
                token_limit_error = e.__cause__
                # 记录令牌限制错误
                logger.error(
                    f"🚨 Token limit error (from RetryError): {token_limit_error}"
                )
                # 将错误消息添加到记忆中
                self.memory.add_message(
                    Message.assistant_message(
                        f"Maximum token limit reached, cannot continue execution: {str(token_limit_error)}"
                    )
                )
                # 将智能体状态设置为已完成
                self.state = AgentState.FINISHED
                return False  # 返回False表示不应继续执行
            raise  # 重新抛出未处理的异常

        # 提取工具调用和内容
        self.tool_calls = tool_calls = (
            response.tool_calls if response and response.tool_calls else []
        )
        content = response.content if response and response.content else ""

        # 记录响应信息到日志
        logger.info(f"✨ {self.name}'s thoughts: {content}")
        logger.info(
            f"🛠️ {self.name} selected {len(tool_calls) if tool_calls else 0} tools to use"
        )
        if tool_calls:
            logger.info(
                f"🧰 Tools being prepared: {[call.function.name for call in tool_calls]}"
            )
            logger.info(f"🔧 Tool arguments: {tool_calls[0].function.arguments}")

        try:
            # 检查响应是否为空
            if response is None:
                raise RuntimeError("No response received from the LLM")

            # 处理不同的工具选择模式
            # ToolChoice.NONE: 不使用工具，只返回文本内容
            if self.tool_choices == ToolChoice.NONE:
                if tool_calls:
                    logger.warning(
                        f"🤔 Hmm, {self.name} tried to use tools when they weren't available!"
                    )
                if content:
                    self.memory.add_message(Message.assistant_message(content))
                    return True
                return False

            # 创建并添加助手消息到记忆
            assistant_msg = (
                Message.from_tool_calls(content=content, tool_calls=self.tool_calls)
                if self.tool_calls
                else Message.assistant_message(content)
            )
            self.memory.add_message(assistant_msg)

            # ToolChoice.REQUIRED: 要求必须使用工具
            if self.tool_choices == ToolChoice.REQUIRED and not self.tool_calls:
                return True  # 将在act()中处理

            # ToolChoice.AUTO: 自动模式，允许文本或工具调用
            if self.tool_choices == ToolChoice.AUTO and not self.tool_calls:
                return bool(content)  # 如果有内容则继续执行

            return bool(self.tool_calls)  # 返回是否有工具调用
        except Exception as e:
            # 处理思考过程中的异常
            logger.error(f"🚨 Oops! The {self.name}'s thinking process hit a snag: {e}")
            self.memory.add_message(
                Message.assistant_message(
                    f"Error encountered while processing: {str(e)}"
                )
            )
            return False

    async def act(self) -> str:
        """
        行动过程：执行工具调用并处理结果

        这是智能体的核心行动函数，执行由think()函数决定的工具调用
        返回值: 字符串，表示执行结果的汇总
        """
        # 如果没有工具调用
        if not self.tool_calls:
            # 如果工具选择模式为REQUIRED，但没有工具调用，抛出异常
            if self.tool_choices == ToolChoice.REQUIRED:
                raise ValueError(TOOL_CALL_REQUIRED)

            # 如果没有工具调用，返回最后一条消息内容
            return self.messages[-1].content or "No content or commands to execute"

        # 收集所有工具执行结果
        results = []
        for command in self.tool_calls:
            # 每次工具调用前重置base64_image
            self._current_base64_image = None

            # 执行工具调用
            result = await self.execute_tool(command)

            # 如果设置了max_observe，则限制结果长度
            if self.max_observe:
                result = result[: self.max_observe]

            # 记录工具执行结果
            logger.info(
                f"🎯 Tool '{command.function.name}' completed its mission! Result: {result}"
            )

            # 将工具响应添加到记忆中
            tool_msg = Message.tool_message(
                content=result,
                tool_call_id=command.id,
                name=command.function.name,
                base64_image=self._current_base64_image,
            )
            self.memory.add_message(tool_msg)
            results.append(result)

        # 返回所有结果的组合
        return "\n\n".join(results)

    async def execute_tool(self, command: ToolCall) -> str:
        """
        执行单个工具调用并进行错误处理

        参数:
            command: 工具调用对象，包含函数名称和参数
        返回值:
            执行结果字符串
        """
        # 检查命令格式是否有效
        if not command or not command.function or not command.function.name:
            return "Error: Invalid command format"

        # 获取工具名称
        name = command.function.name
        # 检查工具是否可用
        if name not in self.available_tools.tool_map:
            return f"Error: Unknown tool '{name}'"

        try:
            # 解析JSON格式参数
            args = json.loads(command.function.arguments or "{}")

            # 执行工具
            logger.info(f"🔧 Activating tool: '{name}'...")
            result = await self.available_tools.execute(name=name, tool_input=args)

            # 处理特殊工具
            await self._handle_special_tool(name=name, result=result)

            # 检查结果是否包含base64_image
            if hasattr(result, "base64_image") and result.base64_image:
                # 存储base64_image以供后续使用
                self._current_base64_image = result.base64_image

                # 格式化结果用于显示
                observation = (
                    f"Observed output of cmd `{name}` executed:\n{str(result)}"
                    if result
                    else f"Cmd `{name}` completed with no output"
                )
                return observation

            # 格式化标准结果
            observation = (
                f"Observed output of cmd `{name}` executed:\n{str(result)}"
                if result
                else f"Cmd `{name}` completed with no output"
            )

            return observation
        except json.JSONDecodeError:
            # 处理JSON解析错误
            error_msg = f"Error parsing arguments for {name}: Invalid JSON format"
            logger.error(
                f"📝 Oops! The arguments for '{name}' don't make sense - invalid JSON, arguments:{command.function.arguments}"
            )
            return f"Error: {error_msg}"
        except Exception as e:
            # 处理其他所有异常
            error_msg = f"⚠️ Tool '{name}' encountered a problem: {str(e)}"
            logger.exception(error_msg)
            return f"Error: {error_msg}"

    async def _handle_special_tool(self, name: str, result: Any, **kwargs):
        """
        处理特殊工具执行和状态变化

        参数:
            name: 工具名称
            result: 工具执行结果
            **kwargs: 额外参数
        """
        # 检查是否为特殊工具
        if not self._is_special_tool(name):
            return

        # 检查是否应该结束执行
        if self._should_finish_execution(name=name, result=result, **kwargs):
            # 将智能体状态设置为已完成
            logger.info(f"🏁 Special tool '{name}' has completed the task!")
            self.state = AgentState.FINISHED

    @staticmethod
    def _should_finish_execution(**kwargs) -> bool:
        """
        确定工具执行是否应该结束智能体

        这是一个静态方法，不需要访问实例属性
        返回值:
            布尔值，默认为True
        """
        return True

    def _is_special_tool(self, name: str) -> bool:
        """
        检查工具名称是否在特殊工具列表中

        参数:
            name: 工具名称
        返回值:
            布尔值，表示是否为特殊工具
        """
        # 转为小写进行比较，避免大小写差异
        return name.lower() in [n.lower() for n in self.special_tool_names]

    async def cleanup(self):
        """
        清理智能体使用的资源

        这个方法会在智能体执行结束时被调用，确保所有资源正确释放
        """
        logger.info(f"🧹 Cleaning up resources for agent '{self.name}'...")
        # 遍历所有工具并调用它们的cleanup方法
        for tool_name, tool_instance in self.available_tools.tool_map.items():
            # 检查工具是否有cleanup方法且为异步方法
            if hasattr(tool_instance, "cleanup") and asyncio.iscoroutinefunction(
                tool_instance.cleanup
            ):
                try:
                    logger.debug(f"🧼 Cleaning up tool: {tool_name}")
                    await tool_instance.cleanup()
                except Exception as e:
                    logger.error(
                        f"🚨 Error cleaning up tool '{tool_name}': {e}", exc_info=True
                    )
        logger.info(f"✨ Cleanup complete for agent '{self.name}'.")

    async def run(self, request: Optional[str] = None) -> str:
        """
        运行智能体并在完成时进行清理

        参数:
            request: 可选的请求字符串
        返回值:
            执行结果字符串
        """
        try:
            # 调用父类的run方法执行智能体
            return await super().run(request)
        finally:
            # 无论执行成功与否，都确保清理资源
            # finally块确保在所有情况下都会执行清理
            await self.cleanup()
