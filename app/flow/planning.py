import json
import time
from enum import Enum
from typing import Dict, List, Optional, Union

from pydantic import Field

from app.agent.base import BaseAgent
from app.flow.base import BaseFlow
from app.llm import LLM
from app.logger import logger
from app.schema import AgentState, Message, ToolChoice
from app.tool import PlanningTool


class PlanStepStatus(str, Enum):
    """
    计划步骤状态枚举

    定义计划中每个步骤可能的状态，继承自str以便于序列化和使用字符串方法。
    这些状态用于跟踪计划执行的进度。
    """

    NOT_STARTED = "not_started"  # 步骤尚未开始
    IN_PROGRESS = "in_progress"  # 步骤正在执行中
    COMPLETED = "completed"  # 步骤已完成
    BLOCKED = "blocked"  # 步骤被阻塞，无法执行

    @classmethod
    def get_all_statuses(cls) -> list[str]:
        """
        获取所有可能的步骤状态值

        @classmethod装饰器使此方法成为类方法，可以通过类直接调用而不需要实例

        返回值:
            包含所有状态值的列表
        """
        return [status.value for status in cls]

    @classmethod
    def get_active_statuses(cls) -> list[str]:
        """
        获取表示活动状态的值列表(未开始或进行中)

        返回值:
            活动状态值列表
        """
        return [cls.NOT_STARTED.value, cls.IN_PROGRESS.value]

    @classmethod
    def get_status_marks(cls) -> Dict[str, str]:
        """
        获取状态到标记符号的映射

        这些符号用于在文本形式展示计划时，直观地表示每个步骤的状态

        返回值:
            状态值到标记符号的字典
        """
        return {
            cls.COMPLETED.value: "[✓]",  # 已完成步骤使用勾号
            cls.IN_PROGRESS.value: "[→]",  # 进行中步骤使用箭头
            cls.BLOCKED.value: "[!]",  # 被阻塞步骤使用感叹号
            cls.NOT_STARTED.value: "[ ]",  # 未开始步骤使用空方括号
        }


class PlanningFlow(BaseFlow):
    """
    计划流程类

    这个类继承自BaseFlow，实现了基于计划的任务执行流程。
    它先创建一个任务计划，然后逐步执行计划中的步骤，同时跟踪执行状态。

    这种流程特别适合:
    1. 需要分解为多个步骤的复杂任务
    2. 需要不同智能体协作的任务
    3. 需要有序执行的任务序列
    """

    # 类属性定义，使用Pydantic的Field
    llm: LLM = Field(default_factory=lambda: LLM())  # 用于创建计划的语言模型
    planning_tool: PlanningTool = Field(default_factory=PlanningTool)  # 计划工具
    executor_keys: List[str] = Field(default_factory=list)  # 执行者智能体的键列表
    active_plan_id: str = Field(
        default_factory=lambda: f"plan_{int(time.time())}"
    )  # 当前活动计划ID，默认使用时间戳
    current_step_index: Optional[int] = None  # 当前执行的步骤索引

    def __init__(
        self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], **data
    ):
        """
        初始化计划流程

        参数:
            agents: 用于流程的智能体，可以是单个智能体、智能体列表或字典
            **data: 额外的配置参数
        """
        # 处理执行者键列表
        if "executors" in data:
            # 如果提供了executors参数，将其转换为executor_keys
            data["executor_keys"] = data.pop("executors")

        # 设置计划ID
        if "plan_id" in data:
            data["active_plan_id"] = data.pop("plan_id")

        # 初始化计划工具
        if "planning_tool" not in data:
            planning_tool = PlanningTool()
            data["planning_tool"] = planning_tool

        # 调用父类的初始化方法
        super().__init__(agents, **data)

        # 如果未指定执行者，使用所有智能体作为执行者
        if not self.executor_keys:
            self.executor_keys = list(self.agents.keys())

    def get_executor(self, step_type: Optional[str] = None) -> BaseAgent:
        """
        获取适合当前步骤的执行者智能体

        这个方法可以根据步骤类型选择最合适的智能体执行特定任务。
        可以在子类中扩展，基于步骤类型/要求选择智能体。

        参数:
            step_type: 步骤类型，可选

        返回值:
            选中的执行者智能体
        """
        # 如果提供了步骤类型且匹配某个智能体键，使用该智能体
        if step_type and step_type in self.agents:
            return self.agents[step_type]

        # 否则使用第一个可用的执行者或回退到主智能体
        for key in self.executor_keys:
            if key in self.agents:
                return self.agents[key]

        # 回退到主智能体
        return self.primary_agent

    async def execute(self, input_text: str) -> str:
        """
        执行计划流程

        这个方法实现了BaseFlow中定义的抽象方法。它根据输入创建初始计划，
        然后逐步执行计划中的步骤，直到所有步骤完成或需要中断执行。

        参数:
            input_text: 用户输入或任务描述

        返回值:
            执行结果的字符串表示

        异常:
            可能引发各种异常，会被捕获并返回错误信息
        """
        try:
            # 检查是否有主智能体
            if not self.primary_agent:
                raise ValueError("No primary agent available")

            # 如果有输入文本，创建初始计划
            if input_text:
                await self._create_initial_plan(input_text)

                # 验证计划是否成功创建
                if self.active_plan_id not in self.planning_tool.plans:
                    logger.error(
                        f"Plan creation failed. Plan ID {self.active_plan_id} not found in planning tool."
                    )
                    return f"Failed to create plan for: {input_text}"

            # 执行计划并收集结果
            result = ""
            while True:
                # 获取当前要执行的步骤
                self.current_step_index, step_info = await self._get_current_step_info()

                # 如果没有更多步骤或计划已完成，退出循环
                if self.current_step_index is None:
                    result += await self._finalize_plan()
                    break

                # 用适当的智能体执行当前步骤
                step_type = step_info.get("type") if step_info else None
                executor = self.get_executor(step_type)
                step_result = await self._execute_step(executor, step_info)
                result += step_result + "\n"

                # 检查智能体是否想要终止执行
                if hasattr(executor, "state") and executor.state == AgentState.FINISHED:
                    break

            return result
        except Exception as e:
            # 捕获并记录任何异常
            logger.error(f"Error in PlanningFlow: {str(e)}")
            return f"Execution failed: {str(e)}"

    async def _create_initial_plan(self, request: str) -> None:
        """
        基于请求创建初始计划

        这个方法使用流程的LLM和PlanningTool创建一个初始任务计划。

        参数:
            request: 用户请求或任务描述
        """
        logger.info(f"Creating initial plan with ID: {self.active_plan_id}")

        # 创建用于计划创建的系统消息
        system_message = Message.system_message(
            "You are a planning assistant. Create a concise, actionable plan with clear steps. "
            "Focus on key milestones rather than detailed sub-steps. "
            "Optimize for clarity and efficiency."
        )

        # 创建包含请求的用户消息
        user_message = Message.user_message(
            f"Create a reasonable plan with clear steps to accomplish the task: {request}"
        )

        # 使用PlanningTool调用LLM
        response = await self.llm.ask_tool(
            messages=[user_message],
            system_msgs=[system_message],
            tools=[self.planning_tool.to_param()],
            tool_choice=ToolChoice.AUTO,
        )

        # 如果存在工具调用，处理它们
        if response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call.function.name == "planning":
                    # 解析参数
                    args = tool_call.function.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse tool arguments: {args}")
                            continue

                    # 确保plan_id正确设置并执行工具
                    args["plan_id"] = self.active_plan_id

                    # 通过ToolCollection执行工具而不是直接执行
                    result = await self.planning_tool.execute(**args)

                    logger.info(f"Plan creation result: {str(result)}")
                    return

        # 如果执行到这里，创建默认计划
        logger.warning("Creating default plan")

        # 使用ToolCollection创建默认计划
        await self.planning_tool.execute(
            **{
                "command": "create",
                "plan_id": self.active_plan_id,
                "title": f"Plan for: {request[:50]}{'...' if len(request) > 50 else ''}",
                "steps": ["Analyze request", "Execute task", "Verify results"],
            }
        )

    async def _get_current_step_info(self) -> tuple[Optional[int], Optional[dict]]:
        """
        获取当前待执行步骤的信息

        这个方法分析计划中的步骤状态，找出第一个未完成的步骤。
        它使用状态跟踪机制来确定哪个步骤应该被执行，同时自动
        将该步骤标记为"进行中"状态。

        返回值:
            元组，包含(步骤索引, 步骤信息字典)
            如果没有找到活动步骤，则返回(None, None)

        工作原理:
        1. 获取当前计划数据
        2. 遍历所有步骤及其状态
        3. 找到第一个"未开始"或"进行中"的步骤
        4. 将其状态更新为"进行中"
        5. 返回步骤信息供执行
        """
        if (
            not self.active_plan_id
            or self.active_plan_id not in self.planning_tool.plans
        ):
            logger.error(f"Plan with ID {self.active_plan_id} not found")
            return None, None

        try:
            # Direct access to plan data from planning tool storage
            plan_data = self.planning_tool.plans[self.active_plan_id]
            steps = plan_data.get("steps", [])
            step_statuses = plan_data.get("step_statuses", [])

            # Find first non-completed step
            for i, step in enumerate(steps):
                if i >= len(step_statuses):
                    status = PlanStepStatus.NOT_STARTED.value
                else:
                    status = step_statuses[i]

                if status in PlanStepStatus.get_active_statuses():
                    # Extract step type/category if available
                    step_info = {"text": step}

                    # Try to extract step type from the text (e.g., [SEARCH] or [CODE])
                    import re

                    type_match = re.search(r"\[([A-Z_]+)\]", step)
                    if type_match:
                        step_info["type"] = type_match.group(1).lower()

                    # Mark current step as in_progress
                    try:
                        await self.planning_tool.execute(
                            command="mark_step",
                            plan_id=self.active_plan_id,
                            step_index=i,
                            step_status=PlanStepStatus.IN_PROGRESS.value,
                        )
                    except Exception as e:
                        logger.warning(f"Error marking step as in_progress: {e}")
                        # Update step status directly if needed
                        if i < len(step_statuses):
                            step_statuses[i] = PlanStepStatus.IN_PROGRESS.value
                        else:
                            while len(step_statuses) < i:
                                step_statuses.append(PlanStepStatus.NOT_STARTED.value)
                            step_statuses.append(PlanStepStatus.IN_PROGRESS.value)

                        plan_data["step_statuses"] = step_statuses

                    return i, step_info

            return None, None  # No active step found

        except Exception as e:
            logger.warning(f"Error finding current step index: {e}")
            return None, None

    async def _execute_step(self, executor: BaseAgent, step_info: dict) -> str:
        """
        使用指定的智能体执行当前步骤

        这个方法是流程执行的核心部分，它负责:
        1. 准备完整的步骤上下文（包括当前计划状态）
        2. 创建给智能体的提示词
        3. 使用智能体执行具体任务
        4. 处理结果并更新步骤状态

        参数:
            executor: 执行步骤的智能体实例
            step_info: 包含步骤详细信息的字典

        返回值:
            步骤执行结果的字符串表示

        这种设计体现了单一职责原则，让不同的智能体专注于执行特定类型的任务，
        而流程则负责协调和状态管理。
        """
        # Prepare context for the agent with current plan status
        plan_status = await self._get_plan_text()
        step_text = step_info.get("text", f"Step {self.current_step_index}")

        # Create a prompt for the agent to execute the current step
        step_prompt = f"""
        CURRENT PLAN STATUS:
        {plan_status}

        YOUR CURRENT TASK:
        You are now working on step {self.current_step_index}: "{step_text}"

        Please execute this step using the appropriate tools. When you're done, provide a summary of what you accomplished.
        """

        # Use agent.run() to execute the step
        try:
            step_result = await executor.run(step_prompt)

            # Mark the step as completed after successful execution
            await self._mark_step_completed()

            return step_result
        except Exception as e:
            logger.error(f"Error executing step {self.current_step_index}: {e}")
            return f"Error executing step {self.current_step_index}: {str(e)}"

    async def _mark_step_completed(self) -> None:
        """
        将当前步骤标记为已完成

        这个方法更新计划中当前步骤的状态为"已完成"，有两种实现方式:
        1. 主要方式：通过planning_tool执行mark_step命令
        2. 备用方式：直接修改planning_tool内部存储的计划数据

        错误处理策略：
        如果主要方式失败，系统会自动切换到备用方式，确保状态一致性。
        这种设计提高了系统的健壮性，防止因状态更新失败导致流程中断。

        注意：这个方法只有在步骤成功执行后才会被调用，体现了乐观更新策略。
        """
        if self.current_step_index is None:
            return

        try:
            # Mark the step as completed
            await self.planning_tool.execute(
                command="mark_step",
                plan_id=self.active_plan_id,
                step_index=self.current_step_index,
                step_status=PlanStepStatus.COMPLETED.value,
            )
            logger.info(
                f"Marked step {self.current_step_index} as completed in plan {self.active_plan_id}"
            )
        except Exception as e:
            logger.warning(f"Failed to update plan status: {e}")
            # Update step status directly in planning tool storage
            if self.active_plan_id in self.planning_tool.plans:
                plan_data = self.planning_tool.plans[self.active_plan_id]
                step_statuses = plan_data.get("step_statuses", [])

                # Ensure the step_statuses list is long enough
                while len(step_statuses) <= self.current_step_index:
                    step_statuses.append(PlanStepStatus.NOT_STARTED.value)

                # Update the status
                step_statuses[self.current_step_index] = PlanStepStatus.COMPLETED.value
                plan_data["step_statuses"] = step_statuses

    async def _get_plan_text(self) -> str:
        """
        获取格式化的计划文本表示

        这个方法返回当前计划的文本表示，主要用于:
        1. 展示给执行步骤的智能体，提供上下文
        2. 生成最终的计划总结
        3. 监控计划执行进度

        它首先尝试使用planning_tool获取格式化文本，
        如果失败则回退到直接从内部存储生成文本。
        这是一种优雅的降级策略，确保系统稳定性。

        返回值:
            格式化的计划文本，包括标题、进度和步骤详情
        """
        try:
            result = await self.planning_tool.execute(
                command="get", plan_id=self.active_plan_id
            )
            return result.output if hasattr(result, "output") else str(result)
        except Exception as e:
            logger.error(f"Error getting plan: {e}")
            return self._generate_plan_text_from_storage()

    def _generate_plan_text_from_storage(self) -> str:
        """
        直接从存储中生成计划文本的备用方法

        当planning_tool的正常获取方法失败时，此方法从内部存储中
        直接构建计划文本表示。这是一个同步方法（不是异步的），
        因为它只访问内存中已有的数据。

        方法流程:
        1. 从planning_tool的内部存储获取原始计划数据
        2. 计算计划的完成进度和各状态统计
        3. 按照特定格式构建文本表示
        4. 包含每个步骤的状态标记和可能的注释

        返回值:
            格式化的计划文本，如果出错则返回错误信息

        这种备用机制体现了防御性编程原则，提高系统的容错能力。
        """
        try:
            if self.active_plan_id not in self.planning_tool.plans:
                return f"Error: Plan with ID {self.active_plan_id} not found"

            plan_data = self.planning_tool.plans[self.active_plan_id]
            title = plan_data.get("title", "Untitled Plan")
            steps = plan_data.get("steps", [])
            step_statuses = plan_data.get("step_statuses", [])
            step_notes = plan_data.get("step_notes", [])

            # Ensure step_statuses and step_notes match the number of steps
            while len(step_statuses) < len(steps):
                step_statuses.append(PlanStepStatus.NOT_STARTED.value)
            while len(step_notes) < len(steps):
                step_notes.append("")

            # Count steps by status
            status_counts = {status: 0 for status in PlanStepStatus.get_all_statuses()}

            for status in step_statuses:
                if status in status_counts:
                    status_counts[status] += 1

            completed = status_counts[PlanStepStatus.COMPLETED.value]
            total = len(steps)
            progress = (completed / total) * 100 if total > 0 else 0

            plan_text = f"Plan: {title} (ID: {self.active_plan_id})\n"
            plan_text += "=" * len(plan_text) + "\n\n"

            plan_text += (
                f"Progress: {completed}/{total} steps completed ({progress:.1f}%)\n"
            )
            plan_text += f"Status: {status_counts[PlanStepStatus.COMPLETED.value]} completed, {status_counts[PlanStepStatus.IN_PROGRESS.value]} in progress, "
            plan_text += f"{status_counts[PlanStepStatus.BLOCKED.value]} blocked, {status_counts[PlanStepStatus.NOT_STARTED.value]} not started\n\n"
            plan_text += "Steps:\n"

            status_marks = PlanStepStatus.get_status_marks()

            for i, (step, status, notes) in enumerate(
                zip(steps, step_statuses, step_notes)
            ):
                # Use status marks to indicate step status
                status_mark = status_marks.get(
                    status, status_marks[PlanStepStatus.NOT_STARTED.value]
                )

                plan_text += f"{i}. {status_mark} {step}\n"
                if notes:
                    plan_text += f"   Notes: {notes}\n"

            return plan_text
        except Exception as e:
            logger.error(f"Error generating plan text from storage: {e}")
            return f"Error: Unable to retrieve plan with ID {self.active_plan_id}"

    async def _finalize_plan(self) -> str:
        """
        完成计划并生成总结

        当所有步骤完成后，此方法负责:
        1. 获取最终的计划状态
        2. 使用语言模型生成任务总结
        3. 提供执行结果的整体评估

        它使用了两层降级策略:
        1. 首先尝试直接使用flow的LLM生成总结
        2. 如果失败，尝试使用主智能体生成总结
        3. 如果两者都失败，返回简单的完成消息

        这种多层降级机制体现了系统设计中的"优雅失败"原则，
        即使在部分组件失败的情况下，系统仍能提供有用的输出。

        返回值:
            计划总结文本
        """
        plan_text = await self._get_plan_text()

        # Create a summary using the flow's LLM directly
        try:
            system_message = Message.system_message(
                "You are a planning assistant. Your task is to summarize the completed plan."
            )

            user_message = Message.user_message(
                f"The plan has been completed. Here is the final plan status:\n\n{plan_text}\n\nPlease provide a summary of what was accomplished and any final thoughts."
            )

            response = await self.llm.ask(
                messages=[user_message], system_msgs=[system_message]
            )

            return f"Plan completed:\n\n{response}"
        except Exception as e:
            logger.error(f"Error finalizing plan with LLM: {e}")

            # Fallback to using an agent for the summary
            try:
                agent = self.primary_agent
                summary_prompt = f"""
                The plan has been completed. Here is the final plan status:

                {plan_text}

                Please provide a summary of what was accomplished and any final thoughts.
                """
                summary = await agent.run(summary_prompt)
                return f"Plan completed:\n\n{summary}"
            except Exception as e2:
                logger.error(f"Error finalizing plan with agent: {e2}")
                return "Plan completed. Error generating summary."
