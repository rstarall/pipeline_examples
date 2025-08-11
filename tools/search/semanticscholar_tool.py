"""
title: Semantic Scholar Academic Paper Search Tool
author: Assistant
version: 1.0
license: MIT
description: A tool for searching academic papers using Semantic Scholar MCP service
"""

import asyncio
import aiohttp
import json
import time
from typing import Callable, Any, Optional, List, Dict
from pydantic import BaseModel, Field

EmitterType = Optional[Callable[[dict], Any]]


class EventEmitter:
    def __init__(self, event_emitter: EmitterType):
        self.event_emitter = event_emitter

    async def emit(self, event_type: str, data: dict):
        if self.event_emitter:
            await self.event_emitter({"type": event_type, "data": data})

    async def update_status(
        self, description: str, done: bool, action: str, urls: List[str] = None
    ):
        await self.emit(
            "status",
            {"done": done, "action": action, "description": description, "urls": urls or []},
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
        self.session_id = None
        self._session_initialized = False
        
    class Valves(BaseModel):
        MCP_SERVER_URL: str = Field(
            default="http://localhost:8992",
            description="Semantic Scholar MCP服务器地址/MCP server URL for Semantic Scholar service",
        )
        MCP_TIMEOUT: int = Field(
            default=30,
            description="MCP服务连接超时时间（秒）/MCP service connection timeout in seconds",
        )
        DEFAULT_LIMIT: int = Field(
            default=10,
            description="默认搜索论文数量/Default number of papers to search",
        )
        MAX_LIMIT: int = Field(
            default=50,
            description="最大搜索论文数量限制/Maximum limit for paper search",
        )

    async def _initialize_mcp_session(self) -> bool:
        if self._session_initialized:
            return True
            
        if not self.valves.MCP_SERVER_URL:
            raise Exception("MCP服务器地址未配置")
        
        try:
            mcp_url = f"{self.valves.MCP_SERVER_URL.strip().rstrip('/')}/mcp"
            
            # Step 1: 发送initialize请求
            initialize_request = {
                "jsonrpc": "2.0",
                "method": "initialize", 
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "sampling": {},
                        "roots": {"listChanged": True}
                    },
                    "clientInfo": {
                        "name": "Semantic Scholar Tool",
                        "version": "1.0.0"
                    }
                },
                "id": "init-1"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    mcp_url,
                    json=initialize_request,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"
                    },
                    timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                ) as response:
                    if response.status == 200:
                        # 检查响应头中的session ID
                        server_session_id = response.headers.get("Mcp-Session-Id")
                        if server_session_id:
                            self.session_id = server_session_id
                        
                        # 处理响应
                        content_type = response.headers.get("Content-Type", "")
                        
                        if "text/event-stream" in content_type:
                            # 处理SSE流
                            init_response = None
                            async for line in response.content:
                                line_str = line.decode('utf-8').strip()
                                if line_str.startswith('data: '):
                                    try:
                                        data = json.loads(line_str[6:])
                                        if data.get("id") == "init-1":
                                            init_response = data
                                            break
                                    except json.JSONDecodeError:
                                        continue
                        else:
                            init_response = await response.json()
                        
                        if not init_response:
                            raise Exception("No initialize response received")
                        
                        if "error" in init_response:
                            raise Exception(f"MCP initialize error: {init_response['error']}")
                        
                        # Step 2: 发送initialized通知
                        initialized_notification = {
                            "jsonrpc": "2.0",
                            "method": "notifications/initialized"
                        }
                        
                        headers = {
                            "Content-Type": "application/json",
                            "Accept": "application/json, text/event-stream"
                        }
                        if self.session_id:
                            headers["Mcp-Session-Id"] = self.session_id
                        
                        async with session.post(
                            mcp_url,
                            json=initialized_notification,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                        ) as notify_response:
                            if notify_response.status not in [200, 202]:
                                pass  # 忽略initialized通知失败
                        
                        self._session_initialized = True
                        return True
                    else:
                        error_text = await response.text()
                        raise Exception(f"Initialize failed - HTTP {response.status}: {error_text}")
                        
        except Exception as e:
            raise Exception(f"MCP会话初始化失败: {e}")

    async def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self.valves.MCP_SERVER_URL:
            return {"error": "MCP服务器地址未配置"}
        
        # 确保会话已初始化
        if not self._session_initialized:
            await self._initialize_mcp_session()
        
        try:
            mcp_url = f"{self.valves.MCP_SERVER_URL.strip().rstrip('/')}/mcp"
            
            # MCP JSON-RPC格式请求体
            jsonrpc_payload = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                },
                "id": f"mcp_{tool_name}_{int(time.time())}"
            }
            
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
            if self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    mcp_url,
                    headers=headers,
                    json=jsonrpc_payload,
                    timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                ) as response:
                    if response.status == 200:
                        content_type = response.headers.get("Content-Type", "")
                        if "text/event-stream" in content_type:
                            # 处理SSE流
                            result = None
                            request_id = jsonrpc_payload["id"]
                            async for line in response.content:
                                line_str = line.decode('utf-8').strip()
                                if line_str.startswith('data: '):
                                    try:
                                        data = json.loads(line_str[6:])
                                        if data.get("id") == request_id:
                                            result = data
                                            break
                                    except json.JSONDecodeError:
                                        continue
                        else:
                            result = await response.json()
                        
                        if not result:
                            return {"error": "No response received"}
                        
                        # 处理MCP JSON-RPC响应
                        if "result" in result:
                            return result["result"]
                        elif "error" in result:
                            return {"error": f"MCP错误: {result['error'].get('message', 'Unknown error')}"}
                        else:
                            return {"error": "无效的MCP响应格式"}
                    else:
                        return {"error": f"HTTP {response.status}: {await response.text()}"}
                        
        except asyncio.TimeoutError:
            return {"error": "请求超时"}
        except aiohttp.ClientError as e:
            return {"error": f"HTTP请求失败: {str(e)}"}
        except Exception as e:
            return {"error": f"MCP工具调用失败: {str(e)}"}

    async def search_academic_papers(
        self,
        query: str = Field(..., description="The search query for academic papers using English "),
        limit: Optional[int] = None,
        offset: int = 0,
        __event_emitter__: EmitterType = None
    ) -> str:
        """
        Search academic papers using Semantic Scholar database. This tool searches for scholarly articles, 
        research papers, and academic publications based on the provided query terms.
        
        Use this tool when users ask about:
        - Scientific research papers
        - Academic literature search
        - Scholar articles on specific topics
        - Research publications by authors
        - Citations and academic references
        - Peer-reviewed papers
        - Conference papers and journal articles
        
        The tool supports complex academic queries including author names, technical terms, 
        research topics, and specific methodologies.

        :param query: The search query for academic papers using English (e.g., "machine learning", "author:John Smith", "deep learning medical imaging")
        :param limit: Maximum number of papers to return (default: configured default, max: configured max)  
        :param offset: Number of papers to skip for pagination (default: 0)
        :param __event_emitter__: Optional event emitter for status updates
        :return: JSON formatted search results containing paper details
        """
        emitter = EventEmitter(__event_emitter__)
        
        # 验证参数
        if not query or not query.strip():
            await emitter.update_status("搜索查询不能为空", True, "search_papers")
            return json.dumps({"error": "搜索查询不能为空", "success": False}, ensure_ascii=False, indent=2)
        
        # 设置默认值和限制
        if limit is None:
            limit = self.valves.DEFAULT_LIMIT
        limit = min(limit, self.valves.MAX_LIMIT)
        offset = max(0, offset)
        
        await emitter.update_status(
            f"正在搜索学术论文: {query} (限制: {limit}篇, 偏移: {offset})",
            False,
            "search_papers"
        )
        
        try:
            # 调用MCP工具执行搜索
            tool_args = {
                "query": query.strip(),
                "limit": limit,
                "offset": offset
            }
            
            result = await self._call_mcp_tool("search_papers", tool_args)
            
            # 检查是否有错误
            if "error" in result:
                error_msg = f"搜索失败: {result['error']}"
                await emitter.update_status(error_msg, True, "search_papers")
                return json.dumps({"error": result["error"], "success": False}, ensure_ascii=False, indent=2)
            
            # 处理搜索结果
            papers = result.get("results", [])
            total_count = result.get("total_count", len(papers))
            
            # 为找到的论文发送引用信息
            for paper in papers:
                title = paper.get("title", "Unknown Title")
                url = paper.get("url", "")
                abstract = paper.get("abstract", "No abstract available")
                
                # 构建引用内容
                authors = paper.get("authors", [])
                author_names = ", ".join([author.get("name", "") for author in authors[:3]])
                if len(authors) > 3:
                    author_names += " et al."
                
                citation_content = f"**{title}**\n\n"
                if author_names:
                    citation_content += f"**Authors:** {author_names}\n\n"
                if paper.get("year"):
                    citation_content += f"**Year:** {paper.get('year')}\n\n"
                if paper.get("venue"):
                    citation_content += f"**Venue:** {paper.get('venue')}\n\n"
                if paper.get("citation_count"):
                    citation_content += f"**Citations:** {paper.get('citation_count')}\n\n"
                if abstract:
                    citation_content += f"**Abstract:** {abstract}\n"
                
                await emitter.send_citation(title, url, citation_content)
            
            success_msg = f"搜索完成! 找到 {len(papers)} 篇论文 (总共 {total_count} 篇相关论文)"
            await emitter.update_status(success_msg, True, "search_papers")
            
            # 返回格式化的结果
            formatted_result = {
                "success": True,
                "query": query,
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "returned_count": len(papers),
                "results": papers
            }
            
            return json.dumps(formatted_result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            error_msg = f"搜索过程中发生错误: {str(e)}"
            await emitter.update_status(error_msg, True, "search_papers")
            return json.dumps({"error": str(e), "success": False}, ensure_ascii=False, indent=2)
