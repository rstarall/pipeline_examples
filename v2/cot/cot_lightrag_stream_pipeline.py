"""
title: COT LightRAG Stream Pipeline
author: open-webui
date: 2024-12-20
version: 1.0
license: MIT
description: 一个双管线CoT系统流式版本：管线1直接生成原始回答(对比)，管线2多步骤递进检索(3阶段LightRAG流式)，两条管线并行执行
requirements: requests, pydantic, openai
"""

import os
import json
import requests
import time
from typing import List, Union, Generator, Iterator
from pydantic import BaseModel

# ===========================================
# 提示词模板定义
# ===========================================

# 问题优化阶段 - 整合历史问题进行意图判断和扩写优化
QUESTION_OPTIMIZATION_PROMPT = """你是问题分析优化专家。请基于用户的历史问题和当前问题，判断用户的真实意图并优化当前问题。

用户历史问题：
{history_questions}

用户当前问题：{current_query}

请分析：
1. 用户的问题背景和上下文
2. 当前问题与历史问题的关联
3. 用户的真实意图和需求

基于分析结果，输出一个优化后的问题，要求：
- 整合相关的历史问题信息
- 明确问题的核心意图
- 补充必要的上下文信息
- 保持简洁明确

直接输出优化后的问题（约100字以内）："""

# 管线1 - 直接回答提示词模板
PIPELINE1_DIRECT_PROMPT = """你是一个知识渊博的AI助手。请直接根据用户的问题提供一个全面、准确的回答。

用户问题：{query}

对话历史参考：
{context}

请提供一个详细、准确的回答，涵盖问题的各个方面。回答应该基于你的知识储备，保持客观、准确。"""

# 管线2 - 第一阶段检索问题优化模板
STAGE1_QUERY_OPTIMIZATION_PROMPT = """你是检索问题分析专家。请基于用户问题生成第一阶段的具体检索查询。

用户原始问题: {original_query}
对话上下文: {context}

请提取用户问题中的核心概念、关键实体和潜在需求，生成一个具体的初始检索查询。查询应该针对问题的基础维度，包含具体的名词、术语或概念。

直接输出约150字的具体检索查询："""

# 管线2 - 第二阶段问题优化模板
STAGE2_QUERY_REFINEMENT_PROMPT = """你是检索优化专家。请从第一阶段的检索结果中提取关键信息，生成第二阶段的深度查询。

用户原始问题: {original_query}
第一阶段检索查询: {stage1_query}
第一阶段检索结果: {stage1_results}

请仔细分析第一阶段的检索结果，提取其中的：关键名词、学术术语、重要概念、实体关系、数据指标等具体内容。基于这些提取的信息，思考原始问题中哪些方面需要进一步深入？什么关键信息还缺失？然后生成一个更具体、更深入的第二阶段检索查询。

直接输出约150字的优化检索查询："""

# 管线2 - 第三阶段综合分析模板
STAGE3_COMPREHENSIVE_PROMPT = """你是信息综合分析专家。请整合前两阶段的检索结果，生成第三阶段的综合查询。

用户原始问题: {original_query}

第一阶段检索查询: {stage1_query}
第一阶段检索结果: {stage1_results}

第二阶段检索查询: {stage2_query}
第二阶段检索结果: {stage2_results}

请深入分析前两阶段检索结果中的：具体数据、公式符号、技术细节、案例实例、因果关系、对比分析等内容。思考这些信息之间的关联性，识别知识体系中的关键环节。基于这些具体信息，从原始问题的角度思考：还需要哪些具体的补充信息才能完整回答？生成一个针对性强的第三阶段查询。

直接输出约150字的综合检索查询："""

# 管线2 - 最终答案生成模板
FINAL_ANSWER_GENERATION_PROMPT = """你是知识整合专家。请基于三个阶段的检索结果，生成完整的最终回答。

用户原始问题: {original_query}

第一阶段检索查询: {stage1_query}
第一阶段检索结果: {stage1_results}

第二阶段检索查询: {stage2_query}
第二阶段检索结果: {stage2_results}

第三阶段检索查询: {stage3_query}
第三阶段检索结果: {stage3_results}

请综合三个阶段的检索信息，大量直接引用检索结果中的原始文字、数据、案例、公式等具体内容。保持信息的完整性和准确性，按逻辑层次组织答案，确保内容丰富详实。优先使用检索到的具体信息而非泛泛而谈。

请生成一个详实完整的最终回答："""

# ===========================================
# 阶段配置定义
# ===========================================

# 后端阶段标题映射
STAGE_TITLES = {
    # 问题优化阶段
    "question_optimization": "问题意图分析与优化",
    
    # 管线1阶段
    "direct_answer": "原始回答生成",
    
    # 管线2阶段
    "stage1_retrieval": "第一阶段检索",
    "stage2_retrieval": "第二阶段检索", 
    "stage3_retrieval": "第三阶段检索",
    "final_synthesis": "最终答案综合",
}

# 阶段组配置 - 用于区分两条并行管线
STAGE_GROUP = {
    # 问题优化阶段
    "question_optimization": "preprocessing",
    
    # 管线1 - 直接回答管线
    "direct_answer": "pipeline_1_direct",
    
    # 管线2 - 多阶段检索管线
    "stage1_retrieval": "pipeline_2_stage1",
    "stage2_retrieval": "pipeline_2_stage2", 
    "stage3_retrieval": "pipeline_2_stage3",
    "final_synthesis": "pipeline_2_final",
}


class Pipeline:
    class Valves(BaseModel):
        # OpenAI配置（用于问题优化和直接回答）
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
        LIGHTRAG_ENABLE_STREAMING: bool

        # Pipeline配置
        ENABLE_STREAMING: bool
        DEBUG_MODE: bool
        ENABLE_PARALLEL_EXECUTION: bool

    def __init__(self):
        self.name = "COT LightRAG Stream Pipeline"
        # 初始化token统计
        self.token_stats = {
            "input_tokens": 0,
            "output_tokens": 0,
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

                # LightRAG配置
                "LIGHTRAG_BASE_URL": os.getenv("LIGHTRAG_BASE_URL", "http://117.50.252.245:9621"),
                "LIGHTRAG_DEFAULT_MODE": os.getenv("LIGHTRAG_DEFAULT_MODE", "hybrid"),
                "LIGHTRAG_TIMEOUT": int(os.getenv("LIGHTRAG_TIMEOUT", "30")),
                "LIGHTRAG_ENABLE_STREAMING": os.getenv("LIGHTRAG_ENABLE_STREAMING", "true").lower() == "true",

                # Pipeline配置
                "ENABLE_STREAMING": os.getenv("ENABLE_STREAMING", "true").lower() == "true",
                "DEBUG_MODE": os.getenv("DEBUG_MODE", "false").lower() == "true",
                "ENABLE_PARALLEL_EXECUTION": os.getenv("ENABLE_PARALLEL_EXECUTION", "true").lower() == "true",
            }
        )

    async def on_startup(self):
        print(f"COT LightRAG Stream Pipeline启动: {__name__}")

        # 验证必需的API密钥
        if not self.valves.OPENAI_API_KEY:
            print("❌ 缺少OpenAI API密钥，请设置OPENAI_API_KEY环境变量")

        # 测试LightRAG连接
        try:
            response = requests.get(f"{self.valves.LIGHTRAG_BASE_URL}/health", timeout=5)
            if response.status_code == 200:
                print("✅ LightRAG服务连接成功")
            else:
                print(f"⚠️ LightRAG服务响应异常: {response.status_code}")
        except Exception as e:
            print(f"❌ 无法连接到LightRAG服务: {e}")

    async def on_shutdown(self):
        print(f"COT LightRAG Stream Pipeline关闭: {__name__}")

    def _estimate_tokens(self, text: str) -> int:
        """
        简单的token估算函数，基于字符数估算
        中文字符按1个token计算，英文单词按平均1.3个token计算
        """
        if not text:
            return 0

        # 统计中文字符数
        chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')

        # 统计英文单词数（简单按空格分割）
        english_text = ''.join(char if not ('\u4e00' <= char <= '\u9fff') else ' ' for char in text)
        english_words = len([word for word in english_text.split() if word.strip()])

        # 估算token数：中文字符1:1，英文单词1:1.3
        estimated_tokens = chinese_chars + int(english_words * 1.3)

        return max(estimated_tokens, 1)  # 至少返回1个token

    def _add_input_tokens(self, text: str):
        """添加输入token统计"""
        tokens = self._estimate_tokens(text)
        self.token_stats["input_tokens"] += tokens
        self.token_stats["total_tokens"] += tokens

    def _add_output_tokens(self, text: str):
        """添加输出token统计"""
        tokens = self._estimate_tokens(text)
        self.token_stats["output_tokens"] += tokens
        self.token_stats["total_tokens"] += tokens

    def _reset_token_stats(self):
        """重置token统计"""
        self.token_stats = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        }

    def _get_token_stats(self) -> dict:
        """获取token统计信息"""
        return self.token_stats.copy()

    def _get_history_questions(self, messages: List[dict], max_questions: int = 5) -> str:
        """从消息历史中提取用户的历史问题（不包括AI回答）"""
        if not messages:
            return "无历史问题"

        history_questions = []
        
        # 从最近的消息开始，倒序提取用户问题
        for message in reversed(messages[-10:]):  # 最多取最近10条消息
            role = message.get("role", "user")
            content = message.get("content", "").strip()

            # 只提取用户的问题，不包括AI的回答
            if content and role == "user":
                history_questions.append(content)
                
                if len(history_questions) >= max_questions:
                    break

        # 恢复正序并格式化
        history_questions.reverse()
        if history_questions:
            formatted_questions = []
            for i, question in enumerate(history_questions, 1):
                formatted_questions.append(f"{i}. {question}")
            return "\n".join(formatted_questions)
        else:
            return "无历史问题"

    def _get_conversation_context(self, messages: List[dict], max_context_length: int = 500) -> str:
        """从消息历史中提取对话上下文"""
        if not messages:
            return "无历史对话"

        context_parts = []
        total_length = 0

        # 从最近的消息开始，倒序提取上下文
        for message in reversed(messages[-5:]):  # 最多取最近5条消息
            role = message.get("role", "user")
            content = message.get("content", "").strip()

            if content and role in ["user", "assistant"]:
                role_text = "用户" if role == "user" else "助手"
                msg_text = f"{role_text}: {content}"

                if total_length + len(msg_text) > max_context_length:
                    break

                context_parts.append(msg_text)
                total_length += len(msg_text)

        # 恢复正序
        context_parts.reverse()
        return "\n".join(context_parts) if context_parts else "无历史对话"

    def _call_openai_api(self, messages: List[dict], stream: bool = False, max_retries: int = 2) -> dict:
        """调用OpenAI API，带重试机制"""
        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": messages,
            "max_tokens": self.valves.OPENAI_MAX_TOKENS,
            "temperature": self.valves.OPENAI_TEMPERATURE,
            "stream": stream
        }

        # 统计输入token
        for message in messages:
            self._add_input_tokens(message.get("content", ""))

        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.valves.OPENAI_TIMEOUT,
                    stream=stream
                )
                response.raise_for_status()
                
                if stream:
                    return response
                else:
                    result = response.json()
                    # 统计输出token
                    if "choices" in result and result["choices"]:
                        content = result["choices"][0].get("message", {}).get("content", "")
                        self._add_output_tokens(content)
                    return result

            except Exception as e:
                if attempt < max_retries:
                    if self.valves.DEBUG_MODE:
                        print(f"⚠️ OpenAI API调用失败，{2}秒后重试: {str(e)}")
                    time.sleep(2)
                    continue
                else:
                    return {"error": f"OpenAI API调用失败: {str(e)}"}

    def _query_lightrag_stream(self, query: str, mode: str = None, stage: str = "retrieval", stream_callback=None) -> dict:
        """调用LightRAG进行流式检索，支持实时流式输出"""
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
        self._add_input_tokens(query)

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.LIGHTRAG_TIMEOUT,
                stream=True
            )
            response.raise_for_status()
            
            collected_content = ""
            buffer = ""
            
            # 使用缓冲区处理NDJSON流式响应
            for chunk in response.iter_content(chunk_size=1024, decode_unicode=True):
                if chunk:
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
                                    return {"error": f"LightRAG查询失败: {json_data['error']}"}
                                
                                # 处理正常响应
                                if "response" in json_data:
                                    response_content = json_data["response"]
                                    collected_content += response_content
                                    
                                    # 立即进行流式输出（如果提供了回调函数）
                                    if stream_callback:
                                        for chunk_emit in self._emit_processing(response_content, stage):
                                            stream_callback(f"data: {json.dumps(chunk_emit)}\n\n")
                                    
                            except json.JSONDecodeError as e:
                                if self.valves.DEBUG_MODE:
                                    print(f"警告: JSON解析错误: {line} - {str(e)}")
                                continue
            
            # 处理最后的缓冲区内容
            if buffer.strip():
                try:
                    json_data = json.loads(buffer.strip())
                    if "response" in json_data:
                        response_content = json_data["response"]
                        collected_content += response_content
                        if stream_callback:
                            for chunk_emit in self._emit_processing(response_content, stage):
                                stream_callback(f"data: {json.dumps(chunk_emit)}\n\n")
                    elif "error" in json_data:
                        return {"error": f"LightRAG查询失败: {json_data['error']}"}
                except json.JSONDecodeError:
                    if self.valves.DEBUG_MODE:
                        print(f"警告: 无法解析最后的响应片段: {buffer}")
                        
            # 统计输出token
            if collected_content:
                self._add_output_tokens(collected_content)
                
            return {"response": collected_content} if collected_content else {"error": "未获取到检索结果"}
                
        except Exception as e:
            return {"error": f"LightRAG流式查询失败: {str(e)}"}



    def _query_lightrag(self, query: str, mode: str = None) -> dict:
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
        self._add_input_tokens(query)

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
                self._add_output_tokens(result["response"])
                
            return result
        except Exception as e:
            return {"error": f"LightRAG查询失败: {str(e)}"}

    def _emit_processing(self, message: str, stage: str) -> Generator[dict, None, None]:
        """
        发送处理过程内容 - 使用processing_content字段实现折叠显示

        Args:
            message: 处理内容
            stage: 处理阶段

        Yields:
            处理事件
        """
        yield {
            'choices': [{
                'delta': {
                    'processing_content': message,
                    'processing_title': STAGE_TITLES.get(stage, "处理中"),
                    'processing_stage': STAGE_GROUP.get(stage, "stage_group_1")  # 添加stage信息用于组件区分
                },
                'finish_reason': None
            }]
        }

    def _emit_status(self, description: str, done: bool = False) -> Generator[dict, None, None]:
        """
        发送状态事件 - 不折叠显示的状态信息

        Args:
            description: 状态描述
            done: 是否完成

        Yields:
            状态事件
        """
        yield {
            "event": {
                "type": "status",
                "data": {
                    "description": description,
                    "done": done,
                },
            }
        }

    # ===========================================
    # 问题优化阶段
    # ===========================================

    def _question_optimization(self, messages: List[dict], current_query: str) -> str:
        """问题优化阶段：整合历史问题进行意图判断和扩写优化"""
        try:
            history_questions = self._get_history_questions(messages)
            
            prompt = QUESTION_OPTIMIZATION_PROMPT.format(
                history_questions=history_questions,
                current_query=current_query
            )
            
            messages_for_api = [{"role": "user", "content": prompt}]
            response = self._call_openai_api(messages_for_api, stream=False)
            
            if "error" in response:
                return current_query  # 如果优化失败，返回原始问题
                
            optimized_query = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            
            # 如果优化结果为空，返回原始问题
            return optimized_query if optimized_query else current_query
            
        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ 问题优化失败: {e}")
            return current_query  # 如果发生异常，返回原始问题

    # ===========================================
    # 管线1 - 直接回答生成
    # ===========================================

    def _pipeline1_direct_answer_stream(self, optimized_query: str, messages: List[dict]) -> Generator[str, None, None]:
        """管线1：直接生成原始回答，用于对比 - 支持流式输出"""
        try:
            context = self._get_conversation_context(messages)
            
            prompt = PIPELINE1_DIRECT_PROMPT.format(
                query=optimized_query,
                context=context
            )
            
            messages_for_api = [{"role": "user", "content": prompt}]
            
            # 使用流式API调用
            response = self._call_openai_api(messages_for_api, stream=True)
            
            if isinstance(response, dict) and "error" in response:
                error_msg = f"直接回答生成失败: {response['error']}"
                for chunk in self._emit_processing(error_msg, "direct_answer"):
                    yield f"data: {json.dumps(chunk)}\n\n"
                return
            
            # 处理流式响应
            collected_content = ""
            for line in response.iter_lines():
                if not line or not line.strip():
                    continue

                line = line.decode('utf-8')    
                if line.startswith("data: "):
                    data_content = line[6:].strip()
                    
                    if data_content == "[DONE]":
                        break
                        
                    try:
                        data = json.loads(data_content)
                        if "choices" in data and data["choices"]:
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            
                            if content:
                                collected_content += content
                                # 使用_emit_processing流式输出内容
                                for chunk in self._emit_processing(content, "direct_answer"):
                                    yield f"data: {json.dumps(chunk)}\n\n"
                                    
                    except (json.JSONDecodeError, KeyError):
                        continue
            
            # 统计输出token
            self._add_output_tokens(collected_content)
            
        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ 管线1直接回答失败: {e}")
            error_msg = f"直接回答生成失败: {str(e)}"
            for chunk in self._emit_processing(error_msg, "direct_answer"):
                yield f"data: {json.dumps(chunk)}\n\n"

    # ===========================================
    # 管线2 - 多阶段检索管线（流式版本）
    # ===========================================

    def _pipeline2_stage1_retrieval_stream(self, optimized_query: str, messages: List[dict], stream_callback=None) -> tuple:
        """管线2阶段1：初始检索（流式版本）"""
        try:
            context = self._get_conversation_context(messages)
            
            # 生成第一阶段检索查询
            prompt = STAGE1_QUERY_OPTIMIZATION_PROMPT.format(
                original_query=optimized_query,
                context=context
            )
            
            messages_for_api = [{"role": "user", "content": prompt}]
            response = self._call_openai_api(messages_for_api, stream=False)
            
            if "error" in response:
                return f"第一阶段查询优化失败: {response['error']}", ""
                
            stage1_query = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            
            # 执行LightRAG检索（使用流式查询获取结果）
            lightrag_result = self._query_lightrag_stream(stage1_query, stage="stage1_retrieval", stream_callback=stream_callback)
            
            if "error" in lightrag_result:
                return stage1_query, f"第一阶段检索失败: {lightrag_result['error']}"
                
            stage1_results = lightrag_result.get("response", "未获取到检索结果")
            
            return stage1_query, stage1_results
            
        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ 管线2阶段1失败: {e}")
            return "", f"第一阶段检索失败: {str(e)}"



    def _pipeline2_stage2_retrieval_stream(self, optimized_query: str, stage1_query: str, stage1_results: str, stream_callback=None) -> tuple:
        """管线2阶段2：基于第一阶段结果的深度检索（流式版本）"""
        try:
            # 生成第二阶段检索查询
            prompt = STAGE2_QUERY_REFINEMENT_PROMPT.format(
                original_query=optimized_query,
                stage1_query=stage1_query,
                stage1_results=stage1_results
            )
            
            messages_for_api = [{"role": "user", "content": prompt}]
            response = self._call_openai_api(messages_for_api, stream=False)
            
            if "error" in response:
                return f"第二阶段查询优化失败: {response['error']}", ""
                
            stage2_query = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            
            # 执行LightRAG检索（使用流式版本获取结果）
            lightrag_result = self._query_lightrag_stream(stage2_query, stage="stage2_retrieval", stream_callback=stream_callback)
            
            if "error" in lightrag_result:
                return stage2_query, f"第二阶段检索失败: {lightrag_result['error']}"
                
            stage2_results = lightrag_result.get("response", "未获取到检索结果")
            
            return stage2_query, stage2_results
            
        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ 管线2阶段2失败: {e}")
            return "", f"第二阶段检索失败: {str(e)}"

    def _pipeline2_stage3_retrieval_stream(self, optimized_query: str, stage1_query: str, stage1_results: str, 
                                   stage2_query: str, stage2_results: str, stream_callback=None) -> tuple:
        """管线2阶段3：综合性检索（流式版本）"""
        try:
            # 生成第三阶段检索查询
            prompt = STAGE3_COMPREHENSIVE_PROMPT.format(
                original_query=optimized_query,
                stage1_query=stage1_query,
                stage1_results=stage1_results,
                stage2_query=stage2_query,
                stage2_results=stage2_results
            )
            
            messages_for_api = [{"role": "user", "content": prompt}]
            response = self._call_openai_api(messages_for_api, stream=False)
            
            if "error" in response:
                return f"第三阶段查询优化失败: {response['error']}", ""
                
            stage3_query = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            
            # 执行LightRAG检索（使用流式版本获取结果）
            lightrag_result = self._query_lightrag_stream(stage3_query, stage="stage3_retrieval", stream_callback=stream_callback)
            
            if "error" in lightrag_result:
                return stage3_query, f"第三阶段检索失败: {lightrag_result['error']}"
                
            stage3_results = lightrag_result.get("response", "未获取到检索结果")
            
            return stage3_query, stage3_results
            
        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ 管线2阶段3失败: {e}")
            return "", f"第三阶段检索失败: {str(e)}"

    def _pipeline2_final_synthesis_stream(self, optimized_query: str, stage1_query: str, stage1_results: str,
                                  stage2_query: str, stage2_results: str, stage3_query: str, stage3_results: str) -> str:
        """管线2最终阶段：综合三次检索结果生成最终答案"""
        try:
            # 生成最终答案
            prompt = FINAL_ANSWER_GENERATION_PROMPT.format(
                original_query=optimized_query,
                stage1_query=stage1_query,
                stage1_results=stage1_results,
                stage2_query=stage2_query,
                stage2_results=stage2_results,
                stage3_query=stage3_query,
                stage3_results=stage3_results
            )
            
            messages_for_api = [{"role": "user", "content": prompt}]
            response = self._call_openai_api(messages_for_api, stream=False)
            
            if "error" in response:
                return f"最终答案生成失败: {response['error']}"
                
            final_answer = response.get("choices", [{}])[0].get("message", {}).get("content", "未获取到最终答案")
            
            return final_answer
            
        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ 管线2最终综合失败: {e}")
            return f"最终答案生成失败: {str(e)}"

    # ===========================================
    # 主管线执行方法
    # ===========================================

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict,
        __event_emitter__=None,
        __event_call__=None,
        __user__=None
    ) -> Union[str, Generator, Iterator]:
        """
        处理用户查询的主要方法 - 双管线CoT系统（流式版本）

        管线1：直接生成原始回答（用于对比）
        管线2：3阶段递进检索，最后综合生成答案

        Args:
            user_message: 用户输入的消息
            model_id: 模型ID
            messages: 消息历史
            body: 请求体，包含流式设置和用户信息

        Returns:
            查询结果字符串或流式生成器
        """
        # 重置token统计
        self._reset_token_stats()

        # 验证必需参数
        if not self.valves.OPENAI_API_KEY:
            return "❌ 错误：缺少OpenAI API密钥，请在配置中设置OPENAI_API_KEY"

        if not user_message.strip():
            return "❌ 请提供有效的查询内容"

        # 打印调试信息
        if self.valves.DEBUG_MODE and "user" in body:
            print("=" * 50)
            print(f"用户: {body['user']['name']} ({body['user']['id']})")
            print(f"查询内容: {user_message}")
            print(f"流式响应: {body.get('stream', False)}")
            print(f"启用流式: {self.valves.ENABLE_STREAMING}")
            print("=" * 50)

        # 总是返回流式响应
        return self._stream_response(user_message, messages)

    def _stream_response(self, query: str, messages: List[dict]) -> Generator[str, None, None]:
        """流式响应处理 - 双管线并行执行"""
        try:
            # 流式开始消息
            yield f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": None}]})}\n\n'

            # 问题优化阶段
            for chunk in self._emit_processing("正在分析用户意图并优化问题...\n", "question_optimization"):
                yield f"data: {json.dumps(chunk)}\n\n"

            optimized_query = self._question_optimization(messages, query)

            for chunk in self._emit_processing(f"✅ 问题优化完成\n\n**原始问题:**\n{query}\n\n**优化后的问题:**\n{optimized_query}", "question_optimization"):
                yield f"data: {json.dumps(chunk)}\n\n"

            # 流式处理管线1的直接回答
            for chunk in self._pipeline1_direct_answer_stream(optimized_query, messages):
                yield chunk

            for chunk in self._emit_processing("\n✅ 直接回答生成完成", "direct_answer"):
                yield f"data: {json.dumps(chunk)}\n\n"

            # 管线2：多阶段检索
            # 第一阶段
            for chunk in self._emit_processing("正在进行第一阶段检索...\n", "stage1_retrieval"):
                yield f"data: {json.dumps(chunk)}\n\n"

            # 创建stream_callback来收集实时输出
            stream_buffer = []
            def stream_callback(data):
                stream_buffer.append(data)

            stage1_query, stage1_results = self._pipeline2_stage1_retrieval_stream(optimized_query, messages, stream_callback)
            
            # 输出收集到的流式数据
            for buffered_data in stream_buffer:
                yield buffered_data
            stream_buffer.clear()

            for chunk in self._emit_processing(f"✅ 第一阶段检索完成\n\n**检索查询:**\n{stage1_query}\n\n**检索结果长度:** {len(stage1_results)} 字符", "stage1_retrieval"):
                yield f"data: {json.dumps(chunk)}\n\n"

            # 第二阶段
            for chunk in self._emit_processing("正在进行第二阶段深度检索...\n", "stage2_retrieval"):
                yield f"data: {json.dumps(chunk)}\n\n"

            stage2_query, stage2_results = self._pipeline2_stage2_retrieval_stream(optimized_query, stage1_query, stage1_results, stream_callback)
            
            # 输出收集到的流式数据
            for buffered_data in stream_buffer:
                yield buffered_data
            stream_buffer.clear()

            for chunk in self._emit_processing(f"✅ 第二阶段检索完成\n\n**检索查询:**\n{stage2_query}\n\n**检索结果长度:** {len(stage2_results)} 字符", "stage2_retrieval"):
                yield f"data: {json.dumps(chunk)}\n\n"

            # 第三阶段
            for chunk in self._emit_processing("正在进行第三阶段综合检索...\n", "stage3_retrieval"):
                yield f"data: {json.dumps(chunk)}\n\n"

            stage3_query, stage3_results = self._pipeline2_stage3_retrieval_stream(
                optimized_query, stage1_query, stage1_results, stage2_query, stage2_results, stream_callback
            )
            
            # 输出收集到的流式数据
            for buffered_data in stream_buffer:
                yield buffered_data
            stream_buffer.clear()

            for chunk in self._emit_processing(f"✅ 第三阶段检索完成\n\n**检索查询:**\n{stage3_query}\n\n**检索结果长度:** {len(stage3_results)} 字符", "stage3_retrieval"):
                yield f"data: {json.dumps(chunk)}\n\n"

            # 最终综合
            for chunk in self._emit_processing("正在综合三个阶段的检索结果，生成最终答案...", "final_synthesis"):
                yield f"data: {json.dumps(chunk)}\n\n"

            final_answer = self._pipeline2_final_synthesis_stream(
                optimized_query, stage1_query, stage1_results, stage2_query, stage2_results, stage3_query, stage3_results
            )

            for chunk in self._emit_processing(f"✅ 最终答案综合完成\n\n**最终答案:**\n{final_answer}", "final_synthesis"):
                yield f"data: {json.dumps(chunk)}\n\n"

            # 显示管线2最终结果（非折叠显示）
            pipeline2_msg = {
                'choices': [{
                    'delta': {
                        'content': f"\n**🧠 管线2 - 多阶段检索最终答案**\n{final_answer}\n"
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(pipeline2_msg)}\n\n"

            # 添加token统计信息
            token_stats = self._get_token_stats()
            token_info_msg = {
                'choices': [{
                    'delta': {
                        'content': f"\n\n---\n**Token消耗统计**\n- 输入Token: {token_stats['input_tokens']:,}\n- 输出Token: {token_stats['output_tokens']:,}\n- 总Token: {token_stats['total_tokens']:,}"
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(token_info_msg)}\n\n"

        except Exception as e:
            error_msg = f"❌ CoT Pipeline执行失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"Stream error: {e}")
            yield f'data: {json.dumps({"choices": [{"delta": {"content": error_msg}}]})}\n\n'

        yield "data: [DONE]\n\n"
