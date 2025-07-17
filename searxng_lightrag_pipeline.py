"""
title: SearxNG LightRAG Pipeline
author: open-webui
date: 2024-12-20
version: 1.0
license: MIT
description: A 4-stage pipeline: 1) Query optimization, 2) Web search using SearxNG API, 3) Generate enhanced LightRAG query, 4) LightRAG Q&A
requirements: requests, pydantic
"""

import os
import json
import requests
import time
from typing import List, Union, Generator, Iterator
from pydantic import BaseModel


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

        # OpenAI配置（用于问题优化和LightRAG查询生成）
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

    def __init__(self):
        self.name = "SearxNG LightRAG Pipeline"
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

                # LightRAG配置
                "LIGHTRAG_BASE_URL": os.getenv("LIGHTRAG_BASE_URL", "http://localhost:9621"),
                "LIGHTRAG_DEFAULT_MODE": os.getenv("LIGHTRAG_DEFAULT_MODE", "hybrid"),
                "LIGHTRAG_TIMEOUT": int(os.getenv("LIGHTRAG_TIMEOUT", "30")),
                "LIGHTRAG_ENABLE_STREAMING": os.getenv("LIGHTRAG_ENABLE_STREAMING", "true").lower() == "true",

                # Pipeline配置
                "ENABLE_STREAMING": os.getenv("ENABLE_STREAMING", "true").lower() == "true",
                "DEBUG_MODE": os.getenv("DEBUG_MODE", "false").lower() == "true",
            }
        )

    async def on_startup(self):
        print(f"SearxNG LightRAG Pipeline启动: {__name__}")

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
        print(f"SearxNG LightRAG Pipeline关闭: {__name__}")

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

            # 格式化单个结果
            result_text = f"{i}. {title}\n"
            if url:
                result_text += f"   链接: {url}\n"
            if content:
                result_text += f"   内容: {content}\n"

            formatted_results.append(result_text)

        return "\n".join(formatted_results)

    def _extract_search_links(self, search_response: dict) -> str:
        """提取搜索结果中的链接，格式化为MD格式"""
        if "error" in search_response:
            return ""

        # 检查SearxNG API的响应结构
        results = search_response.get("results", [])
        if not results:
            return ""

        formatted_links = []
        display_count = min(len(results), self.valves.SEARXNG_SEARCH_COUNT)

        for i, result in enumerate(results[:display_count], 1):
            title = result.get("title", "无标题").strip()
            url = result.get("url", "").strip()

            if url and title:
                # 格式化为MD链接格式
                formatted_links.append(f"{i}. [{title}]({url})")

        return "\n".join(formatted_links)

    def _call_openai_api(self, messages: List[dict], stream: bool = False) -> Union[dict, Iterator[dict]]:
        """调用OpenAI API"""
        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"

        # 统计输入token
        input_text = ""
        for message in messages:
            input_text += message.get("content", "") + " "
        self._add_input_tokens(input_text)

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

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.OPENAI_TIMEOUT,
                stream=stream
            )
            response.raise_for_status()

            if stream:
                return self._parse_stream_response_with_tokens(response)
            else:
                result = response.json()
                # 统计输出token
                if 'choices' in result and len(result['choices']) > 0:
                    output_content = result['choices'][0]['message']['content']
                    self._add_output_tokens(output_content)
                return result

        except Exception as e:
            raise Exception(f"OpenAI API调用失败: {str(e)}")

    def _parse_stream_response_with_tokens(self, response) -> Iterator[dict]:
        """解析流式响应并统计token"""
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = line[6:]
                    if data.strip() == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data)
                        # 统计输出token
                        if 'choices' in chunk and len(chunk['choices']) > 0:
                            delta = chunk['choices'][0].get('delta', {})
                            if 'content' in delta:
                                self._add_output_tokens(delta['content'])
                        yield chunk
                    except json.JSONDecodeError:
                        continue

    def _stage1_optimize_query(self, user_query: str, messages: List[dict]) -> str:
        """第一阶段：基于对话历史的LLM问题优化"""
        context_messages = []

        if messages and len(messages) > 1:
            # 获取更多历史消息以获得更好的上下文理解
            recent_messages = messages[-8:]  # 增加到8条消息
            context_text = ""
            conversation_topics = []

            # 构建对话历史并提取主题
            for msg in recent_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    context_text += f"用户: {content}\n"
                    # 简单提取用户关注的主题关键词
                    if len(content) > 10:  # 过滤太短的内容
                        conversation_topics.append(content[:50])  # 取前50字符作为主题
                elif role == "assistant":
                    context_text += f"助手: {content}\n"

            if context_text.strip():
                topics_summary = "、".join(conversation_topics[-3:]) if conversation_topics else "无特定主题"

                context_messages.append({
                    "role": "user",
                    "content": f"""请基于完整的对话历史和当前问题，生成一个优化的网络搜索查询。

**对话历史**:
{context_text.strip()}

**对话主题总结**: {topics_summary}

**当前问题**: {user_query}

**优化任务**:
请深度分析对话历史，理解用户的连续性需求和关注焦点，然后生成一个优化的搜索查询：

1. **上下文理解**：
   - 分析用户在对话中的关注点演变
   - 识别与当前问题相关的历史信息
   - 理解用户可能的深层需求

2. **查询优化策略**：
   - 结合对话历史中的关键实体和概念
   - 补充相关的专业术语和关键词
   - 考虑时间、地点、人物等重要信息
   - 保持查询的针对性和准确性

3. **输出要求**：
   - 生成一个简洁但信息丰富的搜索查询
   - 长度控制在10-50字之间
   - 只返回优化后的查询文本，不要解释

**优化后的搜索查询**:"""
                })

        if not context_messages:
            context_messages.append({
                "role": "user",
                "content": f"""请优化以下搜索查询，使其更精准和丰富：

**原始问题**: {user_query}

**优化要求**:
1. 补充相关的关键词和专业术语
2. 使查询更具体和准确
3. 保持查询简洁但信息丰富
4. 考虑可能的相关概念和实体
5. 只返回优化后的查询文本，不要解释

**优化后的搜索查询**:"""
            })

        try:
            response = self._call_openai_api(context_messages, stream=False)
            optimized_query = response['choices'][0]['message']['content'].strip()

            if not optimized_query or len(optimized_query) < 3:
                optimized_query = user_query

            if self.valves.DEBUG_MODE:
                print(f"🔧 查询优化: '{user_query}' → '{optimized_query}'")

            return optimized_query

        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ 查询优化失败: {e}")
            return user_query

    def _stage2_search(self, optimized_query: str) -> tuple[str, str, str]:
        """第二阶段：搜索"""
        search_response = self._search_searxng(optimized_query)
        search_results = self._format_search_results(search_response)
        search_links = self._extract_search_links(search_response)

        if "搜索错误" in search_results or "未找到相关搜索结果" in search_results:
            search_status = f"⚠️ {search_results}"
        else:
            search_status = "✅ 搜索完成，找到相关信息"
            if search_links:
                search_status += f"\n\n**相关链接：**\n{search_links}"

        return search_results, search_status, search_links

    def _stage3_generate_lightrag_query(self, original_query: str, search_results: str, messages: List[dict]) -> str:
        """第三阶段：根据搜索结果和对话历史生成增强的LightRAG查询"""
        # 提取更完整的对话历史
        context_text = ""
        conversation_summary = ""

        if messages and len(messages) > 1:
            # 获取更多的历史消息以获得更好的上下文
            recent_messages = messages[-8:]  # 增加到8条消息

            # 构建对话历史文本
            for msg in recent_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    context_text += f"用户: {content}\n"
                elif role == "assistant":
                    context_text += f"助手: {content}\n"

            # 生成对话摘要，帮助理解上下文
            if context_text.strip():
                conversation_summary = f"""
基于对话历史，用户可能关注的主题和背景：
{context_text.strip()}

这表明用户在此次对话中的关注点和需求背景。"""

        # 构建更详细的提示词
        context_analysis = conversation_summary if conversation_summary else "\n这是用户的首次提问，没有前序对话历史。"

        prompt_content = f"""你是一个专业的知识图谱查询专家。请基于以下完整信息生成一个详细、精细、带深度思考的LightRAG检索问题。

**当前用户问题**: {original_query}

**网络搜索获得的最新信息**:
{search_results}

**对话上下文分析**:{context_analysis}

**任务要求**:
请综合分析以上三个方面的信息，生成一个高质量的LightRAG查询：

1. **深度理解用户意图**：
   - 结合对话历史理解用户的真实需求和关注点
   - 识别用户问题的核心关键词和隐含需求
   - 考虑用户可能的后续问题和深层次需求

2. **充分利用搜索结果**：
   - 提取搜索结果中的关键实体、概念和事实
   - 识别重要的时间、地点、人物、事件等信息
   - 分析搜索结果中的关联关系和因果关系

3. **构建综合性查询**：
   - 将用户问题、搜索信息和对话背景有机结合
   - 生成一个包含多个维度和角度的详细查询
   - 查询应该能够引导LightRAG进行深度分析和推理

4. **查询格式要求**：
   - 长度控制在150-400字之间
   - 包含具体的实体名称、关键概念和分析角度
   - 体现思考过程和分析逻辑
   - 语言自然流畅，逻辑清晰

**请直接输出生成的LightRAG查询，不要包含其他解释文字**："""

        query_messages = [{
            "role": "user",
            "content": prompt_content
        }]

        try:
            response = self._call_openai_api(query_messages, stream=False)
            lightrag_query = response['choices'][0]['message']['content'].strip()

            if not lightrag_query or len(lightrag_query) < 20:
                lightrag_query = f"基于以下搜索信息回答问题：{original_query}\n\n搜索结果：{search_results[:500]}..."

            if self.valves.DEBUG_MODE:
                print(f"🔧 LightRAG查询生成: {lightrag_query[:100]}...")

            return lightrag_query

        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ LightRAG查询生成失败: {e}")
            return f"基于以下搜索信息回答问题：{original_query}\n\n搜索结果：{search_results[:500]}..."

    def _stage4_query_lightrag(self, lightrag_query: str, stream: bool = False) -> Union[str, Generator[str, None, None]]:
        """第四阶段：使用LightRAG进行问答"""
        mode = self.valves.LIGHTRAG_DEFAULT_MODE

        # 统计LightRAG查询的输入token
        self._add_input_tokens(lightrag_query)

        if stream and self.valves.LIGHTRAG_ENABLE_STREAMING:
            return self._query_lightrag_streaming(lightrag_query, mode)
        else:
            result = self._query_lightrag_standard(lightrag_query, mode)
            if "error" in result:
                return f"LightRAG查询失败: {result['error']}"
            response_content = result.get("response", "未获取到响应内容")
            # 统计LightRAG响应的输出token
            self._add_output_tokens(response_content)
            return response_content

    def _query_lightrag_standard(self, query: str, mode: str) -> dict:
        """标准LightRAG查询API"""
        url = f"{self.valves.LIGHTRAG_BASE_URL}/query"
        payload = {
            "query": query,
            "mode": mode
        }

        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.LIGHTRAG_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": f"查询失败: {str(e)}"}

    def _query_lightrag_streaming(self, query: str, mode: str) -> Generator[str, None, None]:
        """流式LightRAG查询API"""
        url = f"{self.valves.LIGHTRAG_BASE_URL}/query/stream"

        payload = {
            "query": query,
            "mode": mode
        }

        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                stream=True,
                timeout=self.valves.LIGHTRAG_TIMEOUT
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    line_text = line.decode('utf-8').strip()
                    if line_text:
                        try:
                            data = json.loads(line_text)
                            if 'response' in data and data['response']:
                                chunk = data['response']
                                # 统计LightRAG流式输出token
                                self._add_output_tokens(chunk)
                                yield f'data: {json.dumps({"choices": [{"delta": {"content": chunk}}]})}\n\n'
                            elif 'error' in data:
                                error_msg = data['error']
                                yield f'data: {json.dumps({"choices": [{"delta": {"content": f"错误: {error_msg}"}}]})}\n\n'
                        except json.JSONDecodeError:
                            continue

        except Exception as e:
            error_msg = f"LightRAG流式查询失败: {str(e)}"
            yield f'data: {json.dumps({"choices": [{"delta": {"content": error_msg}}]})}\n\n'

        yield "data: [DONE]\n\n"

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict,
        __event_emitter__=None, 
        __event_call__=None,
        __user__=None
    ) -> Union[str, Generator, Iterator]:
        """
        处理用户查询的主要方法 - 4阶段pipeline

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

        # 根据是否启用流式响应选择不同的处理方式
        if body.get("stream", False) and self.valves.ENABLE_STREAMING:
            return self._stream_response(user_message, messages)
        else:
            return self._non_stream_response(user_message, messages)

    def _stream_response(self, query: str, messages: List[dict]) -> Generator[str, None, None]:
        """流式响应处理 - 4阶段pipeline"""
        try:
            # 流式开始消息
            yield f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": None}]})}\n\n'

            # 第一阶段：问题优化
            optimize_msg = {
                'choices': [{
                    'delta': {
                        'content': "**🔧 第一阶段：问题优化**\n正在优化查询问题..."
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(optimize_msg)}\n\n"

            optimized_query = self._stage1_optimize_query(query, messages)

            optimize_result_msg = {
                'choices': [{
                    'delta': {
                        'content': f"\n✅ 问题优化完成\n优化后查询: {optimized_query}\n"
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(optimize_result_msg)}\n\n"

            # 第二阶段：搜索
            search_msg = {
                'choices': [{
                    'delta': {
                        'content': "\n**🔍 第二阶段：SearxNG搜索**\n正在搜索相关信息..."
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(search_msg)}\n\n"

            search_results, search_status, search_links = self._stage2_search(optimized_query)

            search_result_msg = {
                'choices': [{
                    'delta': {
                        'content': f"\n{search_status}\n"
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(search_result_msg)}\n\n"

            # 第三阶段：生成LightRAG查询
            lightrag_gen_msg = {
                'choices': [{
                    'delta': {
                        'content': "\n**🧠 第三阶段：生成LightRAG查询**\n正在分析搜索结果并生成增强查询..."
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(lightrag_gen_msg)}\n\n"

            lightrag_query = self._stage3_generate_lightrag_query(query, search_results, messages)

            lightrag_gen_result_msg = {
                'choices': [{
                    'delta': {
                        'content': f"\n✅ LightRAG查询生成完成\n增强查询: {lightrag_query[:100]}{'...' if len(lightrag_query) > 100 else ''}\n"
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(lightrag_gen_result_msg)}\n\n"

            # 第四阶段：LightRAG问答
            lightrag_answer_msg = {
                'choices': [{
                    'delta': {
                        'content': "\n**💭 第四阶段：LightRAG问答**\n"
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(lightrag_answer_msg)}\n\n"

            # 流式生成LightRAG回答
            try:
                for chunk_data in self._stage4_query_lightrag(lightrag_query, stream=True):
                    yield chunk_data
            except Exception as e:
                error_msg = {
                    'choices': [{
                        'delta': {
                            'content': f"\n❌ LightRAG查询失败: {str(e)}"
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(error_msg)}\n\n"

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
            error_msg = f"❌ Pipeline执行失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"Stream error: {e}")
            yield f'data: {json.dumps({"choices": [{"delta": {"content": error_msg}}]})}\n\n'

        yield "data: [DONE]\n\n"

    def _non_stream_response(self, query: str, messages: List[dict]) -> str:
        """非流式响应处理 - 4阶段pipeline"""
        try:
            # 第一阶段：问题优化
            optimized_query = self._stage1_optimize_query(query, messages)

            # 第二阶段：搜索
            search_results, search_status, search_links = self._stage2_search(optimized_query)

            # 第三阶段：生成LightRAG查询
            lightrag_query = self._stage3_generate_lightrag_query(query, search_results, messages)

            # 第四阶段：LightRAG问答
            final_answer = self._stage4_query_lightrag(lightrag_query, stream=False)

            # 构建完整响应
            response_parts = []
            response_parts.append(f"**🔧 第一阶段：问题优化**\n原始问题: {query}\n优化后查询: {optimized_query}")
            response_parts.append(f"\n**🔍 第二阶段：SearxNG搜索**\n{search_status}")

            if search_results and "搜索错误" not in search_results:
                # 显示搜索结果摘要
                lines = search_results.split('\n')
                summary_lines = []
                for line in lines[:8]:  # 只显示前8行
                    if line.strip():
                        summary_lines.append(line)
                if len(lines) > 8:
                    summary_lines.append("...")
                response_parts.append(f"\n搜索摘要:\n" + "\n".join(summary_lines))

            response_parts.append(f"\n**🧠 第三阶段：LightRAG查询生成**\n增强查询: {lightrag_query[:150]}{'...' if len(lightrag_query) > 150 else ''}")
            response_parts.append(f"\n**💭 第四阶段：LightRAG问答**\n{final_answer}")

            # 添加token统计信息
            token_stats = self._get_token_stats()
            token_info = f"\n\n---\n**Token消耗统计**\n- 输入Token: {token_stats['input_tokens']:,}\n- 输出Token: {token_stats['output_tokens']:,}\n- 总Token: {token_stats['total_tokens']:,}"

            # 添加配置信息
            config_info = f"\n\n**配置信息**\n- 搜索结果数量: {self.valves.SEARXNG_SEARCH_COUNT}\n- LightRAG模式: {self.valves.LIGHTRAG_DEFAULT_MODE}\n- 模型: {self.valves.OPENAI_MODEL}"

            return "\n".join(response_parts) + token_info + config_info

        except Exception as e:
            error_msg = f"❌ Pipeline执行失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"Non-stream error: {e}")
            return error_msg