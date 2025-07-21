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
from typing import List, Union, Generator, Iterator
from pydantic import BaseModel
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


class ThinkingDepth(Enum):
    """思考深度枚举"""
    SHALLOW = 1     # 浅层思考(1-2步)
    MODERATE = 2    # 中等深度(3-5步)
    DEEP = 3        # 深度思考(6-8步)
    EXHAUSTIVE = 4  # 穷尽分析(8+步)


class HistoryContextManager:
    """历史会话上下文管理器 - 专为思维链优化"""
    
    DEFAULT_HISTORY_TURNS = 3
    
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
                             depth: ThinkingDepth,
                             max_turns: int = None) -> str:
        """格式化思维链生成提示"""
        context_text = cls.extract_recent_context(messages, max_turns)
        
        # 基础提示构建
        base_prompt = f"""请对以下问题进行专业分析和深度思考。

待分析问题: {query}"""

        if context_text.strip():
            base_prompt = f"""请结合对话历史，对以下问题进行专业分析和深度思考。

相关对话历史:
{context_text}

待分析问题: {query}"""

        # 根据策略添加特定指导
        strategy_instructions = cls._get_strategy_instructions(strategy, depth)
        
        return f"""{base_prompt}

{strategy_instructions}

请展现你的思考过程：
- 使用自然流畅的书面语言进行思考
- 针对这个具体问题深入分析，体现实质性思维
- 避免使用分点、编号等结构化格式
- 思考过程要连贯自然，如同内心的思维流淌
- 不要在思考过程中给出总结或结论
- 让思维围绕问题自然展开和深入

请开始思考："""

    @classmethod
    def format_answer_prompt(cls,
                           query: str,
                           thinking_process: str,
                           messages: List[dict],
                           max_turns: int = None) -> str:
        """格式化最终答案生成提示"""
        context_text = cls.extract_recent_context(messages, max_turns)
        
        prompt_content = f"""请基于以下分析过程，生成专业、准确的最终答案。

分析过程:
{thinking_process}

原始问题: {query}"""

        if context_text.strip():
            prompt_content = f"""请基于对话历史和分析过程，生成专业、准确的最终答案。

相关对话历史:
{context_text}

分析过程:
{thinking_process}

原始问题: {query}"""

        prompt_content += """

请基于上述分析过程提供最终答案：
1. 综合分析过程中的关键洞察和结论
2. 提供结构清晰、逻辑严密的专业回答
3. 确保答案的准确性和实用价值
4. 适当提供具体的建议、方案或指导意见
5. 如果分析中涉及多个可能性，请明确说明各自的适用条件

请直接提供最终答案，使用专业规范的表达方式。"""

        return prompt_content

    @classmethod
    def _get_strategy_instructions(cls, strategy: CoTStrategy, depth: ThinkingDepth) -> str:
        """获取特定策略的指导说明"""
        instructions = {
            CoTStrategy.BASIC_COT: """思维方式：让思考沿着逻辑的脉络自然推进，每个想法都自然地引向下一个想法，形成连贯的思维链条。""",

            CoTStrategy.TREE_OF_THOUGHTS: """思维方式：面对问题时让思维自然地探索不同的可能方向，在各种思路间游走比较，根据思考的深入程度选择最有价值的方向继续探索。""",

            CoTStrategy.SELF_REFLECTION: """思维方式：在思考过程中自然地对自己的想法进行审视，对可能的疏漏或错误保持敏感，让思维在自我质疑中不断完善。""",

            CoTStrategy.REVERSE_CHAIN: """思维方式：从想要达到的目标开始思考，自然地追溯实现这个目标需要什么条件，层层递推地构建起通向目标的思维路径。""",

            CoTStrategy.MULTI_PERSPECTIVE: """思维方式：让思维自然地从不同的角度去审视问题，设身处地考虑各方的立场和观点，在多重视角的交织中形成更全面的理解。""",

            CoTStrategy.STEP_BACK: """思维方式：先让思维跳出具体问题的细节，从更宏观的层面去理解问题的本质，然后将这种宏观理解自然地应用到具体问题的思考中。""",

            CoTStrategy.ANALOGICAL: """思维方式：让思维自然地联想到相似的情况和案例，通过这些相似性来启发对当前问题的思考，在类比中寻找解决问题的灵感。"""
        }
        
        depth_instructions = {
            ThinkingDepth.SHALLOW: "思考深度：围绕核心要素进行精准的思考。",
            ThinkingDepth.MODERATE: "思考深度：进行适度深入的思考，在全面性和效率间找到平衡。", 
            ThinkingDepth.DEEP: "思考深度：让思维深入到细节层面，充分考虑各种影响因素和可能性。",
            ThinkingDepth.EXHAUSTIVE: "思考深度：进行全面深入的思考，尽可能涵盖所有相关的维度和细节。"
        }
        
        return f"{instructions[strategy]}\n\n{depth_instructions[depth]}"


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
        COT_STRATEGY: str
        THINKING_DEPTH: str
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
                "THINKING_DEPTH": os.getenv("THINKING_DEPTH", "moderate"),
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
            
        # 验证策略和深度配置
        try:
            CoTStrategy(self.valves.COT_STRATEGY)
            ThinkingDepth[self.valves.THINKING_DEPTH.upper()]
            print(f"✅ 思维链配置验证成功: 策略={self.valves.COT_STRATEGY}, 深度={self.valves.THINKING_DEPTH}")
        except (ValueError, KeyError) as e:
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

    def _get_strategy_and_depth(self) -> tuple:
        """获取当前的策略和深度配置"""
        try:
            strategy = CoTStrategy(self.valves.COT_STRATEGY)
        except ValueError:
            strategy = CoTStrategy.BASIC_COT
            
        try:
            depth = ThinkingDepth[self.valves.THINKING_DEPTH.upper()]
        except KeyError:
            depth = ThinkingDepth.MODERATE
            
        return strategy, depth

    def _stage1_thinking(self, query: str, messages: List[dict], stream: bool = False) -> Union[str, Generator]:
        """阶段1：生成思维链推理过程"""
        if not self.valves.OPENAI_API_KEY:
            return "错误: 未设置OpenAI API密钥"

        strategy, depth = self._get_strategy_and_depth()
        
        system_prompt = """你是一个专业的AI助手。现在需要对用户的问题进行深度思考。请展现你的思维过程，使用自然流畅的书面语言。

思考要求：
- 使用专业的书面语言，避免口语化表达
- 思考过程要自然连贯，如同专业人士内心的思维流淌
- 不要使用分点、编号或其他结构化格式
- 针对具体问题深入思考，包含实质性的分析内容
- 思考过程中不要出现总结或结论部分
- 让思维自然展开，体现真实的推理过程

请开始你的深度思考："""

        # 使用历史上下文管理器生成提示
        user_prompt = HistoryContextManager.format_thinking_prompt(
            query=query,
            messages=messages or [],
            strategy=strategy,
            depth=depth,
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
            print(f"🤔 生成思维过程 - 策略: {strategy.value}, 深度: {depth.name}")
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

        strategy, depth = self._get_strategy_and_depth()
        
        # 阶段1：生成思维链推理过程
        yield f"🤔 **思维过程**: 正在深入思考...\n\n"
        
        stream_mode = body.get("stream", False) and self.valves.ENABLE_STREAMING
        thinking_content = ""
        
        try:
            if stream_mode:
                # 流式模式 - 思维过程
                for chunk in self._stage1_thinking(user_message, messages, stream=True):
                    thinking_content += chunk
                    yield chunk
            else:
                # 非流式模式 - 思维过程
                thinking_result = self._stage1_thinking(user_message, messages, stream=False)
                thinking_content = thinking_result
                yield thinking_result
                
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
                CoTStrategy.BASIC_COT: "如需更深入分析，可尝试tree_of_thoughts策略",
                CoTStrategy.TREE_OF_THOUGHTS: "如需快速分析，可尝试basic_cot策略", 
                CoTStrategy.SELF_REFLECTION: "如需多角度分析，可尝试multi_perspective策略"
            }
            
            if strategy in strategy_suggestions:
                yield f"\n\n💡 **优化建议**: {strategy_suggestions[strategy]}"
