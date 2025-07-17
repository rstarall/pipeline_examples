"""
title: Bocha Search OpenAI Pipeline
author: open-webui
date: 2024-12-20
version: 2.0
license: MIT
description: A 3-stage pipeline: 1) LLM query optimization, 2) Web search using Bocha API, 3) AI-enhanced Q&A with OpenAI API
requirements: requests, pydantic
"""

import os
import json
import requests
from typing import List, Union, Generator, Iterator
from pydantic import BaseModel


class Pipeline:
    class Valves(BaseModel):
        # 博查搜索API配置
        BOCHA_API_KEY: str
        BOCHA_BASE_URL: str
        BOCHA_SEARCH_COUNT: int
        BOCHA_FRESHNESS: str
        BOCHA_ENABLE_SUMMARY: bool
        BOCHA_TIMEOUT: int

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

    def __init__(self):
        self.name = "Bocha Search OpenAI Pipeline"
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
                "BOCHA_FRESHNESS": os.getenv("BOCHA_FRESHNESS", "oneYear"),  # oneDay, oneWeek, oneMonth, oneYear, all
                "BOCHA_ENABLE_SUMMARY": os.getenv("BOCHA_ENABLE_SUMMARY", "true").lower() == "true",
                "BOCHA_TIMEOUT": int(os.getenv("BOCHA_TIMEOUT", "30")),
                
                # OpenAI配置
                "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
                "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4o"),
                "OPENAI_TIMEOUT": int(os.getenv("OPENAI_TIMEOUT", "60")),
                "OPENAI_MAX_TOKENS": int(os.getenv("OPENAI_MAX_TOKENS", "4000")),
                "OPENAI_TEMPERATURE": float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
                
                # Pipeline配置
                "ENABLE_STREAMING": os.getenv("ENABLE_STREAMING", "true").lower() == "true",
                "DEBUG_MODE": os.getenv("DEBUG_MODE", "true").lower() == "true",  # 临时强制启用调试
            }
        )

    async def on_startup(self):
        print(f"Bocha Search OpenAI Pipeline启动: {__name__}")
        
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

    async def on_shutdown(self):
        print(f"Bocha Search OpenAI Pipeline关闭: {__name__}")

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

        # 参数验证
        search_count = count or self.valves.BOCHA_SEARCH_COUNT
        if search_count < 1 or search_count > 20:
            search_count = min(max(search_count, 1), 20)  # 限制在1-20之间

        # 根据示例，去掉freshness参数，只保留核心参数
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
            # 添加详细的调试信息
            if self.valves.DEBUG_MODE:
                print("🔍 博查搜索调试信息:")
                print(f"   URL: {url}")
                print(f"   API Key前缀: {self.valves.BOCHA_API_KEY[:10]}..." if self.valves.BOCHA_API_KEY else "   API Key: 未设置")
                print(f"   请求载荷: {json.dumps(payload, ensure_ascii=False, indent=2)}")
                print(f"   请求头: {headers}")

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.BOCHA_TIMEOUT
            )

            # 添加响应调试信息
            if self.valves.DEBUG_MODE:
                print(f"   响应状态码: {response.status_code}")
                print(f"   响应头: {dict(response.headers)}")
                if response.status_code != 200:
                    print(f"   响应内容: {response.text}")

            response.raise_for_status()
            result = response.json()

            if self.valves.DEBUG_MODE:
                print(f"   响应成功，数据长度: {len(str(result))}")
                # 打印响应结构以便调试
                if isinstance(result, dict):
                    print(f"   响应结构: code={result.get('code')}, msg={result.get('msg')}")
                    data = result.get('data', {})
                    if data:
                        web_pages = data.get('webPages', {})
                        if web_pages:
                            value_count = len(web_pages.get('value', []))
                            print(f"   搜索结果数量: {value_count}")

            return result
        except requests.exceptions.Timeout:
            error_msg = "博查搜索超时，请稍后重试"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            return {"error": error_msg}
        except requests.exceptions.HTTPError as e:
            error_msg = f"博查搜索HTTP错误: {e.response.status_code}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
                if hasattr(e.response, 'text'):
                    print(f"   错误详情: {e.response.text}")
            return {"error": error_msg}
        except requests.exceptions.RequestException as e:
            error_msg = f"博查搜索网络错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"博查搜索未知错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            return {"error": error_msg}

    def _format_search_results(self, search_response: dict) -> str:
        """格式化搜索结果为文本"""
        if "error" in search_response:
            return f"搜索错误: {search_response['error']}"

        # 检查响应结构
        if not isinstance(search_response, dict):
            return "搜索响应格式错误"

        # 检查博查API的响应结构：response.data.webPages.value
        data = search_response.get("data", {})
        if not data:
            return "搜索响应数据为空"

        web_pages_data = data.get("webPages", {})
        web_pages = web_pages_data.get("value", [])

        if not web_pages:
            return "未找到相关搜索结果，请尝试其他关键词"

        formatted_results = []
        total_results = web_pages_data.get("totalEstimatedMatches", 0)

        # 添加搜索统计信息
        if total_results > 0:
            formatted_results.append(f"找到约 {total_results:,} 条相关结果\n")

        for i, page in enumerate(web_pages[:self.valves.BOCHA_SEARCH_COUNT], 1):
            title = page.get("name", "无标题").strip()
            url = page.get("url", "").strip()
            snippet = page.get("snippet", "").strip()
            summary = page.get("summary", "").strip()
            site_name = page.get("siteName", "").strip()
            date_published = page.get("datePublished", "").strip()

            result_text = f"**{i}. {title}**\n"

            if site_name:
                result_text += f"   来源: {site_name}\n"

            if date_published:
                result_text += f"   发布时间: {date_published}\n"

            if url:
                result_text += f"   链接: {url}\n"

            # 优先显示详细摘要，如果没有则显示普通摘要
            content_to_show = summary if summary else snippet
            if content_to_show:
                # 限制摘要长度，避免过长
                if len(content_to_show) > 300:
                    content_to_show = content_to_show[:300] + "..."
                result_text += f"   内容: {content_to_show}\n"

            formatted_results.append(result_text)

        return "\n".join(formatted_results)

    def _extract_search_links(self, search_response: dict) -> str:
        """提取搜索结果中的链接，格式化为MD格式"""
        if "error" in search_response:
            return ""

        # 检查响应结构
        if not isinstance(search_response, dict):
            return ""

        # 检查博查API的响应结构：response.data.webPages.value
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

        except requests.exceptions.Timeout:
            raise Exception("OpenAI API超时，请稍后重试")
        except requests.exceptions.HTTPError as e:
            raise Exception(f"OpenAI API HTTP错误: {e.response.status_code}")
        except requests.exceptions.RequestException as e:
            raise Exception(f"OpenAI API网络错误: {str(e)}")
        except Exception as e:
            raise Exception(f"OpenAI API未知错误: {str(e)}")

    def _parse_stream_response(self, response) -> Iterator[dict]:
        """解析流式响应"""
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = line[6:]  # 移除 'data: ' 前缀
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
                    data = line[6:]  # 移除 'data: ' 前缀
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
        # 构建历史对话上下文
        context_messages = []
        if messages and len(messages) > 1:
            # 获取最近的几轮对话作为上下文
            recent_messages = messages[-6:]  # 最多取最近3轮对话（用户+助手）
            context_text = ""
            for msg in recent_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    context_text += f"用户: {content}\n"
                elif role == "assistant":
                    context_text += f"助手: {content}\n"

            if context_text.strip():
                context_messages.append({
                    "role": "user",
                    "content": f"""请基于以下对话历史和当前问题，生成一个优化的搜索查询。

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
                })

        # 如果没有历史对话，直接优化当前问题
        if not context_messages:
            context_messages.append({
                "role": "user",
                "content": f"""请优化以下搜索查询，使其更精准和丰富：

原始问题: {user_query}

请生成一个优化的搜索查询，要求：
1. 补充相关的关键词和概念
2. 使查询更具体和准确
3. 保持查询简洁但信息丰富
4. 只返回优化后的查询文本，不要其他解释

优化后的查询:"""
            })

        try:
            response = self._call_openai_api(context_messages, stream=False)
            optimized_query = response['choices'][0]['message']['content'].strip()

            # 如果优化失败或返回空，使用原始查询
            if not optimized_query or len(optimized_query) < 3:
                optimized_query = user_query

            if self.valves.DEBUG_MODE:
                print(f"🔧 查询优化: '{user_query}' → '{optimized_query}'")

            return optimized_query

        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ 查询优化失败: {e}")
            return user_query  # 优化失败时返回原始查询

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

    def _stage3_answer(self, original_query: str, optimized_query: str, search_results: str, search_links: str, messages: List[dict], stream: bool = False) -> Union[str, Iterator[str]]:
        """第三阶段：基于搜索结果生成增强回答"""

        # 构建历史对话上下文
        context_text = ""
        if messages and len(messages) > 1:
            # 获取最近的几轮对话作为上下文
            recent_messages = messages[-4:]  # 最多取最近2轮对话
            for msg in recent_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    context_text += f"用户: {content}\n"
                elif role == "assistant":
                    context_text += f"助手: {content}\n"

        if not search_results or "搜索错误" in search_results:
            # 如果搜索失败，仍然尝试基于问题本身回答
            prompt_content = f"""用户问题: {original_query}

由于搜索功能暂时不可用，请基于你的知识回答用户问题，并说明这是基于已有知识的回答，可能不包含最新信息。"""

            if context_text.strip():
                prompt_content = f"""对话历史:
{context_text}

当前问题: {original_query}

由于搜索功能暂时不可用，请基于你的知识和对话上下文回答用户问题，并说明这是基于已有知识的回答，可能不包含最新信息。"""
        else:
            # 构建增强提示
            prompt_content = f"""你是一个专业的AI助手，请基于以下信息回答用户问题。

用户原始问题: {original_query}
优化后的搜索查询: {optimized_query}

搜索结果:
{search_results}"""

            if context_text.strip():
                prompt_content += f"""

对话历史:
{context_text}"""

            prompt_content += """

请遵循以下要求：
1. 结合对话历史和搜索结果，提供准确、详细且有用的回答
2. 如果搜索结果不足以完全回答问题，请说明并提供你能给出的最佳建议
3. 引用相关的搜索结果来源，增强回答的可信度
4. 保持回答的结构清晰，易于理解
5. 如果发现搜索结果中有矛盾信息，请指出并分析
6. 考虑对话上下文，确保回答的连贯性和相关性"""

        answer_messages = [{
            "role": "user",
            "content": prompt_content
        }]

        if stream:
            return self._call_openai_api(answer_messages, stream=True)
        else:
            response = self._call_openai_api(answer_messages, stream=False)
            return response['choices'][0]['message']['content']

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Generator, Iterator]:
        """
        处理用户查询的主要方法

        Args:
            user_message: 用户输入的消息
            model_id: 模型ID（在此pipeline中未使用，但保留以兼容接口）
            messages: 消息历史（在此pipeline中未使用，但保留以兼容接口）
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
        """流式响应处理"""
        try:
            # 流式开始消息
            yield f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": None}]})}\n\n'

            # 第一阶段：问题优化
            optimize_msg = {
                'choices': [{
                    'delta': {
                        'content': "**🔧 问题优化阶段**\n正在优化查询问题..."
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
                        'content': "\n**🔍 搜索阶段**\n正在搜索相关信息..."
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

            # 第三阶段：生成回答
            answer_start_msg = {
                'choices': [{
                    'delta': {
                        'content': "\n**💭 回答阶段**\n"
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(answer_start_msg)}\n\n"

            # 流式生成回答
            try:
                for chunk in self._stage3_answer(query, optimized_query, search_results, search_links, messages, stream=True):
                    if 'choices' in chunk and len(chunk['choices']) > 0:
                        delta = chunk['choices'][0].get('delta', {})
                        if 'content' in delta:
                            content_msg = {
                                'choices': [{
                                    'delta': {
                                        'content': delta['content']
                                    },
                                    'finish_reason': chunk['choices'][0].get('finish_reason')
                                }]
                            }
                            yield f"data: {json.dumps(content_msg)}\n\n"

                            if chunk['choices'][0].get('finish_reason') == 'stop':
                                break
            except Exception as e:
                error_msg = {
                    'choices': [{
                        'delta': {
                            'content': f"\n❌ 回答生成失败: {str(e)}"
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

            # 流式结束消息
            yield f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]})}\n\n'

        except Exception as e:
            error_msg = f"❌ Pipeline执行失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"Stream error: {e}")
            yield f'data: {json.dumps({"choices": [{"delta": {"content": error_msg}}]})}\n\n'

        yield "data: [DONE]\n\n"

    def _non_stream_response(self, query: str, messages: List[dict]) -> str:
        """非流式响应处理"""
        try:
            # 第一阶段：问题优化
            optimized_query = self._stage1_optimize_query(query, messages)

            # 第二阶段：搜索
            search_results, search_status, search_links = self._stage2_search(optimized_query)

            # 第三阶段：生成回答
            final_answer = self._stage3_answer(query, optimized_query, search_results, search_links, messages, stream=False)

            # 构建完整响应
            response_parts = []
            response_parts.append(f"**� 问题优化**\n原始问题: {query}\n优化后查询: {optimized_query}")
            response_parts.append(f"\n**�🔍 搜索结果**\n{search_status}")

            if search_results and "搜索错误" not in search_results:
                # 只显示搜索结果的摘要，不显示完整内容
                lines = search_results.split('\n')
                summary_lines = []
                for line in lines[:10]:  # 只显示前10行
                    if line.strip():
                        summary_lines.append(line)
                if len(lines) > 10:
                    summary_lines.append("...")
                response_parts.append(f"\n搜索摘要:\n" + "\n".join(summary_lines))

            response_parts.append(f"\n**💭 AI回答**\n{final_answer}")

            # 添加token统计信息
            token_stats = self._get_token_stats()
            token_info = f"\n\n---\n**Token消耗统计**\n- 输入Token: {token_stats['input_tokens']:,}\n- 输出Token: {token_stats['output_tokens']:,}\n- 总Token: {token_stats['total_tokens']:,}"

            # 添加配置信息
            config_info = f"\n\n**配置信息**\n- 搜索结果数量: {self.valves.BOCHA_SEARCH_COUNT}\n- 时间范围: {self.valves.BOCHA_FRESHNESS}\n- 模型: {self.valves.OPENAI_MODEL}"

            return "\n".join(response_parts) + token_info + config_info

        except Exception as e:
            error_msg = f"❌ Pipeline执行失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"Non-stream error: {e}")
            return error_msg
