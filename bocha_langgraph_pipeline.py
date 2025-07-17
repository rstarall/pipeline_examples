"""
title: Bocha Search LangGraph Pipeline
author: open-webui
date: 2024-12-20
version: 1.0
license: MIT
description: A 2-stage LangGraph pipeline: 1) Web search using Bocha API, 2) AI-enhanced Q&A with search context
requirements: requests, langgraph, langchain-openai, pydantic
"""

import os
import json
import requests
from typing import List, Union, Generator, Iterator, Annotated, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from langgraph.config import get_stream_writer
from schemas import OpenAIChatMessage


class Pipeline:
    class Valves(BaseModel):
        # 博查搜索API配置
        BOCHA_API_KEY: str
        BOCHA_BASE_URL: str
        BOCHA_SEARCH_COUNT: int
        BOCHA_FRESHNESS: str
        BOCHA_ENABLE_SUMMARY: bool
        BOCHA_TIMEOUT: int
        
        # 大模型配置
        OPENAI_API_KEY: str
        OPENAI_BASE_URL: str
        OPENAI_MODEL: str
        
        # Pipeline配置
        ENABLE_STREAMING: bool
        DEBUG_MODE: bool

    def __init__(self):
        self.name = "Bocha Search LangGraph Pipeline"
        
        self.valves = self.Valves(
            **{
                # 博查搜索配置
                "BOCHA_API_KEY": os.getenv("BOCHA_API_KEY", ""),
                "BOCHA_BASE_URL": os.getenv("BOCHA_BASE_URL", "https://api.bochaai.com/v1"),
                "BOCHA_SEARCH_COUNT": int(os.getenv("BOCHA_SEARCH_COUNT", "8")),
                "BOCHA_FRESHNESS": os.getenv("BOCHA_FRESHNESS", "oneYear"),  # oneDay, oneWeek, oneMonth, oneYear, all
                "BOCHA_ENABLE_SUMMARY": os.getenv("BOCHA_ENABLE_SUMMARY", "true").lower() == "true",
                "BOCHA_TIMEOUT": int(os.getenv("BOCHA_TIMEOUT", "30")),
                
                # 大模型配置
                "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
                "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4o"),
                
                # Pipeline配置
                "ENABLE_STREAMING": os.getenv("ENABLE_STREAMING", "true").lower() == "true",
                "DEBUG_MODE": os.getenv("DEBUG_MODE", "false").lower() == "true",
            }
        )
        
        # 初始化LangGraph
        self._init_langgraph()

    async def on_startup(self):
        print(f"Bocha Search LangGraph Pipeline启动: {__name__}")
        
        # 验证必需的API密钥
        if not self.valves.BOCHA_API_KEY:
            print("❌ 缺少博查API密钥，请设置BOCHA_API_KEY环境变量")
        if not self.valves.OPENAI_API_KEY:
            print("❌ 缺少OpenAI API密钥，请设置OPENAI_API_KEY环境变量")
            
        # 测试博查API连接
        try:
            test_response = self._search_bocha("test query", count=1)
            if "error" not in test_response:
                print("✅ 博查搜索API连接成功")
            else:
                print(f"⚠️ 博查搜索API测试失败: {test_response['error']}")
        except Exception as e:
            print(f"❌ 博查搜索API连接失败: {e}")

    async def on_shutdown(self):
        print(f"Bocha Search LangGraph Pipeline关闭: {__name__}")

    def _search_bocha(self, query: str, count: int = None, freshness: str = None) -> dict:
        """调用博查Web Search API"""
        url = f"{self.valves.BOCHA_BASE_URL}/web-search"

        # 参数验证
        search_count = count or self.valves.BOCHA_SEARCH_COUNT
        if search_count < 1 or search_count > 20:
            search_count = min(max(search_count, 1), 20)  # 限制在1-20之间

        valid_freshness = ["oneDay", "oneWeek", "oneMonth", "oneYear", "all"]
        search_freshness = freshness or self.valves.BOCHA_FRESHNESS
        if search_freshness not in valid_freshness:
            search_freshness = "oneYear"  # 默认值

        payload = {
            "query": query.strip(),
            "count": search_count,
            "freshness": search_freshness,
            "summary": self.valves.BOCHA_ENABLE_SUMMARY
        }

        headers = {
            "Authorization": f"Bearer {self.valves.BOCHA_API_KEY}",
            "Content-Type": "application/json"
        }

        try:
            if self.valves.DEBUG_MODE:
                print(f"博查搜索请求: {payload}")

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.BOCHA_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()

            if self.valves.DEBUG_MODE:
                print(f"博查搜索响应状态: {response.status_code}")

            return result
        except requests.exceptions.Timeout:
            return {"error": "博查搜索超时，请稍后重试"}
        except requests.exceptions.HTTPError as e:
            return {"error": f"博查搜索HTTP错误: {e.response.status_code}"}
        except requests.exceptions.RequestException as e:
            return {"error": f"博查搜索网络错误: {str(e)}"}
        except Exception as e:
            return {"error": f"博查搜索未知错误: {str(e)}"}

    def _format_search_results(self, search_response: dict) -> str:
        """格式化搜索结果为文本"""
        if "error" in search_response:
            return f"搜索错误: {search_response['error']}"

        # 检查响应结构
        if not isinstance(search_response, dict):
            return "搜索响应格式错误"

        web_pages = search_response.get("webPages", {}).get("value", [])
        if not web_pages:
            return "未找到相关搜索结果，请尝试其他关键词"

        formatted_results = []
        total_results = search_response.get("webPages", {}).get("totalEstimatedMatches", 0)

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

    def _generate_custom_stream(self, type: Literal["search", "answer"], content: str):
        """生成自定义流式输出"""
        if not self.valves.ENABLE_STREAMING:
            return
            
        content = f"\n{content}\n"
        custom_stream_writer = get_stream_writer()
        return custom_stream_writer({type: content})

    # LangGraph状态定义
    class State(TypedDict):
        messages: Annotated[list, add_messages]
        query: str
        search_results: str
        final_answer: str

    def _init_langgraph(self):
        """初始化LangGraph"""
        # 初始化LLM
        self.llm = ChatOpenAI(
            model=self.valves.OPENAI_MODEL,
            api_key=self.valves.OPENAI_API_KEY,
            base_url=self.valves.OPENAI_BASE_URL
        )
        
        # 定义图
        graph_builder = StateGraph(Pipeline.State)
        
        # 添加节点
        graph_builder.add_node("search", self._search_node)
        graph_builder.add_node("answer", self._answer_node)
        
        # 定义边
        graph_builder.add_edge(START, "search")
        graph_builder.add_edge("search", "answer")
        graph_builder.add_edge("answer", END)
        
        # 编译图
        self.graph = graph_builder.compile()

    def _search_node(self, state: "Pipeline.State"):
        """搜索节点：使用博查API进行联网搜索"""
        query = state.get("query", "").strip()

        if not query:
            error_msg = "搜索查询为空"
            self._generate_custom_stream("search", f"❌ {error_msg}")
            return {"search_results": error_msg}

        if self.valves.DEBUG_MODE:
            print(f"🔍 开始搜索: {query}")

        try:
            # 调用博查搜索API
            search_response = self._search_bocha(query)
            search_results = self._format_search_results(search_response)

            # 检查搜索是否成功
            if "搜索错误" in search_results or "未找到相关搜索结果" in search_results:
                self._generate_custom_stream("search", f"⚠️ {search_results}")
            else:
                self._generate_custom_stream("search", f"✅ 搜索完成，找到相关信息:\n{search_results}")

            return {"search_results": search_results}

        except Exception as e:
            error_msg = f"搜索节点执行失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"Search node error: {e}")
            self._generate_custom_stream("search", f"❌ {error_msg}")
            return {"search_results": error_msg}

    def _answer_node(self, state: "Pipeline.State"):
        """问答节点：基于搜索结果生成增强回答"""
        query = state.get("query", "").strip()
        search_results = state.get("search_results", "").strip()

        if not query:
            error_msg = "用户问题为空"
            self._generate_custom_stream("answer", f"❌ {error_msg}")
            return {"final_answer": error_msg, "messages": []}

        if not search_results or "搜索错误" in search_results:
            # 如果搜索失败，仍然尝试基于问题本身回答
            fallback_prompt = f"""用户问题: {query}

由于搜索功能暂时不可用，请基于你的知识回答用户问题，并说明这是基于已有知识的回答，可能不包含最新信息。"""

            try:
                response = self.llm.invoke([{"role": "user", "content": fallback_prompt}])
                final_answer = f"⚠️ 搜索功能暂时不可用，以下是基于已有知识的回答：\n\n{response.content}"
                self._generate_custom_stream("answer", final_answer)
                return {"final_answer": final_answer, "messages": [response]}
            except Exception as e:
                error_msg = f"问答节点执行失败: {str(e)}"
                self._generate_custom_stream("answer", f"❌ {error_msg}")
                return {"final_answer": error_msg, "messages": []}

        if self.valves.DEBUG_MODE:
            print(f"💭 开始生成回答，基于搜索结果")

        try:
            # 构建增强提示
            enhanced_prompt = f"""你是一个专业的AI助手，请基于以下搜索结果回答用户问题。

用户问题: {query}

搜索结果:
{search_results}

请遵循以下要求：
1. 基于搜索结果提供准确、详细且有用的回答
2. 如果搜索结果不足以完全回答问题，请说明并提供你能给出的最佳建议
3. 引用相关的搜索结果来源，增强回答的可信度
4. 保持回答的结构清晰，易于理解
5. 如果发现搜索结果中有矛盾信息，请指出并分析"""

            # 调用大模型生成回答
            response = self.llm.invoke([{"role": "user", "content": enhanced_prompt}])
            final_answer = response.content

            # 生成回答阶段的流式输出
            self._generate_custom_stream("answer", final_answer)

            return {"final_answer": final_answer, "messages": [response]}

        except Exception as e:
            error_msg = f"问答节点执行失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"Answer node error: {e}")
            self._generate_custom_stream("answer", f"❌ {error_msg}")
            return {"final_answer": error_msg, "messages": []}

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

        # 准备初始状态
        initial_state = {
            "messages": [],
            "query": user_message,
            "search_results": "",
            "final_answer": ""
        }

        # 根据是否启用流式响应选择不同的处理方式
        if body.get("stream", False) and self.valves.ENABLE_STREAMING:
            return self._stream_response(initial_state)
        else:
            return self._non_stream_response(initial_state)

    def _stream_response(self, initial_state: dict) -> Generator[str, None, None]:
        """流式响应处理"""
        try:
            # 流式开始消息
            yield f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": None}]})}\n\n'

            # 执行LangGraph流式处理
            for event in self.graph.stream(input=initial_state, stream_mode="custom"):
                if self.valves.DEBUG_MODE:
                    print(f"Stream event: {event}")

                search_content = event.get("search", None)
                answer_content = event.get("answer", None)

                # 搜索阶段输出
                if search_content:
                    search_msg = {
                        'choices': [{
                            'delta': {
                                'content': f"**🔍 搜索阶段**\n{search_content}"
                            },
                            'finish_reason': None
                        }]
                    }
                    yield f"data: {json.dumps(search_msg)}\n\n"

                # 回答阶段输出
                if answer_content:
                    answer_msg = {
                        'choices': [{
                            'delta': {
                                'content': f"\n**💭 回答阶段**\n{answer_content}"
                            },
                            'finish_reason': None
                        }]
                    }
                    yield f"data: {json.dumps(answer_msg)}\n\n"

            # 流式结束消息
            yield f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]})}\n\n'

        except Exception as e:
            error_msg = f"❌ Pipeline执行失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"Stream error: {e}")
            yield f'data: {json.dumps({"choices": [{"delta": {"content": error_msg}}]})}\n\n'

        yield "data: [DONE]\n\n"

    def _non_stream_response(self, initial_state: dict) -> str:
        """非流式响应处理"""
        try:
            # 执行完整的LangGraph流程
            final_state = self.graph.invoke(initial_state)

            search_results = final_state.get("search_results", "")
            final_answer = final_state.get("final_answer", "")

            # 构建完整响应
            response_parts = []

            if search_results:
                response_parts.append(f"**🔍 搜索结果**\n{search_results}")

            if final_answer:
                response_parts.append(f"**💭 AI回答**\n{final_answer}")

            if not response_parts:
                return "❌ 未能获取到有效的搜索结果或回答"

            # 添加配置信息
            config_info = f"\n\n---\n**配置信息**\n- 搜索结果数量: {self.valves.BOCHA_SEARCH_COUNT}\n- 时间范围: {self.valves.BOCHA_FRESHNESS}\n- 模型: {self.valves.OPENAI_MODEL}"

            return "\n\n".join(response_parts) + config_info

        except Exception as e:
            error_msg = f"❌ Pipeline执行失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"Non-stream error: {e}")
            return error_msg
