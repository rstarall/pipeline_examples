"""
title: SearxNG Search OpenAI Pipeline
author: open-webui
date: 2024-12-20
version: 1.0
license: MIT
description: A 3-stage pipeline: 1) LLM query optimization, 2) Web search using SearxNG API, 3) AI-enhanced Q&A with OpenAI API
requirements: requests, pydantic
"""

import os
import json
import requests
import time
from typing import List, Union, Generator, Iterator
from pydantic import BaseModel


class HistoryContextManager:
    """历史会话上下文管理器 - 统一处理历史会话信息"""
    
    DEFAULT_HISTORY_TURNS = 3  # 默认3轮对话（6条消息）
    
    @classmethod
    def extract_recent_context(cls, messages: List[dict], max_turns: int = None) -> str:
        """
        提取最近的历史会话上下文
        
        Args:
            messages: 消息列表
            max_turns: 最大轮次数，默认为3轮
        
        Returns:
            格式化的历史上下文字符串
        """
        if not messages or len(messages) < 2:
            return ""
            
        max_turns = max_turns or cls.DEFAULT_HISTORY_TURNS
        max_messages = max_turns * 2  # 每轮包含用户和助手消息
        
        recent_messages = messages[-max_messages:] if len(messages) > max_messages else messages
        context_text = ""
        
        for msg in recent_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                context_text += f"用户: {content}\n"
            elif role == "assistant":
                context_text += f"助手: {content}\n"
                
        return context_text.strip()
    
    @classmethod
    def format_answer_prompt(cls,
                           original_query: str,
                           search_results: str,
                           messages: List[dict],
                           max_turns: int = None) -> str:
        """
        格式化答案生成提示模板
        
        Args:
            original_query: 原始用户查询
            search_results: 搜索结果
            messages: 历史消息
            max_turns: 最大历史轮次
            
        Returns:
            格式化的提示文本
        """
        context_text = cls.extract_recent_context(messages, max_turns)
        
        prompt_content = f"""基于以下搜索结果回答用户的问题。

搜索结果:
{search_results}

当前问题: {original_query}"""

        if context_text.strip():
            prompt_content = f"""基于以下对话历史和搜索结果回答用户的问题。

对话历史:
{context_text}

搜索结果:
{search_results}

当前问题: {original_query}"""

        prompt_content += """

请根据搜索结果提供准确、详细且有用的回答：
1. 结合对话历史和搜索结果，理解用户的真实需求
2. 基于搜索到的信息提供准确回答
3. 如果搜索结果不足以完全回答问题，请说明哪些部分需要更多信息
4. 保持回答的结构清晰，使用适当的格式
5. 在必要时提供相关的链接或参考资料"""

        return prompt_content


class Pipeline:
    class Valves(BaseModel):
        # SearxNG搜索API配置
        SEARXNG_URL: str
        SEARXNG_SEARCH_COUNT: int
        SEARXNG_LANGUAGE: str
        SEARXNG_TIMEOUT: int
        SEARXNG_CATEGORIES: str
        SEARXNG_TIME_RANGE: str
        SEARXNG_SAFESEARCH: int

        # OpenAI配置
        OPENAI_API_KEY: str
        OPENAI_BASE_URL: str
        OPENAI_MODEL: str
        OPENAI_TIMEOUT: int
        OPENAI_MAX_TOKENS: int
        OPENAI_TEMPERATURE: float

        # Pipeline配置
        ENABLE_STREAMING: bool
        DEBUG_MODE: bool
        
        # 历史会话配置
        HISTORY_TURNS: int

    def __init__(self):
        self.name = "SearxNG Search OpenAI Pipeline"
        # 初始化token统计
        self.token_stats = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        }
        
        self.valves = self.Valves(
            **{
                # SearxNG搜索配置
                "SEARXNG_URL": os.getenv("SEARXNG_URL", "http://117.50.252.245:8081"),
                "SEARXNG_SEARCH_COUNT": int(os.getenv("SEARXNG_SEARCH_COUNT", "8")),
                "SEARXNG_LANGUAGE": os.getenv("SEARXNG_LANGUAGE", "zh-CN"),
                "SEARXNG_TIMEOUT": int(os.getenv("SEARXNG_TIMEOUT", "15")),
                "SEARXNG_CATEGORIES": os.getenv("SEARXNG_CATEGORIES", "general"),
                "SEARXNG_TIME_RANGE": os.getenv("SEARXNG_TIME_RANGE", "month"),  # day, week, month, year
                "SEARXNG_SAFESEARCH": int(os.getenv("SEARXNG_SAFESEARCH", "0")),  # 0, 1, 2
                
                # OpenAI配置
                "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
                "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
                "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4o"),
                "OPENAI_TIMEOUT": int(os.getenv("OPENAI_TIMEOUT", "60")),
                "OPENAI_MAX_TOKENS": int(os.getenv("OPENAI_MAX_TOKENS", "4000")),
                "OPENAI_TEMPERATURE": float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
                
                # Pipeline配置
                "ENABLE_STREAMING": os.getenv("ENABLE_STREAMING", "true").lower() == "true",
                "DEBUG_MODE": os.getenv("DEBUG_MODE", "false").lower() == "true",
                
                # 历史会话配置
                "HISTORY_TURNS": int(os.getenv("HISTORY_TURNS", "3")),
            }
        )

    async def on_startup(self):
        print(f"SearxNG Search OpenAI Pipeline启动: {__name__}")
        
        # 验证必需的API密钥
        if not self.valves.OPENAI_API_KEY:
            print("❌ 缺少OpenAI API密钥，请设置OPENAI_API_KEY环境变量")
            
        # 测试SearxNG API连接
        try:
            print("🔧 开始测试SearxNG API连接...")
            test_response = self._search_searxng("test query", count=1)
            if test_response and "results" in test_response:
                print("✅ SearxNG搜索API连接成功")
            else:
                print("⚠️ SearxNG搜索API测试失败")
        except Exception as e:
            print(f"❌ SearxNG搜索API连接失败: {e}")

    async def on_shutdown(self):
        print(f"SearxNG Search OpenAI Pipeline关闭: {__name__}")

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

    def _search_searxng(self, query: str, count: int = None, max_retries: int = 2) -> dict:
        """调用SearxNG API进行搜索，带重试机制"""
        url = f"{self.valves.SEARXNG_URL}/search"

        # 参数验证
        search_count = count or self.valves.SEARXNG_SEARCH_COUNT
        if search_count < 1:
            search_count = 1

        # 构建请求参数 - 不指定特定搜索引擎，让SearXNG自动选择可用的引擎
        params = {
            'q': query.strip(),
            'format': 'json',
            'language': self.valves.SEARXNG_LANGUAGE,
            'safesearch': self.valves.SEARXNG_SAFESEARCH,
            'categories': self.valves.SEARXNG_CATEGORIES
        }

        # 添加可选参数
        if self.valves.SEARXNG_TIME_RANGE:
            params['time_range'] = self.valves.SEARXNG_TIME_RANGE

        # 重试逻辑
        for attempt in range(max_retries + 1):
            try:
                # 添加详细的调试信息
                if self.valves.DEBUG_MODE:
                    print(f"🔍 SearxNG搜索调试信息 (尝试 {attempt + 1}/{max_retries + 1}):")
                    print(f"   URL: {url}")
                    print(f"   请求参数: {json.dumps(params, ensure_ascii=False, indent=2)}")

                response = requests.get(
                    url,
                    params=params,
                    timeout=self.valves.SEARXNG_TIMEOUT
                )

                # 添加响应调试信息
                if self.valves.DEBUG_MODE:
                    print(f"   响应状态码: {response.status_code}")
                    if response.status_code != 200:
                        print(f"   响应内容: {response.text}")

                response.raise_for_status()
                result = response.json()

                if self.valves.DEBUG_MODE:
                    print(f"   响应成功，数据长度: {len(str(result))}")
                    if isinstance(result, dict):
                        print(f"   找到结果数量: {result.get('number_of_results', 0)}")

                return result

            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    if self.valves.DEBUG_MODE:
                        print(f"⚠️ 搜索超时，{2}秒后重试 (尝试 {attempt + 1}/{max_retries + 1})")
                    time.sleep(2)
                    continue
                else:
                    error_msg = "SearxNG搜索超时，可能是搜索引擎连接问题，请稍后重试"
                    if self.valves.DEBUG_MODE:
                        print(f"❌ {error_msg}")
                        print("   提示：如果持续超时，可能是后端搜索引擎不可用")
                    return {"error": error_msg}
            except Exception as e:
                if attempt < max_retries:
                    if self.valves.DEBUG_MODE:
                        print(f"⚠️ 搜索出错，{2}秒后重试: {str(e)}")
                    time.sleep(2)
                    continue
                else:
                    # 处理其他异常
                    break

        # 如果所有重试都失败，返回错误
        return {"error": "SearxNG搜索失败，请稍后重试"}

    def _format_search_results(self, search_response: dict) -> str:
        """格式化搜索结果为文本"""
        if "error" in search_response:
            return f"搜索错误: {search_response['error']}"

        # 检查响应结构
        if not isinstance(search_response, dict):
            return "搜索响应格式错误"

        # 检查SearxNG API的响应结构
        results = search_response.get("results", [])
        if not results:
            return "未找到相关搜索结果，请尝试其他关键词"

        formatted_results = []
        total_results = search_response.get("number_of_results", 0)

        # 添加搜索完成提示和统计信息
        if total_results > 0:
            formatted_results.append("搜索完成，找到相关信息")
            formatted_results.append(f"找到约 {total_results:,} 条相关结果\n")
        else:
            formatted_results.append("搜索完成，找到相关信息\n")

        # 限制显示的结果数量
        display_count = min(len(results), self.valves.SEARXNG_SEARCH_COUNT)

        for i, result in enumerate(results[:display_count], 1):
            title = result.get("title", "无标题").strip()
            url = result.get("url", "").strip()
            content = result.get("content", "").strip()

            # 清理和截断内容
            if content:
                # 移除多余的空白字符
                content = ' '.join(content.split())
                # 如果内容太长，截断并添加省略号
                if len(content) > 200:
                    content = content[:200] + "..."

            # 格式化单个结果为markdown格式
            result_text = f"**[{i}] {title}**\n"
            result_text += f"链接: {url}\n"
            if content:
                result_text += f"摘要: {content}\n"

            formatted_results.append(result_text)

        return "\n\n".join(formatted_results)

    def _optimize_search_query(self, user_message: str, messages: List[dict]) -> str:
        """优化搜索查询，考虑历史对话上下文"""
        # 提取历史上下文用于调试显示
        context_text = HistoryContextManager.extract_recent_context(messages, self.valves.HISTORY_TURNS)
        
        if self.valves.DEBUG_MODE and context_text:
            print(f"🔄 历史上下文({self.valves.HISTORY_TURNS}轮):\n{context_text[:200]}...")

        # 目前简单返回原查询，历史上下文在答案生成阶段使用
        return user_message

    def _stage1_search(self, query: str) -> tuple:
        """第一阶段：执行搜索并获取结果"""
        if self.valves.DEBUG_MODE:
            print(f"🔍 执行搜索: {query}")

        # 验证查询参数
        if not query or not query.strip():
            return "搜索查询不能为空", False

        search_response = self._search_searxng(query.strip())

        if "error" in search_response:
            return f"搜索错误: {search_response['error']}", False

        # 检查搜索结果是否有效
        if not search_response.get("results"):
            return "未找到相关搜索结果，请尝试使用不同的关键词", False

        formatted_results = self._format_search_results(search_response)

        if self.valves.DEBUG_MODE:
            print(f"✅ 搜索完成，结果长度: {len(formatted_results)}")
            print(f"   找到结果数量: {len(search_response.get('results', []))}")

        return formatted_results, True

    def _stage2_generate_answer(self, query: str, search_results: str, messages: List[dict] = None, stream: bool = False) -> Union[str, Generator]:
        """第二阶段：使用OpenAI生成回答"""
        if not self.valves.OPENAI_API_KEY:
            return "错误: 未设置OpenAI API密钥"
        
        system_prompt = """你是一个基于搜索结果回答问题的AI助手。

请遵循以下原则：
1. 主要基于提供的搜索结果回答用户问题
2. 结合对话历史理解用户的真实需求和上下文
3. 如果搜索结果包含相关信息，请提供详细、准确的回答
4. 引用搜索结果时使用编号（如[1]、[2]等）来标注信息来源
5. 如果搜索结果信息不足，请诚实说明并提供可能的建议
6. 不要编造或推测搜索结果中没有的信息
7. 回答要结构清晰，重点突出
8. 如果发现搜索结果中有矛盾信息，请指出并说明

请用中文回答，语言要自然流畅。"""

        # 使用历史上下文管理器生成提示
        user_prompt = HistoryContextManager.format_answer_prompt(
            original_query=query,
            search_results=search_results,
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
            "temperature": self.valves.OPENAI_TEMPERATURE,
            "stream": stream
        }
        
        # 添加输入token统计
        self._add_input_tokens(system_prompt)
        self._add_input_tokens(user_prompt)
        
        if self.valves.DEBUG_MODE:
            print("🤖 调用OpenAI API生成回答")
            print(f"   模型: {self.valves.OPENAI_MODEL}")
            print(f"   流式响应: {stream}")
        
        try:
            if stream:
                # 流式模式：返回生成器
                for chunk in self._stream_openai_response(url, headers, payload):
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

                # 添加输出token统计
                self._add_output_tokens(answer)

                if self.valves.DEBUG_MODE:
                    print(f"✅ 生成回答完成，长度: {len(answer)}")
                    print(f"   Token统计: {self._get_token_stats()}")

                return answer

        except Exception as e:
            error_msg = f"OpenAI API调用错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            if stream:
                yield error_msg
            else:
                return error_msg

    def _stream_openai_response(self, url, headers, payload):
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
                                self._add_output_tokens(delta)
                                yield delta
                        except json.JSONDecodeError:
                            pass
            
            if self.valves.DEBUG_MODE:
                print(f"✅ 流式生成完成，总长度: {len(collected_content)}")
                print(f"   Token统计: {self._get_token_stats()}")
                
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
            print(f"📝 用户消息: {user_message}")
            print(f"🔧 模型ID: {model_id}")
            print(f"📜 历史消息数量: {len(messages) if messages else 0}")

        # 验证输入
        if not user_message or not user_message.strip():
            yield "❌ 请输入有效的问题或查询内容"
            return

        # 阶段1：查询优化
        yield "🔄 **阶段1**: 正在优化搜索查询..."
        optimized_query = self._optimize_search_query(user_message, messages)

        if optimized_query != user_message:
            yield f"✅ 查询已优化: `{optimized_query}`\n"
        else:
            yield f"✅ 使用原始查询: `{user_message}`\n"

        # 阶段2：执行搜索
        yield "🔍 **阶段2**: 正在搜索相关信息..."
        search_results, search_success = self._stage1_search(optimized_query)

        if not search_success:
            # 如果优化后的查询失败，尝试使用原始查询
            if optimized_query != user_message:
                yield "⚠️ 优化查询失败，尝试原始查询..."
                search_results, search_success = self._stage1_search(user_message)

            if not search_success:
                # 如果搜索完全失败，提供基于OpenAI的回答
                if self.valves.OPENAI_API_KEY:
                    yield "❌ 搜索失败，将基于AI知识回答\n"
                    yield "🤖 **阶段3**: 正在生成基于知识的回答..."
                    fallback_prompt = f"用户问题: {user_message}\n\n由于无法获取搜索结果，请基于你的知识回答这个问题，并说明这是基于已有知识的回答，可能不是最新信息。"
                    stream_mode = body.get("stream", False) and self.valves.ENABLE_STREAMING

                    if stream_mode:
                        for chunk in self._stage2_generate_answer(user_message, fallback_prompt, messages, stream=True):
                            yield chunk
                    else:
                        result = self._stage2_generate_answer(user_message, fallback_prompt, messages, stream=False)
                        yield result
                        # 添加token统计信息
                        token_info = self._get_token_stats()
                        yield f"\n\n---\n📊 **Token统计**: 输入 {token_info['input_tokens']}, 输出 {token_info['output_tokens']}, 总计 {token_info['total_tokens']}"
                    return
                else:
                    yield f"❌ 搜索失败且未配置OpenAI API密钥: {search_results}"
                    return

        # 搜索成功，显示搜索结果
        yield "✅ 搜索完成\n"
        yield search_results
        yield "\n"

        # 阶段3：生成AI回答
        yield "🤖 **阶段3**: 正在基于搜索结果生成回答..."
        stream_mode = body.get("stream", False) and self.valves.ENABLE_STREAMING

        try:
            if stream_mode:
                # 流式模式
                for chunk in self._stage2_generate_answer(user_message, search_results, messages, stream=True):
                    yield chunk
                # 流式模式结束后添加token统计
                token_info = self._get_token_stats()
                yield f"\n\n---\n📊 **Token统计**: 输入 {token_info['input_tokens']}, 输出 {token_info['output_tokens']}, 总计 {token_info['total_tokens']}"
            else:
                # 非流式模式
                result = self._stage2_generate_answer(user_message, search_results, messages, stream=False)
                yield result
                # 添加token统计信息
                token_info = self._get_token_stats()
                yield f"\n\n---\n📊 **Token统计**: 输入 {token_info['input_tokens']}, 输出 {token_info['output_tokens']}, 总计 {token_info['total_tokens']}"

        except Exception as e:
            error_msg = f"❌ 生成回答时发生错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            yield error_msg