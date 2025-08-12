"""
title: PubChemPy Chemical Search Tool
author: Assistant  
version: 1.0
license: MIT
description: A tool for searching chemical information using PubChemPy MCP service
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
            default="http://localhost:8989",
            description="PubChemPy MCP服务器地址/MCP server URL for PubChemPy service",
        )
        MCP_TIMEOUT: int = Field(
            default=30,
            description="MCP服务连接超时时间（秒）/MCP service connection timeout in seconds",
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
                        "name": "PubChemPy Tool",
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
                            payload = result["result"]
                            
                            # FastMCP将工具返回值包装在content中
                            if isinstance(payload, dict) and "content" in payload and payload["content"]:
                                # 提取文本内容
                                text_content = ""
                                for content in payload["content"]:
                                    if content.get("type") == "text":
                                        text_content += content.get("text", "") + "\n"
                                
                                if text_content:
                                    try:
                                        # 解析JSON字符串为字典
                                        return json.loads(text_content.strip())
                                    except json.JSONDecodeError:
                                        # 如果不是JSON，返回原始文本
                                        return {"raw_text": text_content.strip()}
                                
                                # content存在但为空
                                return {"error": "Empty content received"}
                            
                            # 直接返回payload（兼容性处理）
                            return payload
                            
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

    async def search_chemical(
        self,
        query: str = Field(..., description="Chemical search query - compound name in English, molecular formula (e.g., 'H2O', 'C6H12O6'), or SMILES string (e.g., 'CCO', 'c1ccccc1').MUST BE IN ENGLISH ONLY. If you have a Chinese compound name, please convert it to the English professional academic name first."),
        search_type: str = "name",
        __event_emitter__: EmitterType = None
    ) -> str:
        """
        Search chemical compounds using PubChemPy database. This tool searches for chemical information 
        including compound properties, molecular structures, and related data.
        
        Use this tool when users ask about:
        - Chemical compound information and properties
        - Molecular formulas and structures  
        - Chemical names and synonyms
        - SMILES strings and InChI data
        - Drug information and pharmaceutical data
        - Chemical identifiers (CID, CAS, etc.)
        
        The tool supports multiple search types:
        - name: Search by compound name (English professional academic name)
        - formula: Search by molecular formula (e.g., C8H10N4O2)
        - smiles: Search by SMILES string (e.g., CCO for ethanol)

        :param query: Chemical search query - English compound name, molecular formula, or SMILES string (convert Chinese names to English first)
        :param search_type: Type of search - 'name' for compound name search, 'formula' for molecular formula search, 'smiles' for SMILES structure search (default: 'name')
        :param __event_emitter__: Optional event emitter for status updates
        :return: JSON formatted search results containing chemical compound details
        """
        emitter = EventEmitter(__event_emitter__)
        
        # 验证参数
        if not query or not query.strip():
            await emitter.update_status("搜索查询不能为空", True, "search_chemical")
            return json.dumps({"error": "搜索查询不能为空", "success": False}, ensure_ascii=False, indent=2)
        
        # 验证搜索类型
        valid_search_types = ["name", "formula", "smiles"]
        if search_type not in valid_search_types:
            await emitter.update_status(f"无效的搜索类型，支持的类型: {', '.join(valid_search_types)}", True, "search_chemical")
            return json.dumps({"error": f"无效的搜索类型，支持的类型: {', '.join(valid_search_types)}", "success": False}, ensure_ascii=False, indent=2)
        
        await emitter.update_status(
            f"正在搜索化学化合物: {query} (搜索类型: {search_type})",
            False,
            "search_chemical"
        )
        
        try:
            # 调用MCP工具执行搜索
            tool_args = {
                "query": query.strip(),
                "search_type": search_type
            }
            
            result = await self._call_mcp_tool("search_chemical", tool_args)
            
            # 检查MCP调用是否成功
            if "error" in result and result["error"]:
                error_msg = f"MCP调用失败: {result['error']}"
                await emitter.update_status(error_msg, True, "search_chemical")
                return json.dumps({"error": result["error"], "success": False}, ensure_ascii=False, indent=2)
            
            # 检查搜索是否成功
            if not result.get("success", False):
                # 获取具体的错误信息
                server_error = result.get("error")
                if server_error:
                    error_msg = f"化学搜索失败: {server_error}"
                else:
                    error_msg = f"化学搜索失败: 未找到匹配的化合物 (查询: {query}, 搜索类型: {search_type})"
                
                await emitter.update_status(error_msg, True, "search_chemical")
                
                # 添加调试信息
                debug_info = {
                    "error": error_msg,
                    "success": False,
                    "debug_info": {
                        "query": query,
                        "search_type": search_type,
                        "mcp_response": result
                    }
                }
                return json.dumps(debug_info, ensure_ascii=False, indent=2)
            
            # 处理搜索结果
            compounds = result.get("results", [])
            total_count = result.get("total_count", len(compounds))
            
            # 发送完整的MCP JSON返回作为引用信息
            if compounds:
                # 使用第一个化合物的名称作为标题
                first_compound = compounds[0]
                name = first_compound.get("iupac_name") or first_compound.get("molecular_formula") or "Chemical Search Results"
                
                # 构建完整的MCP JSON返回内容
                citation_content = f"**PubChemPy MCP JSON返回**\n\n"
                citation_content += "```json\n"
                citation_content += json.dumps(result, ensure_ascii=False, indent=2)
                citation_content += "\n```"
                
                # 使用第一个化合物的URL或默认URL
                cid = first_compound.get("cid")
                url = f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}" if cid else "https://pubchem.ncbi.nlm.nih.gov/"
                
                await emitter.send_citation(name, url, citation_content)
            
            success_msg = f"搜索完成! 找到 {len(compounds)} 个化合物"
            await emitter.update_status(success_msg, True, "search_chemical")
            
            # 返回格式化的结果
            formatted_result = {
                "success": True,
                "query": query,
                "search_type": search_type,
                "total_count": total_count,
                "returned_count": len(compounds),
                "source": result.get("source", "unknown"),
                "results": compounds
            }
            
            return json.dumps(formatted_result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            error_msg = f"搜索过程中发生错误: {str(e)}"
            await emitter.update_status(error_msg, True, "search_chemical")
            return json.dumps({"error": str(e), "success": False}, ensure_ascii=False, indent=2)
