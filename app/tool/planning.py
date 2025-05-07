# tool/planning.py

"""
规划工具模块 (Planning Tool Module)

该模块实现了一个规划工具，使智能体能够创建、管理和跟踪完成任务的计划。
规划能力是智能体解决复杂问题的关键，通过将大型任务分解为可管理的步骤。

教学点:
1. 状态管理: 计划和步骤状态的创建、更新和追踪
2. 数据结构: 使用嵌套字典和列表存储层次化信息
3. 命令模式: 基于命令字符串的操作分发
4. 面向对象设计: 单一工具类中封装多种相关功能
5. 用户体验: 格式化输出和状态可视化
"""

from typing import Dict, List, Literal, Optional

from app.exceptions import ToolError
from app.tool.base import BaseTool, ToolResult

_PLANNING_TOOL_DESCRIPTION = """
A planning tool that allows the agent to create and manage plans for solving complex tasks.
The tool provides functionality for creating plans, updating plan steps, and tracking progress.
"""


class PlanningTool(BaseTool):
    """规划工具类。

    这个工具允许智能体创建和管理解决复杂任务的计划，提供创建计划、
    更新步骤和跟踪进度的功能。它展示了如何在一个工具中集成多个相关命令，
    同时维护工具状态。

    设计模式:
    1. 命令模式: 使用命令字符串分发到不同处理方法
    2. 存储库模式: 工具实例作为计划数据的存储库
    3. 状态模式: 计划步骤有明确的状态转换(未开始->进行中->已完成)

    属性:
        name: 工具的名称标识符。
        description: 工具功能说明。
        parameters: 参数定义（JSON Schema格式）。
        plans: 存储所有计划的字典。
        _current_plan_id: 当前活动计划的ID。
    """

    name: str = "planning"
    description: str = _PLANNING_TOOL_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "description": "The command to execute. Available commands: create, update, list, get, set_active, mark_step, delete.",
                "enum": [
                    "create",
                    "update",
                    "list",
                    "get",
                    "set_active",
                    "mark_step",
                    "delete",
                ],
                "type": "string",
            },
            "plan_id": {
                "description": "Unique identifier for the plan. Required for create, update, set_active, and delete commands. Optional for get and mark_step (uses active plan if not specified).",
                "type": "string",
            },
            "title": {
                "description": "Title for the plan. Required for create command, optional for update command.",
                "type": "string",
            },
            "steps": {
                "description": "List of plan steps. Required for create command, optional for update command.",
                "type": "array",
                "items": {"type": "string"},
            },
            "step_index": {
                "description": "Index of the step to update (0-based). Required for mark_step command.",
                "type": "integer",
            },
            "step_status": {
                "description": "Status to set for a step. Used with mark_step command.",
                "enum": ["not_started", "in_progress", "completed", "blocked"],
                "type": "string",
            },
            "step_notes": {
                "description": "Additional notes for a step. Optional for mark_step command.",
                "type": "string",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    plans: dict = {}  # 存储计划的字典
    _current_plan_id: Optional[str] = None  # 跟踪当前活动计划

    async def execute(
        self,
        *,
        command: Literal[
            "create", "update", "list", "get", "set_active", "mark_step", "delete"
        ],
        plan_id: Optional[str] = None,
        title: Optional[str] = None,
        steps: Optional[List[str]] = None,
        step_index: Optional[int] = None,
        step_status: Optional[
            Literal["not_started", "in_progress", "completed", "blocked"]
        ] = None,
        step_notes: Optional[str] = None,
        **kwargs,
    ):
        """执行规划工具命令。

        这个方法是工具的主入口点，使用命令模式将不同操作分派给专门的处理方法。
        它展示了如何以类型安全的方式处理多个命令和参数。

        命令分派模式:
        使用命令字符串决定调用哪个内部方法，将复杂逻辑分离到专用函数中

        类型安全:
        使用Literal类型标注保证命令和状态值只能是预定义的常量

        参数:
            command: 要执行的操作
            plan_id: 计划的唯一标识符
            title: 计划标题
            steps: 计划步骤列表
            step_index: 要更新的步骤索引
            step_status: 步骤状态
            step_notes: 步骤笔记

        返回:
            ToolResult: 操作结果对象

        异常:
            ToolError: 如果命令无效或参数不足
        """

        # 命令路由 - 根据命令字符串调用相应的处理方法
        if command == "create":
            return self._create_plan(plan_id, title, steps)
        elif command == "update":
            return self._update_plan(plan_id, title, steps)
        elif command == "list":
            return self._list_plans()
        elif command == "get":
            return self._get_plan(plan_id)
        elif command == "set_active":
            return self._set_active_plan(plan_id)
        elif command == "mark_step":
            return self._mark_step(plan_id, step_index, step_status, step_notes)
        elif command == "delete":
            return self._delete_plan(plan_id)
        else:
            raise ToolError(
                f"Unrecognized command: {command}. Allowed commands are: create, update, list, get, set_active, mark_step, delete"
            )

    def _create_plan(
        self, plan_id: Optional[str], title: Optional[str], steps: Optional[List[str]]
    ) -> ToolResult:
        """创建新计划。

        这个方法创建一个新的计划，包括计划ID、标题、步骤及其初始状态。
        它展示了参数验证、数据初始化和状态管理的模式。

        实现细节:
        1. 参数验证 - 检查必需参数并验证其类型
        2. 数据结构 - 创建嵌套字典表示计划和其组件
        3. 并行列表 - 使用索引对齐的列表存储步骤及其状态

        参数:
            plan_id: 计划的唯一标识符
            title: 计划标题
            steps: 计划步骤列表

        返回:
            ToolResult: 包含成功消息和格式化计划的结果

        异常:
            ToolError: 如果参数无效或计划ID已存在
        """
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: create")

        if plan_id in self.plans:
            raise ToolError(
                f"A plan with ID '{plan_id}' already exists. Use 'update' to modify existing plans."
            )

        if not title:
            raise ToolError("Parameter `title` is required for command: create")

        if (
            not steps
            or not isinstance(steps, list)
            or not all(isinstance(step, str) for step in steps)
        ):
            raise ToolError(
                "Parameter `steps` must be a non-empty list of strings for command: create"
            )

        # 创建新计划，初始化步骤状态
        plan = {
            "plan_id": plan_id,
            "title": title,
            "steps": steps,
            "step_statuses": ["not_started"] * len(steps),  # 所有步骤初始为未开始
            "step_notes": [""] * len(steps),  # 所有步骤初始无笔记
        }

        self.plans[plan_id] = plan
        self._current_plan_id = plan_id  # 设为活动计划

        return ToolResult(
            output=f"Plan created successfully with ID: {plan_id}\n\n{self._format_plan(plan)}"
        )

    def _update_plan(
        self, plan_id: Optional[str], title: Optional[str], steps: Optional[List[str]]
    ) -> ToolResult:
        """更新现有计划。

        这个方法更新现有计划的标题或步骤，同时保留已完成步骤的状态。
        它展示了如何处理数据更新时的状态保持问题。

        实现技巧:
        1. 部分更新 - 只更新提供了新值的字段
        2. 状态保持 - 在更新步骤时尽量保留原有状态
        3. 结构重建 - 重建步骤状态列表以匹配新步骤

        参数:
            plan_id: 要更新的计划ID
            title: 新的计划标题（可选）
            steps: 新的步骤列表（可选）

        返回:
            ToolResult: 包含更新成功消息和计划的结果

        异常:
            ToolError: 如果计划不存在或参数无效
        """
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: update")

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        plan = self.plans[plan_id]

        # 更新标题（如果提供）
        if title:
            plan["title"] = title

        # 更新步骤（如果提供）
        if steps:
            if not isinstance(steps, list) or not all(
                isinstance(step, str) for step in steps
            ):
                raise ToolError(
                    "Parameter `steps` must be a list of strings for command: update"
                )

            # 保留现有步骤的状态（对于未更改的步骤）
            old_steps = plan["steps"]
            old_statuses = plan["step_statuses"]
            old_notes = plan["step_notes"]

            # 创建新的步骤状态和笔记
            new_statuses = []
            new_notes = []

            for i, step in enumerate(steps):
                # 如果步骤在相同位置未变，保留状态和笔记
                if i < len(old_steps) and step == old_steps[i]:
                    new_statuses.append(old_statuses[i])
                    new_notes.append(old_notes[i])
                else:
                    # 新步骤或位置变化的步骤重置为默认状态
                    new_statuses.append("not_started")
                    new_notes.append("")

            # 更新计划数据
            plan["steps"] = steps
            plan["step_statuses"] = new_statuses
            plan["step_notes"] = new_notes

        return ToolResult(
            output=f"Plan updated successfully: {plan_id}\n\n{self._format_plan(plan)}"
        )

    def _list_plans(self) -> ToolResult:
        """列出所有计划。

        这个方法生成所有现有计划的概览，包括计划ID、标题和完成进度。
        它展示了如何从内部数据结构生成用户友好的格式化输出。

        实现技巧:
        1. 数据聚合 - 从多个计划中收集和汇总信息
        2. 进度计算 - 计算每个计划的完成百分比
        3. 格式化输出 - 创建一致的表格式输出

        返回:
            ToolResult: 包含格式化计划列表的结果
        """
        if not self.plans:
            return ToolResult(
                output="No plans found. Create a plan using the 'create' command."
            )

        lines = ["# Available Plans"]

        for plan_id, plan in self.plans.items():
            # 计算已完成步骤的百分比
            total_steps = len(plan["steps"])
            completed_steps = plan["step_statuses"].count("completed")
            progress_pct = (
                (completed_steps / total_steps) * 100 if total_steps > 0 else 0
            )

            # 标记当前活动计划
            active_marker = " (active)" if plan_id == self._current_plan_id else ""

            lines.append(
                f"- **{plan['title']}** (ID: `{plan_id}`){active_marker}: "
                f"{completed_steps}/{total_steps} steps completed ({progress_pct:.1f}%)"
            )

        return ToolResult(output="\n".join(lines))

    def _get_plan(self, plan_id: Optional[str]) -> ToolResult:
        """获取计划详情。

        这个方法返回特定计划的详细信息，包括所有步骤及其状态。
        如果未指定plan_id，则使用当前活动计划。

        实现技巧:
        1. 默认值处理 - 在缺少输入时使用当前活动计划
        2. 详细格式化 - 为计划创建结构化视图
        3. 错误处理 - 处理计划不存在的情况

        参数:
            plan_id: 要获取的计划ID，如果为None则使用当前活动计划

        返回:
            ToolResult: 包含格式化计划详情的结果

        异常:
            ToolError: 如果未找到指定计划或没有设置活动计划
        """
        # 如果未指定plan_id，使用当前活动计划
        target_id = plan_id or self._current_plan_id

        if not target_id:
            raise ToolError(
                "No plan ID specified and no active plan set. "
                "Specify a plan_id or set an active plan first."
            )

        if target_id not in self.plans:
            raise ToolError(f"Plan with ID '{target_id}' not found.")

        plan = self.plans[target_id]
        return ToolResult(output=self._format_plan(plan))

    def _set_active_plan(self, plan_id: Optional[str]) -> ToolResult:
        """设置活动计划。

        这个方法设置当前的活动计划，简化后续操作无需每次指定计划ID。
        它展示了如何在工具中维护状态以改善用户体验。

        参数:
            plan_id: 要设为活动的计划ID

        返回:
            ToolResult: 包含成功消息的结果

        异常:
            ToolError: 如果未指定plan_id或计划不存在
        """
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: set_active")

        if plan_id not in self.plans:
            raise ToolError(f"Plan with ID '{plan_id}' not found.")

        self._current_plan_id = plan_id
        plan = self.plans[plan_id]

        return ToolResult(
            output=f"Plan '{plan['title']}' (ID: {plan_id}) set as active plan.\n\n{self._format_plan(plan)}"
        )

    def _mark_step(
        self,
        plan_id: Optional[str],
        step_index: Optional[int],
        step_status: Optional[str],
        step_notes: Optional[str],
    ) -> ToolResult:
        """更新计划步骤的状态和笔记。

        这个方法允许智能体标记步骤的状态（未开始、进行中、已完成、阻塞）
        并添加相关笔记。它是计划跟踪功能的核心，体现了状态管理模式。

        实现技巧:
        1. 参数验证 - 确保所有必需参数有效
        2. 状态验证 - 确保状态值为允许的枚举值
        3. 状态转换 - 实现清晰的状态转换规则
        4. 并发更新 - 同时更新状态和笔记

        参数:
            plan_id: 计划ID，如果为None则使用当前活动计划
            step_index: 步骤在列表中的索引（从0开始）
            step_status: 新的状态值
            step_notes: 步骤相关笔记

        返回:
            ToolResult: 包含更新成功消息和计划的结果

        异常:
            ToolError: 如果参数无效或计划不存在
        """
        # 如果未指定plan_id，使用当前活动计划
        target_id = plan_id or self._current_plan_id

        if not target_id:
            raise ToolError(
                "No plan ID specified and no active plan set. "
                "Specify a plan_id or set an active plan first."
            )

        if target_id not in self.plans:
            raise ToolError(f"Plan with ID '{target_id}' not found.")

        if step_index is None:
            raise ToolError("Parameter `step_index` is required for command: mark_step")

        plan = self.plans[target_id]

        # 验证步骤索引
        if not (0 <= step_index < len(plan["steps"])):
            raise ToolError(
                f"Invalid step_index: {step_index}. Index must be between 0 and {len(plan['steps']) - 1} for this plan."
            )

        # 更新步骤状态（如果提供）
        if step_status:
            valid_statuses = ["not_started", "in_progress", "completed", "blocked"]
            if step_status not in valid_statuses:
                raise ToolError(
                    f"Invalid step_status: {step_status}. Status must be one of: {', '.join(valid_statuses)}"
                )

            plan["step_statuses"][step_index] = step_status

        # 更新步骤笔记（如果提供）
        if step_notes is not None:  # 允许空字符串作为有效值（清除笔记）
            plan["step_notes"][step_index] = step_notes

        return ToolResult(
            output=f"Step {step_index} updated successfully in plan '{plan['title']}' (ID: {target_id}).\n\n{self._format_plan(plan)}"
        )

    def _delete_plan(self, plan_id: Optional[str]) -> ToolResult:
        """删除计划。

        这个方法从工具的内部存储中移除指定计划。
        它展示了如何处理资源删除和引用清理的问题。

        实现技巧:
        1. 引用清理 - 处理删除当前活动计划的情况
        2. 资源释放 - 彻底删除相关数据
        3. 状态恢复 - 在删除后重置为合理状态

        参数:
            plan_id: 要删除的计划ID

        返回:
            ToolResult: 包含删除成功消息的结果

        异常:
            ToolError: 如果未指定plan_id或计划不存在
        """
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: delete")

        if plan_id not in self.plans:
            raise ToolError(f"Plan with ID '{plan_id}' not found.")

        plan_title = self.plans[plan_id]["title"]

        # 删除计划
        del self.plans[plan_id]

        # 如果删除的是当前活动计划，重置当前活动计划
        if plan_id == self._current_plan_id:
            self._current_plan_id = (
                next(iter(self.plans.keys())) if self.plans else None
            )

        return ToolResult(
            output=f"Plan '{plan_title}' (ID: {plan_id}) successfully deleted."
        )

    def _format_plan(self, plan: Dict) -> str:
        """格式化计划为可读字符串。

        这个辅助方法将计划数据结构转换为格式化的Markdown文本。
        它展示了如何创建结构化、用户友好的输出。

        实现技巧:
        1. 多级层次 - 使用标题和列表创建视觉层次
        2. 状态可视化 - 使用符号表示不同状态
        3. 详情展开 - 在简洁输出中包含必要详情

        参数:
            plan: 计划数据字典

        返回:
            格式化的Markdown字符串
        """
        # 计算计划进度
        total_steps = len(plan["steps"])
        completed_steps = plan["step_statuses"].count("completed")
        progress_pct = (completed_steps / total_steps) * 100 if total_steps > 0 else 0

        # 格式化计划标题和元数据
        lines = [
            f"# {plan['title']}",
            f"**Plan ID**: `{plan['plan_id']}`",
            f"**Progress**: {completed_steps}/{total_steps} steps completed ({progress_pct:.1f}%)\n",
            "## Steps:",
        ]

        # 为每个步骤添加状态标记和笔记
        for i, (step, status, notes) in enumerate(
            zip(plan["steps"], plan["step_statuses"], plan["step_notes"])
        ):
            # 为不同状态创建不同的标记
            status_marker = {
                "not_started": "[ ]",
                "in_progress": "[🔄]",
                "completed": "[✓]",
                "blocked": "[❌]",
            }.get(status, "[ ]")

            lines.append(f"{i}. {status_marker} **{step}**")

            # 如果有笔记，添加为缩进文本
            if notes:
                lines.append(f"   *Note: {notes}*")

        return "\n".join(lines)
