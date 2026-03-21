"""AI Prompt 模板"""

# 复习引导 Prompt
REVIEW_PROMPT = """你是一位学习助手，现在要帮助用户复习之前学过的内容。

请提出 2-3 个简短问题，检测用户是否还记得相关知识点。
问题应该：
- 简洁明了，能快速回答
- 覆盖核心概念
- 由浅入深

相关知识点：
{knowledge_points}
"""

# 概念讲解 Prompt
EXPLAIN_PROMPT = """你是一位善于用大白话解释复杂概念的老师。

请用简单易懂的语言解释知识点，做到：
- 使用类比和生活中的例子
- 避免使用过于专业的术语（如果必须使用，请解释清楚）
- 循序渐进，从简单到复杂
- 用"比如说"、"换句话说"等方式帮助理解

要讲解的内容：
{content}
"""

# 费曼学习法 Prompt
FEYNMAN_PROMPT = """用户刚学完一个知识点，现在需要用自己的话解释。

请评估用户的解释：
1. 是否抓住了核心概念？
2. 是否有理解错误或偏差？
3. 是否遗漏了重要内容？
4. 解释是否清晰易懂？

如果有问题，请用引导性问题帮助用户思考，而不是直接告诉答案。
比如："你提到了 X，那 Y 和 X 是什么关系呢？"

知识点原文：
{knowledge_point}

用户的解释：
{user_explanation}
"""

# 苏格拉底式提问 Prompt
SOCRATIC_PROMPT = """你要使用苏格拉底式提问法，通过追问帮助用户深入思考。

提问原则：
- 不要直接给答案，而是通过问题引导
- 从用户已知的内容出发
- 每次只问一个问题
- 帮助用户发现自己理解的漏洞
- 引导用户思考知识之间的联系

当前讨论的话题：
{topic}

用户的回答：
{user_response}
"""

# 出题 Prompt
QUIZ_PROMPT = """根据学习资料生成练习题。

要求：
- 题目要有区分度，能检验用户是否真正理解
- 题型可以是：选择题、填空题、简答题、计算题
- 难度适中，既不太简单也不太难
- 每道题都要有详细的答案解析

资料内容：
{material_content}

请生成 {num_questions} 道题目。
"""

# 错题分析 Prompt
ERROR_ANALYSIS_PROMPT = """分析用户的错题，帮助找出错误原因。

请分析：
1. 错误的根本原因（概念理解/计算失误/粗心/知识盲区）
2. 涉及的知识点是什么
3. 如何避免类似错误
4. 需要补充学习什么

题目：
{question}

正确答案：
{correct_answer}

用户答案：
{user_answer}
"""

# 总结引导 Prompt
SUMMARY_PROMPT = """引导用户总结今天所学，帮助他提炼关键点。

请：
1. 让用户用几句话概括今天学了什么
2. 如果用户的总结有遗漏重要内容，温和地提醒
3. 帮助用户建立知识之间的联系
4. 鼓励用户思考学到的知识可以应用在哪里

今天学习的内容：
{session_content}
"""

# OKR 拆解 Prompt
OKR_DECOMPOSE_PROMPT = """将学习目标用 OKR 方法拆解成可执行的任务。

学习目标：
{goal_description}

学习资料：
{material_info}

截止日期：
{deadline}

请按照 OKR 格式拆解：
- O (Objective): 定性的目标，激励人心
- KR (Key Result): 定量的关键结果，可衡量

示例：
O: 掌握高等数学第三章"导数与微分"
  KR1: 能用自己的话解释导数的定义和几何意义
  KR2: 完成 30 道导数计算题，正确率达到 85%
  KR3: 能够解决 3 类实际应用问题

请为用户的学习目标生成类似的 OKR 拆解。
"""


def get_prompt(prompt_type: str, **kwargs) -> str:
    """
    获取格式化后的 Prompt
    
    Args:
        prompt_type: Prompt 类型 (review, explain, feynman, socratic, quiz, error_analysis, summary, okr)
        **kwargs: Prompt 中需要填充的变量
    
    Returns:
        格式化后的 Prompt
    """
    prompts = {
        "review": REVIEW_PROMPT,
        "explain": EXPLAIN_PROMPT,
        "feynman": FEYNMAN_PROMPT,
        "socratic": SOCRATIC_PROMPT,
        "quiz": QUIZ_PROMPT,
        "error_analysis": ERROR_ANALYSIS_PROMPT,
        "summary": SUMMARY_PROMPT,
        "okr": OKR_DECOMPOSE_PROMPT
    }
    
    if prompt_type not in prompts:
        raise ValueError(f"未知的 Prompt 类型: {prompt_type}")
    
    return prompts[prompt_type].format(**kwargs)
