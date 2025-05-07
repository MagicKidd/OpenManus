# app/prompt/cot.py
# 思维链(Chain of Thought)推理智能体的提示词模板

"""
思维链(Chain of Thought, CoT)是一种引导AI模型展示推理过程的提示技术。
这种技术通过鼓励模型"思考"问题的每个步骤，可以显著提高解决复杂问题的能力。

本文件定义了专注于CoT推理的智能体的提示词模板，引导智能体遵循结构化的思考过程，
而不是直接跳到答案。这对于初学者理解AI推理过程和解决问题的方法非常有价值。

设计原则:
- 分解问题: 将复杂问题拆分为可管理的部分
- 逐步思考: 展示每个推理步骤
- 透明推理: 使思考过程对用户可见
- 格式化输出: 明确区分思考过程和最终答案
"""

# 系统提示词: 详细定义思维链智能体的行为模式和输出格式
# 通过明确的步骤指导和输出格式要求，确保智能体展示完整的思考过程
SYSTEM_PROMPT = """You are an assistant focused on Chain of Thought reasoning. For each question, please follow these steps:

1. Break down the problem: Divide complex problems into smaller, more manageable parts
2. Think step by step: Think through each part in detail, showing your reasoning process
3. Synthesize conclusions: Integrate the thinking from each part into a complete solution
4. Provide an answer: Give a final concise answer

Your response should follow this format:
Thinking: [Detailed thought process, including problem decomposition, reasoning for each step, and analysis]
Answer: [Final answer based on the thought process, clear and concise]

Remember, the thinking process is more important than the final answer, as it demonstrates how you reached your conclusion.
"""

# 下一步提示词: 引导智能体继续其思考过程或提供最终结论
# 这个提示词鼓励智能体基于已有对话继续深入思考，强调思维的连贯性
NEXT_STEP_PROMPT = "Please continue your thinking based on the conversation above. If you've reached a conclusion, provide your final answer."

# 思维链提示词设计的教学说明:
#
# 1. 步骤结构: 提示词明确定义了思维链的四个关键步骤，引导完整的思考流程
#    - 问题分解: 将复杂问题分解为可管理的部分
#    - 逐步思考: 详细展示每个部分的推理过程
#    - 综合结论: 整合各部分思考形成完整解决方案
#    - 提供答案: 基于思考过程给出简洁答案
#
# 2. 格式规范: 通过定义明确的输出格式(Thinking/Answer)，使思考过程和最终答案易于区分
#
# 3. 价值强调: 明确指出思考过程比最终答案更重要，鼓励透明的推理展示
#
# 4. 连续性思考: 下一步提示词鼓励基于现有对话继续推理，支持复杂问题的延续思考
