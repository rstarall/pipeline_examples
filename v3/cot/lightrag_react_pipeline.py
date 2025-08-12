"""
title: LightRAG ReAct Pipeline
author: open-webui
date: 2024-12-20
version: 1.0
license: MIT
description: A ReAct-based pipeline for querying LightRAG knowledge base with support for multiple query modes (local, global, hybrid, naive, mix) and conversation history
requirements: requests
"""
import os
import json
import logging
import requests
import asyncio
import time
from typing import List, Union, Generator, Iterator, AsyncGenerator, Dict, Any
from pydantic import BaseModel

# 配置日志记录器
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ===========================================
# ReAct阶段标题映射
# ===========================================

STAGE_TITLES = {
    "reasoning": "🤔 推理分析",
    "action": "🔧 执行检索",
    "observation": "👁️ 观察结果", 
    "answer_generation": "📝 生成答案",
    "lightrag_discovery": "🔍 LightRAG服务发现"
}

STAGE_GROUP = {
    "reasoning": "stage_group_1",
    "action": "stage_group_2", 
    "observation": "stage_group_3",
    "answer_generation": "stage_group_4",
    "lightrag_discovery": "stage_group_0"
}

# ===========================================
# 提示词模板定义
# ===========================================

REASONING_PROMPT = """你是专业的知识检索助手。请首先深入分析用户意图，然后判断是否需要使用LightRAG进行知识检索。

用户当前问题: {user_message}
历史对话上下文: {conversation_context}
已使用的查询词: {used_queries}
已收集的信息摘要: {collected_info_summary}


**LightRAG检索模式选择指南：**
- naive: 快速文档检索，适合简单概念查找
- local: 深挖特定实体，适合需要详细信息的意图  
- global: 关系推理，适合需要理解关联性的意图
- hybrid: 平衡模式，适合中等复杂度问题
- mix: 最全面检索，适合复杂分析和深度理解需求（优先推荐）

回复格式：
```json
{{
    "intent_analysis": "详细分析用户的目的、期望回答类型和深度要求",
    "need_search": true/false,
    "search_query": "基于用户意图和当前问题优化的检索查询",
    "reasoning": "基于用户意图和当前问题分析的检索策略和判断依据",
    "search_mode": "针对用户意图和当前问题选择的最佳检索模式",
    "sufficient_info": true/false
}}
```"""

OBSERVATION_PROMPT = """你是专业的信息分析专家。请基于用户意图分析当前检索结果，判断是否满足用户的真实需求，并制定基于意图的优化检索策略。

用户原始问题: {user_message}
用户意图分析: {intent_analysis}
当前检索查询: {current_query}
检索模式: {search_mode}
检索结果: {search_result}

已收集的历史信息:
{collected_info}

**核心分析任务：**
1. **信息完整性判断**：基于用户期望的回答深度，评估信息是否充分
2. **深度分析判断优化**：基于获取到的信息，进行下一轮检索深度分析优化

**LightRAG检索模式选择指南：**
- naive: 快速文档检索，适合简单概念查找
- local: 深挖特定实体，适合需要详细信息的意图  
- global: 关系推理，适合需要理解关联性的意图
- hybrid: 平衡模式，适合中等复杂度问题
- mix: 最全面检索，适合复杂分析和深度理解需求（优先推荐）

回复格式：
```json
{{
    "relevance_score": 1-10,
    "intent_match_score": 1-10,
    "sufficient_info": true/false,
    "need_more_search": true/false,
    "next_query": "基于已有信息优化的下一轮检索查询",
    "next_mode": "基于已有信息选择的最佳检索模式",
    "optimization_reason": "基于已有信息的查询优化策略和理由",
    "key_information": ["提取的关键信息点"],
    "observation": "基于用户意图的结果分析和下一步策略"
}}
```"""

ANSWER_GENERATION_PROMPT = """请基于用户问题、对话历史、已有的信息，提供针对性的回答。

用户问题: {user_message}
历史对话: {conversation_context}

检索到的相关信息:
{collected_information}


基于你的知识和检索到的信息进行深度分析、思考，然后提供专业、全面、详细的回答"""

class Pipeline:
    class Valves(BaseModel):
        # OpenAI配置
        OPENAI_API_KEY: str
        OPENAI_BASE_URL: str
        OPENAI_MODEL: str
        OPENAI_TIMEOUT: int
        OPENAI_MAX_TOKENS: int
        OPENAI_TEMPERATURE: float

        # LightRAG配置
        LIGHTRAG_BASE_URL: str
        LIGHTRAG_DEFAULT_MODE: str
        LIGHTRAG_TIMEOUT: int

        # Pipeline配置
        ENABLE_STREAMING: bool
        DEBUG_MODE: bool
        MAX_REACT_ITERATIONS: int
        MIN_INFO_THRESHOLD: int

    def __init__(self):
        self.name = "LightRAG ReAct Pipeline"
        
        # 初始化token统计
        self.token_stats = {
            "input_tokens": 0,
            "output_tokens": 0, 
            "total_tokens": 0,
            "api_calls": 0
        }
        
        # ReAct状态管理
        self.react_state = {
            "collected_information": [],  # 存储检索到的信息
            "query_history": [],          # 查询历史
            "used_queries": set(),        # 已使用的查询词
            "current_iteration": 0,       # 当前迭代次数
            "search_modes_used": set(),   # 已使用的搜索模式
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
                
                # LightRAG配置
                "LIGHTRAG_BASE_URL": os.getenv("LIGHTRAG_BASE_URL", "http://117.50.252.245:9621"),
                "LIGHTRAG_DEFAULT_MODE": os.getenv("LIGHTRAG_DEFAULT_MODE", "mix"),
                "LIGHTRAG_TIMEOUT": int(os.getenv("LIGHTRAG_TIMEOUT", "30")),
                
                # Pipeline配置
                "ENABLE_STREAMING": os.getenv("ENABLE_STREAMING", "true").lower() == "true",
                "DEBUG_MODE": os.getenv("DEBUG_MODE", "false").lower() == "true",
                "MAX_REACT_ITERATIONS": int(os.getenv("MAX_REACT_ITERATIONS", "5")),
                "MIN_INFO_THRESHOLD": int(os.getenv("MIN_INFO_THRESHOLD", "3")),
            }
        )

    async def on_startup(self):
        logger.info(f"COT LightRAG ReAct Pipeline启动: {__name__}")
        
        # 验证必需的API密钥
        if not self.valves.OPENAI_API_KEY:
            logger.error("❌ 缺少OpenAI API密钥，请设置OPENAI_API_KEY环境变量")
        
        # 测试LightRAG连接
        try:
            response = requests.get(f"{self.valves.LIGHTRAG_BASE_URL}/health", timeout=5)
            if response.status_code == 200:
                logger.info("✅ LightRAG服务连接成功")
            else:
                logger.warning(f"⚠️ LightRAG服务响应异常: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ 无法连接到LightRAG服务: {e}")

    async def on_shutdown(self):
        logger.info(f"COT LightRAG ReAct Pipeline关闭: {__name__}")

    def _emit_processing(self, content: str, stage: str = "processing" , next_line = True) -> Generator[dict, None, None]:
        """发送处理过程内容"""
        yield {
            'choices': [{
                'delta': {
                    'processing_content': content + ('\n' if next_line else ''),
                    'processing_title': STAGE_TITLES.get(stage, "处理中"),
                    'processing_stage': STAGE_GROUP.get(stage, "stage_group_1")
                },
                'finish_reason': None
            }]
        }

    def _estimate_tokens(self, text: str) -> int:
        """简单的token估算函数"""
        if not text:
            return 0
        # 中文字符按1个token计算，英文单词按平均1.3个token计算
        chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        english_text = ''.join(char if not ('\u4e00' <= char <= '\u9fff') else ' ' for char in text)
        english_words = len([word for word in english_text.split() if word.strip()])
        estimated_tokens = chinese_chars + int(english_words * 1.3)
        return max(estimated_tokens, 1)

    def _add_token_stats(self, input_text: str, output_text: str):
        """添加token统计"""
        input_tokens = self._estimate_tokens(input_text)
        output_tokens = self._estimate_tokens(output_text)
        self.token_stats["input_tokens"] += input_tokens
        self.token_stats["output_tokens"] += output_tokens
        self.token_stats["total_tokens"] += input_tokens + output_tokens
        self.token_stats["api_calls"] += 1

    def _build_conversation_context(self, user_message: str, messages: List[dict]) -> str:
        """构建对话上下文"""
        if not messages or len(messages) <= 1:
            return "无历史对话"
        
        context_parts = []
        recent_messages = messages[-4:] if len(messages) > 4 else messages
        
        for msg in recent_messages:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = msg.get("content", "").strip()
            if content and len(content) > 200:
                content = content[:200] + "..."
            context_parts.append(f"{role}: {content}")
        
        return "\n".join(context_parts) if context_parts else "无历史对话"

    def _call_openai_api(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        """调用OpenAI API"""
        if not self.valves.OPENAI_API_KEY:
            return "错误: 未设置OpenAI API密钥"
        
        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": messages,
            "max_tokens": self.valves.OPENAI_MAX_TOKENS,
            "temperature": self.valves.OPENAI_TEMPERATURE,
        }
        
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.valves.OPENAI_TIMEOUT)
            response.raise_for_status()
            result = response.json()
            
            response_content = result["choices"][0]["message"]["content"]
            
            # 统计token使用
            input_text = system_prompt + user_prompt
            self._add_token_stats(input_text, response_content)
            
            return response_content
        except Exception as e:
            return f"OpenAI API调用错误: {str(e)}"

    def _stream_openai_response(self, system_prompt: str, user_prompt: str) -> Generator:
        """流式处理OpenAI响应"""
        if not self.valves.OPENAI_API_KEY:
            yield "错误: 未设置OpenAI API密钥"
            return
        
        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": messages,
            "max_tokens": self.valves.OPENAI_MAX_TOKENS,
            "temperature": self.valves.OPENAI_TEMPERATURE,
            "stream": True
        }
        
        output_content = ""
        
        try:
            response = requests.post(url, headers=headers, json=payload, stream=True, timeout=self.valves.OPENAI_TIMEOUT)
            response.raise_for_status()
            
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
                                output_content += delta
                                yield delta
                        except json.JSONDecodeError:
                            pass
            
            # 统计token使用
            input_text = system_prompt + user_prompt
            self._add_token_stats(input_text, output_content)
            
        except Exception as e:
            yield f"OpenAI流式API调用错误: {str(e)}"

    def _call_lightrag(self, query: str, mode: str = None) -> dict:
        """调用LightRAG进行检索（非流式版本）"""
        if not mode:
            mode = self.valves.LIGHTRAG_DEFAULT_MODE

        url = f"{self.valves.LIGHTRAG_BASE_URL}/query"
        payload = {
            "query": query,
            "mode": mode
        }

        headers = {"Content-Type": "application/json"}

        # 统计输入token
        self._add_token_stats(query, "")

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.LIGHTRAG_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
            
            # 统计输出token
            if "response" in result:
                self._add_token_stats("", result["response"])
                
            return result
        except Exception as e:
            return {"error": f"LightRAG查询失败: {str(e)}"}

    def _call_lightrag_stream(self, query: str, mode: str = None, stage: str = "action") -> Generator[tuple, None, None]:
        """调用LightRAG进行流式检索，支持实时流式输出（同步版本）"""
        if not mode:
            mode = self.valves.LIGHTRAG_DEFAULT_MODE

        url = f"{self.valves.LIGHTRAG_BASE_URL}/query/stream"
        payload = {
            "query": query,
            "mode": mode
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }

        # 统计输入token
        self._add_token_stats(query, "")

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.LIGHTRAG_TIMEOUT,
                stream=True
            )
            response.raise_for_status()
            
            # 设置较小的缓冲区以确保实时性
            response.raw.decode_content = True
            
            collected_content = ""
            buffer = ""
            
            # 使用缓冲区处理NDJSON流式响应
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    # 确保chunk是字符串类型
                    if isinstance(chunk, bytes):
                        chunk = chunk.decode('utf-8', errors='ignore')
                    buffer += chunk
                    
                    # 按行分割处理NDJSON
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        
                        if line:
                            try:
                                json_data = json.loads(line)
                                
                                # 检查是否有错误
                                if "error" in json_data:
                                    yield ("error", f"LightRAG查询失败: {json_data['error']}")
                                    return
                                
                                # 处理正常响应
                                if "response" in json_data:
                                    response_content = json_data["response"]
                                    collected_content += response_content
                                    
                                    # 使用_emit_processing函数进行流式输出
                                    for chunk_emit in self._emit_processing(response_content, stage, next_line=False):
                                        yield ("stream_data", f"data: {json.dumps(chunk_emit)}\n\n")
                                    
                            except json.JSONDecodeError as e:
                                if self.valves.DEBUG_MODE:
                                    logger.warning(f"JSON解析错误: {line} - {str(e)}")
                                continue
            
            # 处理最后的缓冲区内容
            if buffer.strip():
                try:
                    json_data = json.loads(buffer.strip())
                    if "response" in json_data:
                        response_content = json_data["response"]
                        collected_content += response_content
                        
                        # 使用_emit_processing函数进行最后的流式输出
                        for chunk_emit in self._emit_processing(response_content, stage, next_line=False):
                            yield ("stream_data", f"data: {json.dumps(chunk_emit)}\n\n")
                    elif "error" in json_data:
                        yield ("error", f"LightRAG查询失败: {json_data['error']}")
                        return
                except json.JSONDecodeError:
                    if self.valves.DEBUG_MODE:
                        logger.warning(f"无法解析最后的响应片段: {buffer}")
                        
            # 统计输出token
            if collected_content:
                self._add_token_stats("", collected_content)
                
            # 返回最终收集的内容
            yield ("result", {"response": collected_content} if collected_content else {"error": "未获取到检索结果"})
                
        except Exception as e:
            yield ("error", f"LightRAG流式查询失败: {str(e)}")

    async def _reasoning_phase(self, user_message: str, messages: List[dict], stream_mode: bool) -> AsyncGenerator[tuple, None]:
        """ReAct推理阶段"""
        if stream_mode:
            for chunk in self._emit_processing("分析用户问题，判断是否需要检索知识...", "reasoning"):
                yield ("processing", f'data: {json.dumps(chunk)}\n\n')
        
        conversation_context = self._build_conversation_context(user_message, messages)
        used_queries = list(self.react_state['used_queries'])
        collected_info_summary = self._summarize_collected_info()
        
        reasoning_prompt = REASONING_PROMPT.format(
            user_message=user_message,
            conversation_context=conversation_context,
            used_queries=used_queries,
            collected_info_summary=collected_info_summary
        )
        
        decision = self._call_openai_api("", reasoning_prompt, json_mode=True)
        
        # 检查OpenAI API是否返回错误
        if decision.startswith("错误:") or decision.startswith("OpenAI API调用错误:"):
            error_msg = f"❌ 推理分析失败：{decision}"
            if stream_mode:
                for chunk in self._emit_processing(error_msg, "reasoning"):
                    yield ("processing", f'data: {json.dumps(chunk)}\n\n')
            # 返回默认决策，表示不需要搜索
            yield ("decision", {"need_search": False, "sufficient_info": True, "reasoning": "推理分析失败", "error": decision})
            return
        
        try:
            decision_data = json.loads(decision)
            if stream_mode:
                reasoning_content = f"推理分析：{decision_data.get('reasoning', '无分析')}"
                for chunk in self._emit_processing(reasoning_content, "reasoning"):
                    yield ("processing", f'data: {json.dumps(chunk)}\n\n')
            
            yield ("decision", decision_data)
        except json.JSONDecodeError:
            error_msg = "❌ 推理分析结果解析失败：无法解析JSON格式"
            if stream_mode:
                for chunk in self._emit_processing(error_msg, "reasoning"):
                    yield ("processing", f'data: {json.dumps(chunk)}\n\n')
            yield ("decision", {"need_search": False, "sufficient_info": True, "reasoning": "解析失败"})

    async def _action_phase(self, query: str, mode: str = "mix", stream_mode: bool = False) -> AsyncGenerator[tuple, None]:
        """ReAct动作阶段 - 调用LightRAG（使用流式调用）"""
        if stream_mode:
            action_msg = f"执行LightRAG检索：{query} (模式: {mode})"
            for chunk in self._emit_processing(action_msg, "action"):
                yield ("processing", f'data: {json.dumps(chunk)}\n\n')
        
        # 调用LightRAG流式检索
        search_result = None
        collected_content = ""
        
        for stream_result in self._call_lightrag_stream(query, mode, "action"):
            result_type, content = stream_result
            
            if result_type == "stream_data" and stream_mode:
                # 直接输出流式数据
                yield ("processing", content)
            elif result_type == "result":
                # 收集最终结果
                search_result = content
            elif result_type == "error":
                # 处理错误，使用_emit_processing输出错误信息
                if stream_mode:
                    error_msg = f"❌ LightRAG检索失败：{content}"
                    for chunk in self._emit_processing(error_msg, "action"):
                        yield ("processing", f'data: {json.dumps(chunk)}\n\n')
                search_result = {"error": content}
                break
        
        # 如果没有获得结果，设置默认错误
        if search_result is None:
            error_msg = "❌ 未获取到检索结果"
            if stream_mode:
                for chunk in self._emit_processing(error_msg, "action"):
                    yield ("processing", f'data: {json.dumps(chunk)}\n\n')
            search_result = {"error": "未获取到检索结果"}
           
        # 记录查询历史
        self.react_state['query_history'].append({
            "query": query,
            "mode": mode,
            "result": search_result
        })
        self.react_state['used_queries'].add(query.lower())
        self.react_state['search_modes_used'].add(mode)
        
        yield ("result", search_result)

    async def _observation_phase(self, search_result: dict, current_query: str, search_mode: str, 
                         user_message: str, intent_analysis: str, stream_mode: bool) -> AsyncGenerator[tuple, None]:
        """ReAct观察阶段"""
        if stream_mode:
            for chunk in self._emit_processing("观察检索结果，分析信息质量，决定下一步行动...", "observation"):
                yield ("processing", f'data: {json.dumps(chunk)}\n\n')
        
        # 检查检索结果是否包含错误
        if isinstance(search_result, dict) and "error" in search_result:
            error_msg = f"❌ 观察到检索错误：{search_result['error']}"
            if stream_mode:
                for chunk in self._emit_processing(error_msg, "observation"):
                    yield ("processing", f'data: {json.dumps(chunk)}\n\n')
            # 返回默认的观察结果，表示需要停止搜索
            yield ("observation", {"sufficient_info": False, "need_more_search": False, "error": search_result["error"]})
            return
        
        collected_info = self._get_collected_info_text()
        
        observation_prompt = OBSERVATION_PROMPT.format(
            user_message=user_message,
            intent_analysis=intent_analysis,
            current_query=current_query,
            search_mode=search_mode,
            search_result=json.dumps(search_result, ensure_ascii=False, indent=2),
            collected_info=collected_info
        )
        
        observation = self._call_openai_api("", observation_prompt, json_mode=True)
        
        # 检查OpenAI API是否返回错误
        if observation.startswith("错误:") or observation.startswith("OpenAI API调用错误:"):
            error_msg = f"❌ 观察分析失败：{observation}"
            if stream_mode:
                for chunk in self._emit_processing(error_msg, "observation"):
                    yield ("processing", f'data: {json.dumps(chunk)}\n\n')
            # 返回默认的观察结果，表示需要停止搜索
            yield ("observation", {"sufficient_info": False, "need_more_search": False, "error": observation})
            return
        
        try:
            observation_data = json.loads(observation)
            
            # 存储关键信息到收集列表
            key_info = observation_data.get('key_information', [])
            if key_info:
                info_entry = {
                    "query": current_query,
                    "mode": search_mode,
                    "key_information": key_info,
                    "relevance_score": observation_data.get('relevance_score', 5),
                    "raw_result": search_result
                }
                self.react_state['collected_information'].append(info_entry)
            
            if stream_mode:
                obs_content = f"观察分析：{observation_data.get('observation', '无观察')}"
                
                if key_info:
                    obs_content += f"\n提取关键信息：{', '.join(key_info)}"
                
                relevance_score = observation_data.get('relevance_score', 0)
                obs_content += f"\n相关性评分：{relevance_score}/10"
                
                for chunk in self._emit_processing(obs_content, "observation"):
                    yield ("processing", f'data: {json.dumps(chunk)}\n\n')
            
            yield ("observation", observation_data)
        except json.JSONDecodeError:
            error_msg = "❌ 观察分析结果解析失败：无法解析JSON格式"
            if stream_mode:
                for chunk in self._emit_processing(error_msg, "observation"):
                    yield ("processing", f'data: {json.dumps(chunk)}\n\n')
            yield ("observation", {"sufficient_info": True, "need_more_search": False})

    async def _answer_generation_phase(self, user_message: str, messages: List[dict], stream_mode: bool) -> AsyncGenerator[str, None]:
        """答案生成阶段"""
        conversation_context = self._build_conversation_context(user_message, messages)
        collected_information = self._get_collected_info_text()
        
        answer_prompt = ANSWER_GENERATION_PROMPT.format(
            user_message=user_message,
            conversation_context=conversation_context,
            collected_information=collected_information
        )
        
        system_prompt = """你是专业的知识助手。你的任务是：
1. 充分利用所有通过LightRAG检索到的信息
2. 提供准确、全面、有逻辑的回答
3. 确保答案结构清晰，便于理解
4. 如有不确定性，诚实指出
5. 突出最重要的洞察和结论"""
        
        if stream_mode:
            for chunk in self._stream_openai_response(system_prompt, answer_prompt):
                chunk_data = {
                    'choices': [{
                        'delta': {'content': chunk},
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"
            
            # 添加token统计信息
            stats_text = self._get_token_stats_text()
            stats_chunk_data = {
                'choices': [{
                    'delta': {'content': stats_text},
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(stats_chunk_data)}\n\n"
        else:
            answer = self._call_openai_api(system_prompt, answer_prompt)
            stats_text = self._get_token_stats_text()
            yield answer + stats_text

    def _summarize_collected_info(self) -> str:
        """总结已收集的信息"""
        if not self.react_state['collected_information']:
            return "暂无收集信息"
        
        summary = f"已收集 {len(self.react_state['collected_information'])} 条信息："
        for i, info in enumerate(self.react_state['collected_information'], 1):
            key_points = ', '.join(info.get('key_information', []))[:100]
            summary += f"\n{i}. {key_points} (相关性: {info.get('relevance_score', 0)}/10)"
        
        return summary

    def _get_collected_info_text(self) -> str:
        """获取收集信息的完整文本"""
        if not self.react_state['collected_information']:
            return "暂无收集信息"
        
        info_text = f"共收集 {len(self.react_state['collected_information'])} 条检索信息：\n\n"
        
        for i, info in enumerate(self.react_state['collected_information'], 1):
            info_text += f"=== 信息条目 {i} ===\n"
            info_text += f"检索查询：{info.get('query', '未知')}\n"
            info_text += f"检索模式：{info.get('mode', '未知')}\n"
            info_text += f"相关性评分：{info.get('relevance_score', 0)}/10\n"
            
            key_info = info.get('key_information', [])
            if key_info:
                info_text += f"关键信息：{', '.join(key_info)}\n"
            
            raw_result = info.get('raw_result', {})
            if isinstance(raw_result, dict) and 'response' in raw_result:
                response_text = raw_result['response']
                if len(response_text) > 800:
                    response_text = response_text[:800] + "..."
                info_text += f"检索结果：{response_text}\n"
            
            info_text += "\n"
        
        return info_text

    def _get_token_stats_text(self) -> str:
        """格式化token统计信息"""
        stats = self.token_stats
        stats_text = f"""

---

**📊 Token使用统计**
- 输入Token数: {stats['input_tokens']:,} 字符
- 输出Token数: {stats['output_tokens']:,} 字符  
- 总Token数: {stats['total_tokens']:,} 字符
- API调用次数: {stats['api_calls']} 次
- 平均每次调用: {stats['total_tokens']//max(stats['api_calls'], 1):,} 字符

*注: Token数量基于字符数估算，实际使用量可能略有差异*
"""
        return stats_text

    async def _react_loop(self, user_message: str, messages: List[dict], stream_mode: bool) -> AsyncGenerator[str, None]:
        """ReAct主循环"""
        # 重置状态
        self.react_state = {
            "collected_information": [],
            "query_history": [],
            "used_queries": set(),
            "current_iteration": 0,
            "search_modes_used": set(),
        }
        
        self.token_stats = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "api_calls": 0
        }
        
        # 开始流式响应
        if stream_mode:
            yield f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": None}]})}\n\n'
        
        # 1. Reasoning阶段
        initial_decision = None
        async for phase_result in self._reasoning_phase(user_message, messages, stream_mode):
            result_type, content = phase_result
            if result_type == "processing":
                yield content
            elif result_type == "decision":
                initial_decision = content
                break
        
        # 检查是否需要搜索
        if not initial_decision.get("need_search", False) or initial_decision.get("sufficient_info", False):
            # 直接进入答案生成阶段
            async for answer_chunk in self._answer_generation_phase(user_message, messages, stream_mode):
                yield answer_chunk
            return
        
        # 2. Action-Observation循环
        max_iterations = self.valves.MAX_REACT_ITERATIONS
        current_query = initial_decision.get("search_query", "")
        search_mode = initial_decision.get("search_mode", self.valves.LIGHTRAG_DEFAULT_MODE)
        intent_analysis = initial_decision.get("intent_analysis", "")
        
        while self.react_state['current_iteration'] < max_iterations and current_query:
            self.react_state['current_iteration'] += 1
            
            # Action阶段
            search_result = None
            async for phase_result in self._action_phase(current_query, search_mode, stream_mode):
                result_type, content = phase_result
                if result_type == "processing":
                    yield content
                elif result_type == "result":
                    search_result = content
                    break
            
            if search_result is None:
                break
            
            # Observation阶段
            observation = None
            async for phase_result in self._observation_phase(search_result, current_query, search_mode, user_message, intent_analysis, stream_mode):
                result_type, content = phase_result
                if result_type == "processing":
                    yield content
                elif result_type == "observation":
                    observation = content
                    break
            
            # 检查收集信息是否足够
            collected_count = len(self.react_state['collected_information'])
            if collected_count >= self.valves.MIN_INFO_THRESHOLD:
                if stream_mode:
                    stop_content = f"\n✅ 已收集足够信息({collected_count}条 >= {self.valves.MIN_INFO_THRESHOLD}条阈值)，停止搜索"
                    for chunk in self._emit_processing(stop_content, "observation"):
                        yield f'data: {json.dumps(chunk)}\n\n'
                break
            
            # 检查是否需要继续搜索
            if not observation or not observation.get("need_more_search", False) or observation.get("sufficient_info", False):
                break
            
            # 获取下一轮查询
            current_query = observation.get("next_query", "")
            search_mode = observation.get("next_mode", search_mode)
            
            # 避免重复查询
            if current_query and current_query.lower() in self.react_state['used_queries']:
                break
        
        # 3. 答案生成阶段
        async for answer_chunk in self._answer_generation_phase(user_message, messages, stream_mode):
            yield answer_chunk

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Generator, Iterator]:
        """主管道函数"""
        if not user_message or not user_message.strip():
            yield "❌ 请输入有效的问题"
            return
        
        stream_mode = self.valves.ENABLE_STREAMING
        
        try:
            # 在同步环境中运行异步ReAct循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async_gen = self._react_loop(user_message, messages, stream_mode)
                
                while True:
                    try:
                        result = loop.run_until_complete(async_gen.__anext__())
                        yield result
                    except StopAsyncIteration:
                        break
                
                # 流式模式结束标记
                if stream_mode:
                    done_msg = {
                        'choices': [{
                            'delta': {},
                            'finish_reason': 'stop'
                        }]
                    }
                    yield f"data: {json.dumps(done_msg)}\n\n"
                    yield "data: [DONE]\n\n"
                    
            finally:
                loop.close()

        except Exception as e:
            error_msg = f"❌ ReAct Pipeline执行错误: {str(e)}"
            if stream_mode:
                error_chunk = {
                    'choices': [{
                        'delta': {'content': error_msg},
                        'finish_reason': 'stop'
                    }]
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"
                yield "data: [DONE]\n\n"
            else:
                yield error_msg
