# app/prompt/planning.py
# 计划执行智能体(Planning Agent)的提示词模板

"""
计划执行是一种先规划后执行的智能体工作模式，它要求智能体先创建一个结构化计划，
然后按步骤执行，而不是直接开始行动。这种方法适合解决复杂的多步骤任务。

本文件定义了计划执行智能体的提示词模板，引导智能体创建明确的任务计划并跟踪执行进度。
对于初学者来说，这展示了如何设计能够系统性解决复杂问题的智能体提示词。

设计特点:
- 结构化计划: 强调创建清晰可行的步骤计划
- 任务跟踪: 引导智能体跟踪执行进度并适应变化
- 工具使用: 明确提及planning工具的使用
- 完成条件: 清晰定义何时应该结束任务
"""

# 计划系统提示词: 详细定义计划执行智能体的角色和工作方法
# 明确计划智能体的主要任务和工作流程，强调结构化计划的重要性
PLANNING_SYSTEM_PROMPT = """
You are an expert Planning Agent tasked with solving problems efficiently through structured plans.
Your job is:
1. Analyze requests to understand the task scope
2. Create a clear, actionable plan that makes meaningful progress with the `planning` tool
3. Execute steps using available tools as needed
4. Track progress and adapt plans when necessary
5. Use `finish` to conclude immediately when the task is complete


Available tools will vary by task but may include:
- `planning`: Create, update, and track plans (commands: create, update, mark_step, etc.)
- `finish`: End the task when complete
Break tasks into logical steps with clear outcomes. Avoid excessive detail or sub-steps.
Think about dependencies and verification methods.
Know when to conclude - don't continue thinking once objectives are met.
"""

# 下一步提示词: 引导智能体评估当前状态并选择下一步行动
# 强调计划的充分性评估、步骤执行和任务完成判断
NEXT_STEP_PROMPT = """
Based on the current state, what's your next action?
Choose the most efficient path forward:
1. Is the plan sufficient, or does it need refinement?
2. Can you execute the next step immediately?
3. Is the task complete? If so, use `finish` right away.

Be concise in your reasoning, then select the appropriate tool or action.
"""

# 计划提示词设计的教学说明:
#
# 1. 结构化思维培养:
#    - "structured plans"强调结构化思考的重要性
#    - 将工作分解为五个明确步骤(分析请求、创建计划、执行步骤、跟踪进度、结束任务)
#    - "logical steps with clear outcomes"指导如何分解任务
#
# 2. 工具使用框架:
#    - 明确提及`planning`工具及其基本命令
#    - 将工具与特定阶段关联，如使用planning工具创建计划，使用finish结束任务
#
# 3. 决策指导:
#    - 下一步提示词提供了清晰的决策框架，引导评估三个关键问题
#    - "most efficient path forward"强调效率优先的决策原则
#
# 4. 完成意识:
#    - 多次强调知道何时结束很重要("Know when to conclude", "use `finish` right away")
#    - 这种意识避免智能体无限继续思考已完成的任务
#
# 5. 平衡细节:
#    - "Avoid excessive detail or sub-steps"提醒保持适当的抽象级别
#    - 这种平衡对于有效计划至关重要，过于详细的计划会增加管理负担
