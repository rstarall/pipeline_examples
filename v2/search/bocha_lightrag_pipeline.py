"""
title: Search LightRAG Pipeline
author: open-webui
date: 2024-12-20
version: 1.0
license: MIT
description: A 4-stage pipeline: 1) Query optimization, 2) Web search using Bocha API, 3) Generate enhanced LightRAG query, 4) LightRAG Q&A
requirements: requests, pydantic
"""

import os
import json
import requests
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
    def format_query_optimization_prompt(cls, 
                                       user_query: str, 
                                       messages: List[dict], 
                                       domain: str = None,
                                       max_turns: int = None) -> str:
        """
        格式化查询优化提示模板
        
        Args:
            user_query: 用户当前查询
            messages: 历史消息
            domain: 专业领域（可选）
            max_turns: 最大历史轮次
            
        Returns:
            格式化的提示文本
        """
        context_text = cls.extract_recent_context(messages, max_turns)
        
        if context_text:
            domain_prefix = f"{domain}专业" if domain else ""
            
            return f"""请基于以下对话历史和当前问题，生成一个优化的{domain_prefix}搜索查询。

对话历史:
{context_text}

当前问题: {user_query}

请生成一个更精准、更丰富的搜索查询，要求：
1. 结合对话上下文，理解用户的真实意图
2. 补充相关的关键词和概念
3. 使查询更具体和准确
4. 保持查询简洁但信息丰富
5. 只返回优化后的查询文本，不要其他解释

优化后的查询:"""
        else:
            domain_prefix = f"{domain}专业" if domain else ""
            return f"""请优化以下搜索查询，使其更精准和丰富：

原始问题: {user_query}

请生成一个优化的{domain_prefix}搜索查询，要求：
1. 补充相关的关键词和概念
2. 使查询更具体和准确
3. 保持查询简洁但信息丰富
4. 只返回优化后的查询文本，不要其他解释

优化后的查询:"""

    @classmethod
    def format_lightrag_query_prompt(cls,
                                   original_query: str,
                                   search_results: str,
                                   messages: List[dict],
                                   domain: str = None,
                                   max_turns: int = None) -> str:
        """
        格式化LightRAG查询生成提示模板
        
        Args:
            original_query: 原始用户查询
            search_results: 搜索结果
            messages: 历史消息
            domain: 专业领域
            max_turns: 最大历史轮次
            
        Returns:
            格式化的提示文本
        """
        context_text = cls.extract_recent_context(messages, max_turns)
        
        prompt_content = f"""你是一个专业的知识图谱查询专家，请基于以下信息生成一个详细、精细、带思考的LightRAG检索问题。

用户原始问题: {original_query}

网络搜索结果:
{search_results}"""

        if context_text.strip():
            prompt_content += f"""

对话历史:
{context_text}"""

        domain_context = f"在{domain}专业领域中，" if domain else ""

        prompt_content += f"""

请遵循以下要求生成LightRAG查询：
1. {domain_context}结合用户问题、搜索结果和对话历史，深入理解用户的真实需求
2. 分析搜索结果中的关键信息、实体和关系
3. 生成一个较长、精细、带思考过程的查询问题
4. 查询应该包含：
   - 核心问题的详细描述
   - 相关实体和概念
   - 可能的关联关系
   - 思考角度和分析维度
5. 查询长度应在100-300字之间
6. 只返回生成的LightRAG查询文本，不要其他解释

生成的LightRAG查询:"""

        return prompt_content


class Pipeline:
    class Valves(BaseModel):
        # 博查搜索API配置
        BOCHA_API_KEY: str
        BOCHA_BASE_URL: str
        BOCHA_SEARCH_COUNT: int
        BOCHA_FRESHNESS: str
        BOCHA_ENABLE_SUMMARY: bool
        BOCHA_TIMEOUT: int
        
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
        
        # 历史会话配置
        HISTORY_TURNS: int

    def __init__(self):
        self.name = "Search LightRAG Pipeline"
        # 初始化token统计
        self.token_stats = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        }
        
        self.valves = self.Valves(
            **{
                # 博查搜索配置
                "BOCHA_API_KEY": os.getenv("BOCHA_API_KEY", ""),
                "BOCHA_BASE_URL": os.getenv("BOCHA_BASE_URL", "https://api.bochaai.com/v1"),
                "BOCHA_SEARCH_COUNT": int(os.getenv("BOCHA_SEARCH_COUNT", "8")),
                "BOCHA_FRESHNESS": os.getenv("BOCHA_FRESHNESS", "oneYear"),
                "BOCHA_ENABLE_SUMMARY": os.getenv("BOCHA_ENABLE_SUMMARY", "true").lower() == "true",
                "BOCHA_TIMEOUT": int(os.getenv("BOCHA_TIMEOUT", "30")),
                
                # OpenAI配置
                "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
                "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
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
                
                # 历史会话配置
                "HISTORY_TURNS": int(os.getenv("HISTORY_TURNS", "3")),
            }
        )

    async def on_startup(self):
        print(f"Search LightRAG Pipeline启动: {__name__}")
        
        # 验证必需的API密钥
        if not self.valves.BOCHA_API_KEY:
            print("❌ 缺少博查API密钥，请设置BOCHA_API_KEY环境变量")
        if not self.valves.OPENAI_API_KEY:
            print("❌ 缺少OpenAI API密钥，请设置OPENAI_API_KEY环境变量")
            
        # 测试博查API连接
        if self.valves.BOCHA_API_KEY:
            try:
                print("🔧 开始测试博查API连接...")
                test_response = self._search_bocha("test query", count=1)
                if "error" not in test_response:
                    print("✅ 博查搜索API连接成功")
                else:
                    print(f"⚠️ 博查搜索API测试失败: {test_response['error']}")
            except Exception as e:
                print(f"❌ 博查搜索API连接失败: {e}")
        else:
            print("⚠️ 跳过博查API测试（未设置API密钥）")
            
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
        print(f"Search LightRAG Pipeline关闭: {__name__}")

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

    def _search_bocha(self, query: str, count: int = None) -> dict:
        """调用博查Web Search API"""
        url = f"{self.valves.BOCHA_BASE_URL}/web-search"

        search_count = count or self.valves.BOCHA_SEARCH_COUNT
        if search_count < 1 or search_count > 20:
            search_count = min(max(search_count, 1), 20)

        payload = {
            "query": query.strip(),
            "count": search_count,
            "summary": self.valves.BOCHA_ENABLE_SUMMARY
        }

        headers = {
            "Authorization": f"Bearer {self.valves.BOCHA_API_KEY}",
            "Content-Type": "application/json"
        }

        try:
            if self.valves.DEBUG_MODE:
                print(f"🔍 博查搜索: {query}")

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.BOCHA_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()

            if self.valves.DEBUG_MODE:
                print(f"✅ 搜索成功，获得 {len(result.get('data', {}).get('webPages', {}).get('value', []))} 条结果")

            return result
        except Exception as e:
            error_msg = f"博查搜索失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            return {"error": error_msg}

    def _format_search_results(self, search_response: dict) -> str:
        """格式化搜索结果为文本"""
        if "error" in search_response:
            return f"搜索错误: {search_response['error']}"

        data = search_response.get("data", {})
        if not data:
            return "搜索响应数据为空"

        web_pages_data = data.get("webPages", {})
        web_pages = web_pages_data.get("value", [])

        if not web_pages:
            return "未找到相关搜索结果"

        formatted_results = []
        for i, page in enumerate(web_pages[:self.valves.BOCHA_SEARCH_COUNT], 1):
            title = page.get("name", "无标题").strip()
            url = page.get("url", "").strip()
            snippet = page.get("snippet", "").strip()
            summary = page.get("summary", "").strip()

            result_text = f"{i}. {title}\n"
            if url:
                result_text += f"   链接: {url}\n"
            
            content_to_show = summary if summary else snippet
            if content_to_show:
                if len(content_to_show) > 200:
                    content_to_show = content_to_show[:200] + "..."
                result_text += f"   内容: {content_to_show}\n"

            formatted_results.append(result_text)

        return "\n".join(formatted_results)

    def _extract_search_links(self, search_response: dict) -> str:
        """提取搜索结果中的链接，格式化为MD格式"""
        if "error" in search_response:
            return ""

        data = search_response.get("data", {})
        if not data:
            return ""

        web_pages_data = data.get("webPages", {})
        web_pages = web_pages_data.get("value", [])

        if not web_pages:
            return ""

        formatted_links = []
        for i, page in enumerate(web_pages[:self.valves.BOCHA_SEARCH_COUNT], 1):
            title = page.get("name", "无标题").strip()
            url = page.get("url", "").strip()

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

    def _parse_stream_response(self, response) -> Iterator[dict]:
        """解析流式响应"""
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = line[6:]
                    if data.strip() == '[DONE]':
                        break
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue

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
        """第一阶段：LLM问题优化"""
        # 使用新的历史上下文管理器
        prompt_content = HistoryContextManager.format_query_optimization_prompt(
            user_query=user_query,
            messages=messages,
            max_turns=self.valves.HISTORY_TURNS
        )
        
        context_messages = [{"role": "user", "content": prompt_content}]

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
        search_response = self._search_bocha(optimized_query)
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
        """第三阶段：根据搜索结果生成增强的LightRAG查询"""
        # 使用新的历史上下文管理器
        prompt_content = HistoryContextManager.format_lightrag_query_prompt(
            original_query=original_query,
            search_results=search_results,
            messages=messages,
            max_turns=self.valves.HISTORY_TURNS
        )
        
        query_messages = [{"role": "user", "content": prompt_content}]

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
        self, user_message: str, model_id: str, messages: List[dict], body: dict
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
        if not self.valves.BOCHA_API_KEY:
            return "❌ 错误：缺少博查API密钥，请在配置中设置BOCHA_API_KEY"

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
                        'content': "\n**🔍 第二阶段：网络搜索**\n正在搜索相关信息..."
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
            response_parts.append(f"\n**🔍 第二阶段：网络搜索**\n{search_status}")

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
            config_info = f"\n\n**配置信息**\n- 搜索结果数量: {self.valves.BOCHA_SEARCH_COUNT}\n- LightRAG模式: {self.valves.LIGHTRAG_DEFAULT_MODE}\n- 模型: {self.valves.OPENAI_MODEL}"

            return "\n".join(response_parts) + token_info + config_info

        except Exception as e:
            error_msg = f"❌ Pipeline执行失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"Non-stream error: {e}")
            return error_msg
