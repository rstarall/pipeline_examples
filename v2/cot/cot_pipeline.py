"""
title: Chain of Thought Pipeline
author: open-webui
date: 2024-12-20
version: 1.0
license: MIT
description: 高级思维链推理Pipeline - 支持多种CoT技术、流式输出和智能推理
requirements: requests, pydantic
"""

import os
import json
import requests
import time
from typing import List, Union, Generator, Iterator, Literal
from pydantic import BaseModel, Field
from enum import Enum


class CoTStrategy(Enum):
    """思维链策略枚举"""
    BASIC_COT = "basic_cot"              # 基础思维链
    TREE_OF_THOUGHTS = "tree_of_thoughts" # 树状思维
    SELF_REFLECTION = "self_reflection"   # 自我反思
    REVERSE_CHAIN = "reverse_chain"       # 反向思维链
    MULTI_PERSPECTIVE = "multi_perspective" # 多视角分析
    STEP_BACK = "step_back"              # 步退分析
    ANALOGICAL = "analogical"            # 类比推理
    PLAN = "plan"                        # 计划推理思维


# ================================
# 提示词模板函数 
# ================================

def format_basic_cot_prompt(query: str, context_text: str) -> str:
    """基础思维链模板"""
    base_content = f"""请对以下问题进行逐步深入的分析思考。

待分析问题: {query}"""

    if context_text.strip():
        base_content = f"""请结合对话历史，对以下问题进行逐步深入的分析思考。

相关对话历史:
{context_text}

待分析问题: {query}"""

    return f"""{base_content}

请展现你的逐步推理思维过程：

首先，让我从更深层的角度理解这个问题的背景和用户的真实需求。基于对话历史和问题本身，我需要思考用户为什么会提出这个问题，他们可能遇到了什么具体情境或挑战，以及他们的专业背景和知识层次如何。

然后，让思维沿着逻辑的脉络自然推进，从问题的核心开始，每个想法都自然地引向下一个想法，形成连贯的推理链条。在思考中体现：

• 对用户提问背景和动机的深入分析
• 基于用户角色和专业水平的个性化思考
• 对问题本质的理解和分析
• 从已知信息出发的逻辑推导
• 每一步推理的依据和合理性
• 从简单到复杂的递进式思考
• 对结论的逻辑验证

请使用自然流畅的书面语言进行思考，避免使用分点、编号等结构化格式，让思维过程连贯自然，如同内心的逻辑推理流淌。不要在思考过程中给出总结或结论。

请开始你的逐步推理："""


def format_tree_thoughts_prompt(query: str, context_text: str) -> str:
    """树状思维模板"""
    base_content = f"""请对以下问题进行树状思维分析，探索多个可能的思考方向。

待分析问题: {query}"""

    if context_text.strip():
        base_content = f"""请结合对话历史，对以下问题进行树状思维分析，探索多个可能的思考方向。

相关对话历史:
{context_text}

待分析问题: {query}"""

    return f"""{base_content}

请展现你的树状思维探索过程：

首先，我需要深入理解用户提出这个问题的深层原因。通过分析对话历史和问题表述，我要思考用户可能的身份背景、专业领域、知识水平，以及他们在什么情境下产生了这个疑问。这将帮助我确定应该从哪些角度和深度来探索问题。

面对问题时让思维自然地探索不同的可能方向，在各种思路间游走比较，深入探索最有价值的方向。在思考中体现：

• 对用户提问动机和背景情境的多维度分析
• 基于用户角色特征的差异化思考路径
• 识别问题的多个可能维度
• 探索不同的解决路径和角度  
• 比较各种思路的优缺点
• 深入挖掘最有希望的方向
• 在不同分支间建立联系

请使用自然流畅的书面语言进行思考，避免使用分点、编号等结构化格式。让思维在不同可能性之间自然流转，体现探索式的思考过程。不要在思考过程中给出总结或结论。

请开始你的树状思维探索："""


def format_self_reflection_prompt(query: str, context_text: str) -> str:
    """自我反思模板"""
    base_content = f"""请对以下问题进行深入的自我反思式分析。

待分析问题: {query}"""

    if context_text.strip():
        base_content = f"""请结合对话历史，对以下问题进行深入的自我反思式分析。

相关对话历史:
{context_text}

待分析问题: {query}"""

    return f"""{base_content}

请展现你的自我反思思维过程：

让我首先反思用户为什么会在此时提出这样的问题。结合对话历史，我需要思考用户可能的困惑点在哪里，他们的专业背景如何，以及他们期望获得什么层次的答案。这种对用户动机和身份的深入理解，将指导我如何进行更有针对性的分析。

在思考过程中自然地对自己的想法进行审视，对可能的疏漏或错误保持敏感，让思维在自我质疑和验证中不断完善。在思考中体现：

• 对用户提问意图和专业背景的反思性分析
• 基于用户特征调整思考深度和角度
• 对初始想法的批判性审视
• 识别可能的认知偏误和盲点
• 从不同角度验证推理的合理性
• 质疑假设和前提的正确性
• 在反思中深化和修正理解

请使用自然流畅的书面语言进行思考，避免使用分点、编号等结构化格式。让思维在质疑、验证、修正中自然展开，体现反思性的深度思考。不要在思考过程中给出总结或结论。

请开始你的自我反思："""


def format_reverse_chain_prompt(query: str, context_text: str) -> str:
    """反向思维链模板"""
    base_content = f"""请对以下问题进行反向推理分析。

待分析问题: {query}"""

    if context_text.strip():
        base_content = f"""请结合对话历史，对以下问题进行反向推理分析。

相关对话历史:
{context_text}

待分析问题: {query}"""

    return f"""{base_content}

请展现你的反向推理思维过程：

在开始反向推理之前，让我先深入分析用户提出这个问题的真实需求。通过观察对话历史中的细节，我需要判断用户的专业水平、领域背景，以及他们希望通过这个问题解决什么实际困难。这种对用户动机的理解将帮助我确定合适的目标设定和推理深度。

从想要达到的目标或理想结果开始思考，自然地追溯实现这个目标需要什么条件，层层递推地构建起通向目标的思维路径。在思考中体现：

• 基于用户背景和需求的目标重新定义
• 考虑用户专业水平的个性化路径设计
• 明确理想的结果或解决方案
• 倒推实现目标所需的直接条件
• 逐层分析每个条件的前置要求
• 识别关键的节点和依赖关系
• 构建从现状到目标的完整路径

请使用自然流畅的书面语言进行思考，避免使用分点、编号等结构化格式。让思维从目标出发向起点自然回溯，体现逆向工程的思考过程。不要在思考过程中给出总结或结论。

请开始你的反向推理："""


def format_multi_perspective_prompt(query: str, context_text: str) -> str:
    """多视角分析模板"""
    base_content = f"""请对以下问题进行多视角深度分析。

待分析问题: {query}"""

    if context_text.strip():
        base_content = f"""请结合对话历史，对以下问题进行多视角深度分析。

相关对话历史:
{context_text}

待分析问题: {query}"""

    return f"""{base_content}

请展现你的多视角分析思维过程：

在进行多视角分析前，我首先要理解用户提问的深层背景。通过分析对话历史，我需要推断用户可能的职业角色、专业领域、经验水平，以及他们在什么具体情境中遇到了这个问题。这种对用户身份的洞察将指导我选择最相关的视角进行分析。

让思维自然地从不同的角度去审视问题，设身处地考虑各方的立场和观点，在多重视角的交织中形成更全面的理解。在思考中体现：

• 基于用户角色特征选择相关分析视角
• 结合用户专业背景调整分析深度
• 从不同利益相关者的角度思考
• 考虑短期和长期的不同影响
• 分析理论与实际应用的差异
• 权衡各种因素和制约条件
• 在不同观点间寻找平衡和共识

请使用自然流畅的书面语言进行思考，避免使用分点、编号等结构化格式。让思维在不同视角间自然切换，体现全面性和包容性的分析过程。不要在思考过程中给出总结或结论。

请开始你的多视角分析："""


def format_step_back_prompt(query: str, context_text: str) -> str:
    """步退分析模板"""
    base_content = f"""请对以下问题进行步退式深入分析。

待分析问题: {query}"""

    if context_text.strip():
        base_content = f"""请结合对话历史，对以下问题进行步退式深入分析。

相关对话历史:
{context_text}

待分析问题: {query}"""

    return f"""{base_content}

请展现你的步退分析思维过程：

在进行步退分析之前，让我从用户的角度思考这个问题的来源。通过仔细观察对话历史和问题表述，我需要分析用户可能的专业背景、知识结构，以及他们为什么会在这个时候提出这样的问题。这种对用户动机和身份的理解将帮助我确定应该退到什么层次进行宏观分析。

先让思维跳出具体问题的细节，从更宏观的层面去理解问题的本质和背景，然后将这种宏观理解自然地应用到具体问题的分析中。在思考中体现：

• 基于用户特征确定合适的抽象层次
• 结合用户专业水平调整分析深度
• 将具体问题置于更大的背景中理解
• 识别问题背后的根本原理和规律
• 从抽象层面把握问题的本质特征
• 将宏观洞察应用于具体情况
• 在宏观和微观间建立有机联系

请使用自然流畅的书面语言进行思考，避免使用分点、编号等结构化格式。让思维从宏观到微观自然过渡，体现由抽象到具体的分析深化过程。不要在思考过程中给出总结或结论。

请开始你的步退分析："""


def format_analogical_prompt(query: str, context_text: str) -> str:
    """类比推理模板"""
    base_content = f"""请对以下问题进行类比推理分析。

待分析问题: {query}"""

    if context_text.strip():
        base_content = f"""请结合对话历史，对以下问题进行类比推理分析。

相关对话历史:
{context_text}

待分析问题: {query}"""

    return f"""{base_content}

请展现你的类比推理思维过程：

在开始类比推理前，我需要深入理解用户提出这个问题的背景动机。通过分析对话历史，我要判断用户的专业领域、知识基础，以及他们最熟悉的领域或概念。这样我就能选择用户容易理解的类比对象，让推理过程更加贴近用户的认知背景。

让思维自然地联想到相似的情况、案例或现象，通过这些相似性来启发对当前问题的理解，在类比中寻找解决问题的洞察和灵感。在思考中体现：

• 基于用户背景选择合适的类比领域
• 考虑用户知识结构的个性化类比
• 寻找与当前问题结构相似的已知案例
• 分析类比对象的关键特征和模式
• 识别相似性和差异性
• 从成功案例中提取可借鉴的智慧
• 通过类比获得新的理解视角

请使用自然流畅的书面语言进行思考，避免使用分点、编号等结构化格式。让思维在不同领域间自然跳跃联想，体现创造性的类比思考过程。不要在思考过程中给出总结或结论。

请开始你的类比推理："""


def format_plan_prompt(query: str, context_text: str) -> str:
    """计划推理模板 - 允许结构化分点"""
    base_content = f"""请对以下问题制定详细的解决计划。

待解决问题: {query}"""

    if context_text.strip():
        base_content = f"""请结合对话历史，对以下问题制定详细的解决计划。

相关对话历史:
{context_text}

待解决问题: {query}"""

    return f"""{base_content}

请展现你的计划推理思维过程：

在制定计划之前，我首先要深入分析用户提出这个问题的真实需求和背景。通过对话历史，我需要判断用户的专业水平、可用资源、时间约束，以及他们在实施计划时可能面临的具体挑战。基于这种对用户情况的全面了解，我将制定真正适合他们的个性化解决方案。

运用系统性的计划思维，将复杂问题分解为可执行的具体步骤，制定清晰的行动路径和时间安排。在制定计划时请使用结构化的思考方式：

**阶段一：用户需求与背景分析**
- 深入分析用户的专业背景和角色特征
- 理解用户提问的真实动机和期望
- 评估用户的知识水平和执行能力
- 识别用户的具体约束和资源限制

**阶段二：问题分析与目标设定**
- 基于用户特征重新定义问题核心
- 设定符合用户实际情况的具体目标
- 确定适合用户水平的成功标准

**阶段三：资源评估与约束分析** 
- 评估用户可用的资源和工具
- 识别用户可能面临的限制和风险因素
- 分析用户的时间、成本等约束条件

**阶段四：方案设计与步骤规划**
- 设计适合用户背景的解决方案
- 将方案分解为用户可执行的具体步骤
- 确定步骤间的依赖关系和时间顺序

**阶段五：实施策略与监控机制**
- 制定符合用户特点的具体实施策略
- 设计适合用户的进度监控和质量检查机制  
- 基于用户经验准备应对异常情况的备选方案

请按照以上结构化思维框架进行深入的计划思考，可以使用分点、编号等清晰的格式来组织你的思维过程。

请开始你的计划推理："""


# ================================
# 历史会话上下文管理器
# ================================

class HistoryContextManager:
    """历史会话上下文管理器 - 专为思维链优化"""
    
    DEFAULT_HISTORY_TURNS = 3
    
    @classmethod
    def analyze_user_profile(cls, messages: List[dict]) -> dict:
        """分析用户画像和角色特征"""
        if not messages or len(messages) < 2:
            return {
                "role_category": "general_user",
                "expertise_level": "beginner",
                "professional_domains": [],
                "interaction_patterns": [],
                "motivation_indicators": []
            }
        
        user_messages = [msg for msg in messages if msg.get("role") == "user"]
        all_user_text = " ".join([msg.get("content", "") for msg in user_messages])
        
        # 分析专业领域关键词
        technical_domains = {
            "programming": ["代码", "编程", "开发", "软件", "算法", "函数", "bug", "debug", "API", "框架"],
            "business": ["项目", "管理", "战略", "市场", "运营", "团队", "业务", "客户", "方案"],
            "academic": ["研究", "理论", "学术", "论文", "分析", "方法论", "实验", "数据"],
            "design": ["设计", "界面", "用户体验", "UI", "UX", "视觉", "交互", "原型"],
            "finance": ["财务", "投资", "金融", "成本", "收益", "预算", "风险", "资金"],
            "healthcare": ["医疗", "健康", "治疗", "诊断", "病患", "临床", "药物"],
            "education": ["教学", "学习", "课程", "学生", "教育", "培训", "知识传授"]
        }
        
        detected_domains = []
        for domain, keywords in technical_domains.items():
            if any(keyword in all_user_text for keyword in keywords):
                detected_domains.append(domain)
        
        # 分析专业水平
        expertise_indicators = {
            "expert": ["深入", "架构", "底层", "原理", "最佳实践", "优化", "高级"],
            "intermediate": ["如何实现", "具体方法", "步骤", "流程", "经验", "问题解决"],
            "beginner": ["什么是", "怎么", "基础", "入门", "简单", "初学", "不太懂"]
        }
        
        expertise_level = "intermediate"  # 默认中级
        for level, indicators in expertise_indicators.items():
            if any(indicator in all_user_text for indicator in indicators):
                expertise_level = level
                break
        
        # 分析交互模式
        interaction_patterns = []
        if len(user_messages) > 3:
            interaction_patterns.append("engaged_conversation")
        if any("具体" in msg.get("content", "") for msg in user_messages):
            interaction_patterns.append("detail_seeking")
        if any("为什么" in msg.get("content", "") for msg in user_messages):
            interaction_patterns.append("reason_seeking")
        if any("如何" in msg.get("content", "") for msg in user_messages):
            interaction_patterns.append("solution_seeking")
        
        # 分析动机指标
        motivation_indicators = []
        recent_user_text = " ".join([msg.get("content", "") for msg in user_messages[-3:]])
        
        if any(word in recent_user_text for word in ["急", "马上", "快速", "立即"]):
            motivation_indicators.append("urgent_need")
        if any(word in recent_user_text for word in ["学习", "了解", "知识"]):
            motivation_indicators.append("learning_oriented")
        if any(word in recent_user_text for word in ["解决", "问题", "困难", "挑战"]):
            motivation_indicators.append("problem_solving")
        if any(word in recent_user_text for word in ["比较", "选择", "决策"]):
            motivation_indicators.append("decision_making")
        if any(word in recent_user_text for word in ["改进", "优化", "提升"]):
            motivation_indicators.append("improvement_focused")
        
        return {
            "role_category": detected_domains[0] if detected_domains else "general_user",
            "expertise_level": expertise_level,
            "professional_domains": detected_domains,
            "interaction_patterns": interaction_patterns,
            "motivation_indicators": motivation_indicators
        }
    
    @classmethod
    def extract_recent_context(cls, messages: List[dict], max_turns: int = None) -> str:
        """提取最近的历史会话上下文"""
        if not messages or len(messages) < 2:
            return ""
            
        max_turns = max_turns or cls.DEFAULT_HISTORY_TURNS
        max_messages = max_turns * 2
        
        recent_messages = messages[-max_messages:] if len(messages) > max_messages else messages
        context_text = ""
        
        for msg in recent_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                context_text += f"用户问题: {content}\n"
            elif role == "assistant":
                # 提取思维过程和最终答案
                if "🤔 **思维过程**:" in content:
                    thinking_part = content.split("🤔 **思维过程**:")[1].split("📝 **最终答案**:")[0].strip()
                    final_part = content.split("📝 **最终答案**:")[1].strip() if "📝 **最终答案**:" in content else ""
                    context_text += f"助手思考: {thinking_part[:200]}...\n"
                    context_text += f"助手回答: {final_part[:200]}...\n"
                else:
                    context_text += f"助手: {content[:300]}...\n"
                
        return context_text.strip()

    @classmethod
    def format_thinking_prompt(cls, 
                             query: str, 
                             messages: List[dict], 
                             strategy: CoTStrategy,
                             max_turns: int = None) -> str:
        """根据策略格式化思维链生成提示"""
        context_text = cls.extract_recent_context(messages, max_turns)
        
        # 根据不同策略调用对应的模板函数
        strategy_templates = {
            CoTStrategy.BASIC_COT: format_basic_cot_prompt,
            CoTStrategy.TREE_OF_THOUGHTS: format_tree_thoughts_prompt,
            CoTStrategy.SELF_REFLECTION: format_self_reflection_prompt,
            CoTStrategy.REVERSE_CHAIN: format_reverse_chain_prompt,
            CoTStrategy.MULTI_PERSPECTIVE: format_multi_perspective_prompt,
            CoTStrategy.STEP_BACK: format_step_back_prompt,
            CoTStrategy.ANALOGICAL: format_analogical_prompt,
            CoTStrategy.PLAN: format_plan_prompt
        }
        
        template_func = strategy_templates.get(strategy, format_basic_cot_prompt)
        return template_func(query, context_text)

    @classmethod
    def format_answer_prompt(cls,
                           query: str,
                           thinking_process: str,
                           messages: List[dict],
                           max_turns: int = None) -> str:
        """格式化最终答案生成提示"""
        context_text = cls.extract_recent_context(messages, max_turns)
        user_profile = cls.analyze_user_profile(messages)
        
        # 根据用户画像调整回答风格
        role_descriptions = {
            "programming": "技术开发人员",
            "business": "商业管理人员", 
            "academic": "学术研究人员",
            "design": "设计专业人员",
            "finance": "金融从业人员",
            "healthcare": "医疗健康从业者",
            "education": "教育工作者",
            "general_user": "一般用户"
        }
        
        expertise_descriptions = {
            "expert": "具有深厚专业基础的高级用户",
            "intermediate": "具有一定经验的中级用户", 
            "beginner": "初学者或新手用户"
        }
        
        user_role = role_descriptions.get(user_profile["role_category"], "一般用户")
        user_level = expertise_descriptions.get(user_profile["expertise_level"], "具有一定经验的中级用户")
        
        prompt_content = f"""请基于以下分析过程，为{user_role}({user_level})生成专业、准确的最终答案。

用户画像分析:
- 角色类型: {user_role}
- 专业水平: {user_level}
- 专业领域: {', '.join(user_profile['professional_domains']) if user_profile['professional_domains'] else '通用领域'}
- 交互特征: {', '.join(user_profile['interaction_patterns']) if user_profile['interaction_patterns'] else '标准交互'}
- 需求动机: {', '.join(user_profile['motivation_indicators']) if user_profile['motivation_indicators'] else '一般咨询'}

分析过程:
{thinking_process}

原始问题: {query}"""

        if context_text.strip():
            prompt_content = f"""请基于对话历史和分析过程，为{user_role}({user_level})生成专业、准确的最终答案。

相关对话历史:
{context_text}

用户画像分析:
- 角色类型: {user_role}
- 专业水平: {user_level}
- 专业领域: {', '.join(user_profile['professional_domains']) if user_profile['professional_domains'] else '通用领域'}
- 交互特征: {', '.join(user_profile['interaction_patterns']) if user_profile['interaction_patterns'] else '标准交互'}
- 需求动机: {', '.join(user_profile['motivation_indicators']) if user_profile['motivation_indicators'] else '一般咨询'}

分析过程:
{thinking_process}

原始问题: {query}"""

        # 根据用户水平调整回答要求
        if user_profile["expertise_level"] == "expert":
            answer_requirements = """
请基于上述分析过程提供高级专业的最终答案：
1. 提供深入的技术细节和底层原理分析
2. 包含高级概念、最佳实践和优化建议
3. 讨论相关的前沿发展和未来趋势
4. 提供具体的实现方案和架构建议
5. 如果涉及多种解决方案，请详细比较各自的优缺点
6. 使用专业术语，确保技术准确性和权威性"""
        elif user_profile["expertise_level"] == "beginner":
            answer_requirements = """
请基于上述分析过程提供易于理解的最终答案：
1. 使用简单明了的语言，避免过多专业术语
2. 提供基础概念的解释和背景介绍
3. 给出具体的步骤指导和操作建议
4. 包含实用的示例和类比说明
5. 提供进一步学习的方向和资源建议
6. 确保内容循序渐进，便于初学者掌握"""
        else:  # intermediate
            answer_requirements = """
请基于上述分析过程提供专业实用的最终答案：
1. 综合分析过程中的关键洞察和结论
2. 提供结构清晰、逻辑严密的专业回答
3. 包含适度的技术细节和实践指导
4. 给出具体的解决方案和实施建议
5. 平衡理论分析与实际应用
6. 如果分析中涉及多个可能性，请明确说明各自的适用条件"""

        prompt_content += answer_requirements

        prompt_content += """

请直接提供最终答案，使用专业规范且适合目标用户水平的表达方式。"""

        return prompt_content


# ================================
# Pipeline主体类
# ================================

class Pipeline:
    class Valves(BaseModel):
        # OpenAI API配置
        OPENAI_API_KEY: str
        OPENAI_BASE_URL: str
        OPENAI_MODEL: str
        OPENAI_TIMEOUT: int
        OPENAI_MAX_TOKENS: int
        OPENAI_TEMPERATURE: float

        # 思维链特定配置
        COT_STRATEGY: Literal[
            "basic_cot",
            "tree_of_thoughts", 
            "self_reflection",
            "reverse_chain",
            "multi_perspective",
            "step_back",
            "analogical",
            "plan"
        ] = Field(
            default="basic_cot",
            description="思维链推理策略：basic_cot(基础思维链), tree_of_thoughts(树状思维), self_reflection(自我反思), reverse_chain(反向思维链), multi_perspective(多视角分析), step_back(步退分析), analogical(类比推理), plan(计划推理)"
        )
        THINKING_TEMPERATURE: float
        ANSWER_TEMPERATURE: float
        
        # Pipeline配置
        ENABLE_STREAMING: bool
        DEBUG_MODE: bool
        
        # 历史会话配置
        HISTORY_TURNS: int
        
        # 高级配置
        MAX_THINKING_TOKENS: int
        ENABLE_SELF_CORRECTION: bool
        USE_THINKING_CACHE: bool

    def __init__(self):
        self.name = "Chain of Thought Pipeline"
        # 初始化token统计
        self.token_stats = {
            "thinking_tokens": 0,
            "answer_tokens": 0, 
            "total_tokens": 0
        }
        
        self.valves = self.Valves(
            **{
                # OpenAI配置
                "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
                "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
                "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4o"),
                "OPENAI_TIMEOUT": int(os.getenv("OPENAI_TIMEOUT", "60")),
                "OPENAI_MAX_TOKENS": int(os.getenv("OPENAI_MAX_TOKENS", "4000")),
                "OPENAI_TEMPERATURE": float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
                
                # 思维链特定配置
                "COT_STRATEGY": os.getenv("COT_STRATEGY", "basic_cot"),
                "THINKING_TEMPERATURE": float(os.getenv("THINKING_TEMPERATURE", "0.8")),
                "ANSWER_TEMPERATURE": float(os.getenv("ANSWER_TEMPERATURE", "0.6")),
                
                # Pipeline配置
                "ENABLE_STREAMING": os.getenv("ENABLE_STREAMING", "true").lower() == "true",
                "DEBUG_MODE": os.getenv("DEBUG_MODE", "false").lower() == "true",
                
                # 历史会话配置
                "HISTORY_TURNS": int(os.getenv("HISTORY_TURNS", "3")),
                
                # 高级配置
                "MAX_THINKING_TOKENS": int(os.getenv("MAX_THINKING_TOKENS", "2000")),
                "ENABLE_SELF_CORRECTION": os.getenv("ENABLE_SELF_CORRECTION", "false").lower() == "true",
                "USE_THINKING_CACHE": os.getenv("USE_THINKING_CACHE", "false").lower() == "true",
            }
        )

    async def on_startup(self):
        print(f"思维链推理Pipeline启动: {__name__}")
        
        # 验证必需的API密钥
        if not self.valves.OPENAI_API_KEY:
            print("❌ 缺少OpenAI API密钥，请设置OPENAI_API_KEY环境变量")
            
        # 验证策略配置
        try:
            CoTStrategy(self.valves.COT_STRATEGY)
            print(f"✅ 思维链配置验证成功: 策略={self.valves.COT_STRATEGY}")
        except ValueError as e:
            print(f"❌ 思维链配置错误: {e}")

    async def on_shutdown(self):
        print(f"思维链推理Pipeline关闭: {__name__}")

    def _estimate_tokens(self, text: str) -> int:
        """估算token数量"""
        if not text:
            return 0
        chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        english_text = ''.join(char if not ('\u4e00' <= char <= '\u9fff') else ' ' for char in text)
        english_words = len([word for word in english_text.split() if word.strip()])
        estimated_tokens = chinese_chars + int(english_words * 1.3)
        return max(estimated_tokens, 1)

    def _add_thinking_tokens(self, text: str):
        """添加思维过程token统计"""
        tokens = self._estimate_tokens(text)
        self.token_stats["thinking_tokens"] += tokens
        self.token_stats["total_tokens"] += tokens

    def _add_answer_tokens(self, text: str):
        """添加答案token统计"""
        tokens = self._estimate_tokens(text)
        self.token_stats["answer_tokens"] += tokens
        self.token_stats["total_tokens"] += tokens

    def _reset_token_stats(self):
        """重置token统计"""
        self.token_stats = {
            "thinking_tokens": 0,
            "answer_tokens": 0,
            "total_tokens": 0
        }

    def _get_token_stats(self) -> dict:
        """获取token统计信息"""
        return self.token_stats.copy()

    def _get_strategy(self) -> CoTStrategy:
        """获取当前的策略配置"""
        try:
            strategy = CoTStrategy(self.valves.COT_STRATEGY)
        except ValueError:
            strategy = CoTStrategy.BASIC_COT
        return strategy

    def _stage1_thinking(self, query: str, messages: List[dict], stream: bool = False) -> Union[str, Generator]:
        """阶段1：生成思维链推理过程"""
        if not self.valves.OPENAI_API_KEY:
            return "错误: 未设置OpenAI API密钥"

        strategy = self._get_strategy()
        
        system_prompt = """你是一个专业的AI助手。现在需要对用户的问题进行深度思考。请展现你的思维过程，使用自然流畅的书面语言。

思考要求：
- 使用专业的书面语言，避免口语化表达
- 思考过程要自然连贯，如同专业人士内心的思维流淌
- 针对具体问题深入思考，包含实质性的分析内容
- 思考过程中不要出现总结或结论部分
- 让思维自然展开，体现真实的推理过程

请开始你的深度思考："""

        # 使用历史上下文管理器生成提示
        user_prompt = HistoryContextManager.format_thinking_prompt(
            query=query,
            messages=messages or [],
            strategy=strategy,
            max_turns=self.valves.HISTORY_TURNS
        )

        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": self.valves.MAX_THINKING_TOKENS,
            "temperature": self.valves.THINKING_TEMPERATURE,
            "stream": stream
        }
        
        # 添加输入token统计
        self._add_thinking_tokens(system_prompt)
        self._add_thinking_tokens(user_prompt)
        
        if self.valves.DEBUG_MODE:
            print(f"🤔 生成思维过程 - 策略: {strategy.value}")
            print(f"   模型: {self.valves.OPENAI_MODEL}")
            print(f"   温度: {self.valves.THINKING_TEMPERATURE}")
        
        try:
            if stream:
                for chunk in self._stream_openai_response(url, headers, payload, is_thinking=True):
                    yield chunk
            else:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.valves.OPENAI_TIMEOUT
                )
                response.raise_for_status()
                result = response.json()
                
                thinking = result["choices"][0]["message"]["content"]
                self._add_thinking_tokens(thinking)
                
                if self.valves.DEBUG_MODE:
                    print(f"✅ 思维过程生成完成，长度: {len(thinking)}")
                    
                return thinking

        except Exception as e:
            error_msg = f"思维链生成错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            if stream:
                yield error_msg
            else:
                return error_msg

    def _stage2_answer(self, query: str, thinking_process: str, messages: List[dict], stream: bool = False) -> Union[str, Generator]:
        """阶段2：基于思维链生成最终答案"""
        if not self.valves.OPENAI_API_KEY:
            return "错误: 未设置OpenAI API密钥"
        
        system_prompt = """你是一个专业的AI助手，需要基于前述思维分析过程，为用户提供准确、实用的最终答案。

核心要求：
1. 综合思维分析中的关键洞察和结论
2. 提供结构清晰、逻辑严密的专业回答
3. 确保答案准确性和实用价值，直接回应用户需求
4. 适当提供具体的建议、方案或指导意见
5. 保持客观立场，明确表达任何不确定性或局限性

请使用专业、准确的中文表达，确保语言规范且易于理解。"""

        # 使用历史上下文管理器生成提示
        user_prompt = HistoryContextManager.format_answer_prompt(
            query=query,
            thinking_process=thinking_process,
            messages=messages or [],
            max_turns=self.valves.HISTORY_TURNS
        )

        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": self.valves.OPENAI_MAX_TOKENS,
            "temperature": self.valves.ANSWER_TEMPERATURE,
            "stream": stream
        }
        
        # 添加输入token统计
        self._add_answer_tokens(system_prompt)
        self._add_answer_tokens(user_prompt)
        
        if self.valves.DEBUG_MODE:
            print("📝 生成最终答案")
            print(f"   模型: {self.valves.OPENAI_MODEL}")
            print(f"   温度: {self.valves.ANSWER_TEMPERATURE}")
        
        try:
            if stream:
                for chunk in self._stream_openai_response(url, headers, payload, is_thinking=False):
                    yield chunk
            else:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.valves.OPENAI_TIMEOUT
                )
                response.raise_for_status()
                result = response.json()

                answer = result["choices"][0]["message"]["content"]
                self._add_answer_tokens(answer)

                if self.valves.DEBUG_MODE:
                    print(f"✅ 答案生成完成，长度: {len(answer)}")

                return answer

        except Exception as e:
            error_msg = f"答案生成错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            if stream:
                yield error_msg
            else:
                return error_msg

    def _generate_thinking_details(self, content: str, done: bool = False, duration: float = None) -> str:
        """生成思考内容的 details 标签
        
        实现说明：
        - 流式输出时，每次推送完整的 <details> 块，内容逐步丰富
        - done=false 表示思考进行中，done=true 表示思考完成
        - 思考完成时会包含 duration 属性，显示思考耗时
        - 前端会自动用最新的 details 块覆盖渲染
        
        Args:
            content: 思考内容文本
            done: 是否思考完成
            duration: 思考耗时（秒）
            
        Returns:
            格式化的 details HTML 标签
        """
        done_attr = 'true' if done else 'false'
        duration_attr = f' duration="{int(duration)}"' if duration is not None else ''
        summary_text = f'Thought for {int(duration)} seconds' if done and duration else 'Thinking…'
        
        return f'''<details type="reasoning" done="{done_attr}"{duration_attr}>
    <summary>{summary_text}</summary>
    <p>{content}</p>
</details>'''

    def _stream_thinking_with_details(self, user_message: str, messages: List[dict]) -> Generator:
        """流式生成思考内容，每次输出完整的details块"""
        if not self.valves.OPENAI_API_KEY:
            yield "错误: 未设置OpenAI API密钥"
            return

        strategy = self._get_strategy()
        
        system_prompt = """你是一个专业的AI助手。现在需要对用户的问题进行深度思考。请展现你的思维过程，使用自然流畅的书面语言。

思考要求：
- 使用专业的书面语言，避免口语化表达
- 思考过程要自然连贯，如同专业人士内心的思维流淌
- 针对具体问题深入思考，包含实质性的分析内容
- 思考过程中不要出现总结或结论部分
- 让思维自然展开，体现真实的推理过程

请开始你的深度思考："""

        # 使用历史上下文管理器生成提示
        user_prompt = HistoryContextManager.format_thinking_prompt(
            query=user_message,
            messages=messages or [],
            strategy=strategy,
            max_turns=self.valves.HISTORY_TURNS
        )

        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": self.valves.MAX_THINKING_TOKENS,
            "temperature": self.valves.THINKING_TEMPERATURE,
            "stream": True
        }
        
        # 添加输入token统计
        self._add_thinking_tokens(system_prompt)
        self._add_thinking_tokens(user_prompt)
        
        if self.valves.DEBUG_MODE:
            print(f"🤔 生成思维过程 - 策略: {strategy.value}")
            print(f"   模型: {self.valves.OPENAI_MODEL}")
            print(f"   温度: {self.valves.THINKING_TEMPERATURE}")
        
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=self.valves.OPENAI_TIMEOUT
            )
            response.raise_for_status()
            
            collected_content = ""
            
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            break
                        try:
                            json_data = json.loads(data)
                            delta = json_data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                            if delta:
                                collected_content += delta
                                self._add_thinking_tokens(delta)
                                yield collected_content  # 返回累积的内容
                        except json.JSONDecodeError:
                            pass
            
            if self.valves.DEBUG_MODE:
                print(f"✅ 思维过程流式生成完成，总长度: {len(collected_content)}")
                
        except Exception as e:
            error_msg = f"思维链生成错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            yield error_msg

    def _stream_openai_response(self, url, headers, payload, is_thinking=False):
        """流式处理OpenAI响应"""
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=self.valves.OPENAI_TIMEOUT
            )
            response.raise_for_status()
            
            collected_content = ""
            
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            break
                        try:
                            json_data = json.loads(data)
                            delta = json_data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                            if delta:
                                collected_content += delta
                                if is_thinking:
                                    self._add_thinking_tokens(delta)
                                else:
                                    self._add_answer_tokens(delta)
                                yield delta
                        except json.JSONDecodeError:
                            pass
            
            if self.valves.DEBUG_MODE:
                stage = "思维过程" if is_thinking else "最终答案"
                print(f"✅ {stage}流式生成完成，总长度: {len(collected_content)}")
                
        except Exception as e:
            error_msg = f"OpenAI流式API调用错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            yield error_msg

    def pipe(self, user_message: str, model_id: str, messages: List[dict], body: dict) -> Union[str, Generator, Iterator]:
        """主管道函数，处理用户请求"""
        # 重置token统计
        self._reset_token_stats()

        if self.valves.DEBUG_MODE:
            print(f"💭 用户消息: {user_message}")
            print(f"🔧 模型ID: {model_id}")
            print(f"📜 历史消息数量: {len(messages) if messages else 0}")

        # 验证输入
        if not user_message or not user_message.strip():
            yield "❌ 请输入有效的问题或查询内容"
            return

        strategy = self._get_strategy()
        
        # 阶段1：生成思维链推理过程
        stream_mode = body.get("stream", False) and self.valves.ENABLE_STREAMING
        thinking_content = ""
        
        # 开始计时
        thinking_start_time = time.time()
        
        try:
            if stream_mode:
                # 流式模式 - 思维过程
                # 先推送初始的 details 标签
                yield self._generate_thinking_details("正在分析...", done=False)
                
                for content in self._stream_thinking_with_details(user_message, messages):
                    thinking_content = content
                    # 每次推送完整的 details 块
                    yield self._generate_thinking_details(thinking_content, done=False)
                    
                # 计算思考时长
                thinking_duration = time.time() - thinking_start_time
                # 推送最终的带时长的 details 块
                yield self._generate_thinking_details(thinking_content, done=True, duration=thinking_duration)
            else:
                # 非流式模式 - 思维过程
                # 先推送初始的 details 标签
                yield self._generate_thinking_details("正在分析...", done=False)
                
                thinking_result = self._stage1_thinking(user_message, messages, stream=False)
                thinking_content = thinking_result
                
                # 计算思考时长
                thinking_duration = time.time() - thinking_start_time
                # 推送最终的带时长的 details 块
                yield self._generate_thinking_details(thinking_content, done=True, duration=thinking_duration)
                
        except Exception as e:
            error_msg = f"❌ 思维过程生成错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            yield error_msg
            return

        yield "\n\n"
        
        # 自我纠错（如果启用）
        if self.valves.ENABLE_SELF_CORRECTION and "错误" in thinking_content.lower():
            yield "🔍 **自我纠错**: 检测到可能的错误，正在修正...\n\n"
            # 这里可以添加自我纠错逻辑
        
        # 阶段2：基于思维链生成最终答案
        yield "📝 **最终答案**: \n\n"
        
        try:
            if stream_mode:
                # 流式模式 - 最终答案
                for chunk in self._stage2_answer(user_message, thinking_content, messages, stream=True):
                    yield chunk
                # 流式模式结束后添加token统计
                token_info = self._get_token_stats()
                yield f"\n\n---\n📊 **分析统计**: 思维过程 {token_info['thinking_tokens']} tokens, 最终答案 {token_info['answer_tokens']} tokens, 总计 {token_info['total_tokens']} tokens"
            else:
                # 非流式模式 - 最终答案
                result = self._stage2_answer(user_message, thinking_content, messages, stream=False)
                yield result
                # 添加token统计信息
                token_info = self._get_token_stats()
                yield f"\n\n---\n📊 **分析统计**: 思维过程 {token_info['thinking_tokens']} tokens, 最终答案 {token_info['answer_tokens']} tokens, 总计 {token_info['total_tokens']} tokens"

        except Exception as e:
            error_msg = f"❌ 最终答案生成错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            yield error_msg

        # 提供改进建议
        if self.valves.DEBUG_MODE:
            strategy_suggestions = {
                CoTStrategy.BASIC_COT: "如需更深入分析，可尝试tree_of_thoughts或plan策略",
                CoTStrategy.TREE_OF_THOUGHTS: "如需快速分析，可尝试basic_cot策略", 
                CoTStrategy.SELF_REFLECTION: "如需多角度分析，可尝试multi_perspective策略",
                CoTStrategy.REVERSE_CHAIN: "如需正向推理，可尝试basic_cot策略",
                CoTStrategy.MULTI_PERSPECTIVE: "如需深度反思，可尝试self_reflection策略",
                CoTStrategy.STEP_BACK: "如需具体分析，可尝试basic_cot策略",
                CoTStrategy.ANALOGICAL: "如需逻辑推理，可尝试basic_cot策略",
                CoTStrategy.PLAN: "如需深入思考，可尝试tree_of_thoughts或self_reflection策略"
            }
            
            if strategy in strategy_suggestions:
                yield f"\n\n💡 **优化建议**: {strategy_suggestions[strategy]}"
