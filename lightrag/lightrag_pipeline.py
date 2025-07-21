"""
title: LightRAG Pipeline
author: open-webui
date: 2024-12-20
version: 1.0
license: MIT
description: A pipeline for querying LightRAG knowledge base with support for multiple query modes (local, global, hybrid, naive, mix) and conversation history
requirements: requests, sseclient-py
"""

from typing import List, Union, Generator, Iterator
import requests
import json
import os
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
    def enhance_query_with_history(cls, user_query: str, messages: List[dict], max_turns: int = None) -> str:
        """
        使用历史会话上下文增强用户查询
        
        Args:
            user_query: 原始用户查询
            messages: 历史消息
            max_turns: 最大历史轮次
            
        Returns:
            增强后的查询字符串
        """
        context_text = cls.extract_recent_context(messages, max_turns)
        
        if not context_text:
            return user_query
        
        enhanced_query = f"""基于以下对话历史回答问题：

对话历史:
{context_text}

当前问题: {user_query}

请结合对话历史的上下文，提供准确、详细且相关的回答。"""
        
        return enhanced_query


class Pipeline:
    class Valves(BaseModel):
        LIGHTRAG_BASE_URL: str
        LIGHTRAG_DEFAULT_MODE: str
        LIGHTRAG_TIMEOUT: int
        LIGHTRAG_ENABLE_STREAMING: bool
        
        # 历史会话配置
        HISTORY_TURNS: int
        ENABLE_HISTORY_CONTEXT: bool

    def __init__(self):
        self.name = "LightRAG Pipeline"
        
        self.valves = self.Valves(
            **{
                "LIGHTRAG_BASE_URL": os.getenv("LIGHTRAG_BASE_URL", "http://localhost:9621"),
                "LIGHTRAG_DEFAULT_MODE": os.getenv("LIGHTRAG_DEFAULT_MODE", "hybrid"),
                "LIGHTRAG_TIMEOUT": int(os.getenv("LIGHTRAG_TIMEOUT", "30")),
                "LIGHTRAG_ENABLE_STREAMING": os.getenv("LIGHTRAG_ENABLE_STREAMING", "true").lower() == "true",
                
                # 历史会话配置
                "HISTORY_TURNS": int(os.getenv("HISTORY_TURNS", "3")),
                "ENABLE_HISTORY_CONTEXT": os.getenv("ENABLE_HISTORY_CONTEXT", "true").lower() == "true",
            }
        )

    async def on_startup(self):
        print(f"LightRAG Pipeline启动: {__name__}")
        # 测试连接和端点可用性
        try:
            # 测试健康检查端点
            response = requests.get(f"{self.valves.LIGHTRAG_BASE_URL}/health", timeout=5)
            if response.status_code == 200:
                print("✅ LightRAG服务连接成功")

                # 测试查询端点
                test_endpoints = [
                    ("/query", "标准查询端点"),
                    ("/query/stream", "流式查询端点"),
                    ("/api/chat", "Ollama兼容端点")
                ]

                for endpoint, description in test_endpoints:
                    try:
                        test_response = requests.post(
                            f"{self.valves.LIGHTRAG_BASE_URL}{endpoint}",
                            json={"query": "test", "mode": "hybrid"} if endpoint != "/api/chat" else {
                                "model": "lightrag:latest",
                                "messages": [{"role": "user", "content": "test"}],
                                "stream": False
                            },
                            timeout=3
                        )
                        if test_response.status_code in [200, 422]:  # 422可能是参数验证错误，但端点存在
                            print(f"✅ {description}可用")
                        else:
                            print(f"⚠️ {description}响应异常: {test_response.status_code}")
                    except Exception as e:
                        print(f"❌ {description}不可用: {e}")

            else:
                print(f"⚠️ LightRAG服务响应异常: {response.status_code}")
        except Exception as e:
            print(f"❌ 无法连接到LightRAG服务: {e}")

    async def on_shutdown(self):
        print(f"LightRAG Pipeline关闭: {__name__}")

    def _extract_query_mode(self, user_message: str) -> tuple[str, str]:
        """从用户消息中提取查询模式和实际查询内容"""
        mode_prefixes = {
            "/local": "local",
            "/global": "global", 
            "/hybrid": "hybrid",
            "/naive": "naive",
            "/mix": "mix"
        }
        
        for prefix, mode in mode_prefixes.items():
            if user_message.startswith(prefix):
                query = user_message[len(prefix):].strip()
                return mode, query
        
        return self.valves.LIGHTRAG_DEFAULT_MODE, user_message

    def _query_lightrag_standard(self, query: str, mode: str) -> dict:
        """标准查询API"""
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
        """流式查询API - 使用LightRAG的/query/stream端点"""
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

            # LightRAG的流式响应格式是NDJSON，每行一个JSON对象
            for line in response.iter_lines():
                if line:
                    line_text = line.decode('utf-8').strip()
                    if line_text:
                        try:
                            data = json.loads(line_text)
                            # LightRAG流式响应格式: {"response": "chunk_content"}
                            if 'response' in data and data['response']:
                                chunk = data['response']
                                # 转换为OpenAI兼容的流式响应格式
                                yield f'data: {json.dumps({"choices": [{"delta": {"content": chunk}}]})}\n\n'
                            elif 'error' in data:
                                error_msg = data['error']
                                yield f'data: {json.dumps({"choices": [{"delta": {"content": f"错误: {error_msg}"}}]})}\n\n'
                        except json.JSONDecodeError:
                            # 忽略无法解析的行
                            continue

        except Exception as e:
            error_msg = f"流式查询失败: {str(e)}"
            yield f'data: {json.dumps({"choices": [{"delta": {"content": error_msg}}]})}\n\n'

        yield "data: [DONE]\n\n"

    def _query_lightrag_streaming_ollama(self, query: str, mode: str) -> Generator[str, None, None]:
        """备用流式查询API - 使用LightRAG的/api/chat端点（Ollama兼容）"""
        url = f"{self.valves.LIGHTRAG_BASE_URL}/api/chat"

        # 根据模式前缀格式化查询
        formatted_query = f"/{mode} {query}" if mode != "hybrid" else query
        messages = [{"role": "user", "content": formatted_query}]

        payload = {
            "model": "lightrag:latest",
            "messages": messages,
            "stream": True
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

            # Ollama兼容API的流式响应格式是NDJSON
            for line in response.iter_lines():
                if line:
                    line_text = line.decode('utf-8').strip()
                    if line_text:
                        try:
                            data = json.loads(line_text)
                            # Ollama格式: {"message": {"content": "chunk"}, "done": false}
                            if 'message' in data and 'content' in data['message']:
                                chunk = data['message']['content']
                                if chunk:
                                    # 转换为OpenAI兼容的流式响应格式
                                    yield f'data: {json.dumps({"choices": [{"delta": {"content": chunk}}]})}\n\n'

                            # 检查是否完成
                            if data.get('done', False):
                                break

                        except json.JSONDecodeError:
                            # 忽略无法解析的行
                            continue

        except Exception as e:
            error_msg = f"备用流式查询失败: {str(e)}"
            yield f'data: {json.dumps({"choices": [{"delta": {"content": error_msg}}]})}\n\n'

        yield "data: [DONE]\n\n"

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Generator, Iterator]:
        """
        处理用户查询的主要方法

        Args:
            user_message: 用户输入的消息
            model_id: 模型ID（在此pipeline中未使用，但保留以兼容接口）
            messages: 消息历史（现在会被使用来增强查询上下文）
            body: 请求体，包含流式设置和用户信息

        Returns:
            查询结果字符串或流式生成器
        """
        # 提取查询模式和内容
        mode, query = self._extract_query_mode(user_message)
        
        # 如果启用历史上下文且有历史消息，则增强查询
        if self.valves.ENABLE_HISTORY_CONTEXT and messages:
            enhanced_query = HistoryContextManager.enhance_query_with_history(
                user_query=query,
                messages=messages,
                max_turns=self.valves.HISTORY_TURNS
            )
            if enhanced_query != query:  # 如果查询被增强了
                query = enhanced_query
                if body.get("user"):
                    print(f"📜 历史上下文已应用，增强查询长度: {len(query)} 字符")

        # 验证查询内容
        if not query.strip():
            return "请提供有效的查询内容。"
        
        # 打印调试信息
        if "user" in body:
            print("=" * 50)
            print(f"用户: {body['user']['name']} ({body['user']['id']})")
            print(f"查询模式: {mode}")
            print(f"查询内容: {query}")
            print(f"流式响应: {body.get('stream', False)}")
            print(f"启用流式: {self.valves.LIGHTRAG_ENABLE_STREAMING}")
            print("=" * 50)

        # 根据是否启用流式响应选择不同的处理方式
        if body.get("stream", False) and self.valves.LIGHTRAG_ENABLE_STREAMING:
            # 首先尝试使用专用的流式查询端点
            try:
                return self._query_lightrag_streaming(query, mode)
            except Exception as e:
                print(f"主流式端点失败，尝试备用端点: {e}")
                # 如果主端点失败，尝试使用Ollama兼容端点
                return self._query_lightrag_streaming_ollama(query, mode)
        else:
            # 非流式响应
            result = self._query_lightrag_standard(query, mode)
            
            if "error" in result:
                return result["error"]
            
            # 返回查询结果
            response_content = result.get("response", "未获取到响应内容")
            
            # 添加模式信息到响应中
            mode_info = f"\n\n---\n**查询模式**: {mode.upper()}\n**LightRAG服务**: {self.valves.LIGHTRAG_BASE_URL}"
            
            return response_content + mode_info
