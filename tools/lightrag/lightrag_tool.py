"""
title: LightRAG Query Tool
author: Assistant
version: 1.0
license: MIT
description: A tool for querying LightRAG knowledge base with support for multiple query modes
"""

import json
import requests
from typing import Callable, Any, Optional
from pydantic import BaseModel, Field

EmitterType = Optional[Callable[[dict], Any]]


class EventEmitter:
    def __init__(self, event_emitter: EmitterType):
        self.event_emitter = event_emitter

    async def emit(self, event_type: str, data: dict):
        if self.event_emitter:
            await self.event_emitter({"type": event_type, "data": data})

    async def update_status(
        self, description: str, done: bool, action: str
    ):
        await self.emit(
            "status",
            {"done": done, "action": action, "description": description},
        )

    async def send_citation(self, title: str, url: str, content: str):
        await self.emit(
            "citation",
            {
                "document": [content],
                "metadata": [{"name": title, "source": url, "html": False}],
            },
        )


class Tools:
    def __init__(self):
        self.valves = self.Valves()
        
    class Valves(BaseModel):
        LIGHTRAG_BASE_URL: str = Field(
            default="http://117.50.252.245:9621",
            description="LightRAG服务器地址/LightRAG server URL",
        )
        LIGHTRAG_TIMEOUT: int = Field(
            default=30,
            description="查询请求超时时间（秒）/Query request timeout in seconds",
        )
        LIGHTRAG_DEFAULT_MODE: str = Field(
            default="mix",
            description="默认查询模式/Default query mode (naive, local, global, hybrid, mix)",
        )

    async def query_lightrag(
        self,
        query: str = Field(..., description="查询问题，直接输入用户的完整问题或查询语句。例如：'敏感肌肤适合用什么成分的护肤品？'、'维生素C精华液的正确使用方法是什么？'、'如何选择适合自己肤质的粉底液？'。"),
        mode: Optional[str] = None,
        __event_emitter__: EmitterType = None
    ) -> str:
        """
        Query the LightRAG knowledge base. This tool performs knowledge retrieval and returns
        relevant information from the knowledge graph.
        
        Use this tool when users ask about:
        - Specific concepts or entities in the knowledge base
        - Complex questions requiring reasoning across multiple documents
        - Technical information and explanations
        - Any topic that requires knowledge retrieval and synthesis
        
        The tool supports various query modes:
        - naive: Fast document retrieval for simple concept lookup
        - local: Deep dive into specific entities for detailed information
        - global: Relationship reasoning for understanding connections
        - hybrid: Balanced mode for medium complexity questions
        - mix: Most comprehensive retrieval for complex analysis (recommended)

        :param query: 查询问题，直接输入用户的完整问题或查询语句 (e.g., "敏感肌肤适合用什么成分的护肤品？", "维生素C精华液的正确使用方法是什么？", "如何选择适合自己肤质的粉底液？")
        :param mode: 查询模式 (naive, local, global, hybrid, mix), 默认使用配置的默认模式
        :param __event_emitter__: Optional event emitter for status updates
        :return: JSON formatted query results containing knowledge base information
        """
        emitter = EventEmitter(__event_emitter__)
        
        # 验证参数
        if not query or not query.strip():
            await emitter.update_status("查询内容不能为空", True, "lightrag_query")
            return json.dumps({"error": "查询内容不能为空", "success": False}, ensure_ascii=False, indent=2)
        
        # 设置默认模式
        if mode is None:
            mode = self.valves.LIGHTRAG_DEFAULT_MODE
        
        # 验证模式
        valid_modes = ["naive", "local", "global", "hybrid", "mix"]
        if mode not in valid_modes:
            await emitter.update_status(f"无效的查询模式: {mode}", True, "lightrag_query")
            return json.dumps({
                "error": f"无效的查询模式: {mode}，支持的模式: {', '.join(valid_modes)}", 
                "success": False
            }, ensure_ascii=False, indent=2)
        
        await emitter.update_status(
            f"正在查询LightRAG知识库: {query} (模式: {mode})",
            False,
            "lightrag_query"
        )
        
        try:
            # 构建LightRAG API请求
            url = f"{self.valves.LIGHTRAG_BASE_URL.strip().rstrip('/')}/query"
            
            payload = {
                "query": query.strip(),
                "mode": mode
            }
            
            headers = {"Content-Type": "application/json"}
            
            # 发送查询请求
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.LIGHTRAG_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
            
            # 检查查询结果
            if "error" in result:
                error_msg = f"LightRAG查询失败: {result['error']}"
                await emitter.update_status(error_msg, True, "lightrag_query")
                return json.dumps({"error": result["error"], "success": False}, ensure_ascii=False, indent=2)
            
            # 检查是否有响应内容
            response_content = result.get("response", "")
            if not response_content or not response_content.strip():
                await emitter.update_status("未找到相关知识", True, "lightrag_query")
                return json.dumps({
                    "error": "未找到相关知识内容",
                    "success": False,
                    "query": query,
                    "mode": mode
                }, ensure_ascii=False, indent=2)
            
            # 发送引用信息
            citation_content = f"**查询问题:** {query}\n\n"
            citation_content += f"**查询模式:** {mode}\n\n"
            citation_content += f"**知识内容:**\n{response_content}\n\n"
            
            await emitter.send_citation(
                f"LightRAG查询结果 - {query}", 
                f"lightrag://query?q={query}&mode={mode}", 
                citation_content
            )
            
            success_msg = f"LightRAG查询完成! 成功获取知识内容 (模式: {mode})"
            await emitter.update_status(success_msg, True, "lightrag_query")
            
            prompt = f"""
关键要求：
1. 基于LightRAG检索到的知识内容回答用户问题
2. 充分利用知识库中的信息，提供准确全面的回答
3. 如果知识内容不完整，可以结合你的知识进行补充
4. 保持回答的逻辑性和条理性
5. 突出重要的知识点和结论
6. 如有不确定的信息，请诚实指出"""
            
            # 返回格式化的结果
            formatted_result = {
                "success": True,
                "query": query,
                "mode": mode,
                "response": response_content,
                "source": "lightrag",
                "prompt": prompt,
                "knowledge_info": {
                    "query": query,
                    "mode": mode,
                    "content_length": len(response_content),
                    "has_content": bool(response_content.strip())
                }
            }
            
            return json.dumps(formatted_result, ensure_ascii=False, indent=2)
            
        except requests.exceptions.Timeout:
            error_msg = f"LightRAG查询超时 (超过 {self.valves.LIGHTRAG_TIMEOUT} 秒)"
            await emitter.update_status(error_msg, True, "lightrag_query")
            return json.dumps({"error": error_msg, "success": False}, ensure_ascii=False, indent=2)
        except requests.exceptions.RequestException as e:
            error_msg = f"LightRAG查询请求失败: {str(e)}"
            await emitter.update_status(error_msg, True, "lightrag_query")
            return json.dumps({"error": error_msg, "success": False}, ensure_ascii=False, indent=2)
        except Exception as e:
            error_msg = f"LightRAG查询过程中发生错误: {str(e)}"
            await emitter.update_status(error_msg, True, "lightrag_query")
            return json.dumps({"error": str(e), "success": False}, ensure_ascii=False, indent=2)
