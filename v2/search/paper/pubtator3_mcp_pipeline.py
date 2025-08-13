"""
PubTator3 MCP Pipeline - 基于MCP协议的学术论文搜索管道

功能特性:
1. 通过MCP JSON-RPC协议动态发现PubTator3服务器工具
2. 使用MCP JSON-RPC协议进行工具调用
3. 支持流式输出和智能工具选择
4. AI决策驱动的单次工具调用模式
5. 基于抽象内容的学术论文搜索
6. 多源摘要检索功能
"""

import os
import json
import requests
import asyncio
import aiohttp
import time
from typing import List, Union, Generator, Iterator, Dict, Any, Optional, AsyncGenerator
from pydantic import BaseModel
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 后端阶段标题映射
STAGE_TITLES = {
    "mcp_discovery": "MCP服务发现", 
    "tool_calling": "工具调用",
    "answer_generation": "生成回答",
}

STAGE_GROUP = {
    "mcp_discovery": "stage_group_1",
    "tool_calling": "stage_group_2", 
    "answer_generation": "stage_group_3",
}

class Pipeline:
    class Valves(BaseModel):
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
        MAX_TOOL_CALLS: int
        
        # MCP配置
        MCP_SERVER_URL: str
        MCP_TIMEOUT: int
        MCP_TOOLS_EXPIRE_HOURS: int

    def __init__(self):
        self.name = "PubTator3 MCP Academic Paper Pipeline"
        
        # 初始化token统计
        self.token_stats = {
            "input_tokens": 0, 
            "output_tokens": 0,
            "total_tokens": 0
        }
        
        # MCP工具缓存
        self.mcp_tools = {}
        self.tools_loaded = False
        self.tools_loaded_time = None  # 记录工具加载时间
        
        # MCP会话ID将在初始化时从服务器获取
        self.session_id = None
        
        self.valves = self.Valves(
            **{
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
                "MAX_TOOL_CALLS": int(os.getenv("MAX_TOOL_CALLS", "3")),
                
                # MCP配置 - 默认指向pubtator3服务
                "MCP_SERVER_URL": os.getenv("MCP_SERVER_URL", "http://localhost:8991"),
                "MCP_TIMEOUT": int(os.getenv("MCP_TIMEOUT", "30")),
                "MCP_TOOLS_EXPIRE_HOURS": int(os.getenv("MCP_TOOLS_EXPIRE_HOURS", "12")),
            }
        )

    async def on_startup(self):
        print(f"PubTator3 MCP Academic Paper Pipeline启动: {__name__}")
        
        # 验证必需的API密钥
        if not self.valves.OPENAI_API_KEY:
            print("❌ 缺少OpenAI API密钥，请设置OPENAI_API_KEY环境变量")
        
        # 验证MCP服务器地址
        print(f"🔗 MCP服务器地址: {self.valves.MCP_SERVER_URL}")
        print(f"⏰ 工具过期时间: {self.valves.MCP_TOOLS_EXPIRE_HOURS} 小时")
        if not self.valves.MCP_SERVER_URL:
            print("❌ 缺少MCP服务器地址，请设置MCP_SERVER_URL环境变量")
        
        print("🔧 MCP工具将在首次使用时自动发现")

    async def on_shutdown(self):
        print(f"PubTator3 MCP Academic Paper Pipeline关闭: {__name__}")
        print("🔚 Pipeline已关闭")

    async def _initialize_mcp_session(self, stream_mode: bool = False) -> AsyncGenerator[str, None]:
        """初始化MCP会话并获取服务器分配的session ID"""
        if not self.valves.MCP_SERVER_URL:
            raise Exception("MCP服务器地址未配置")
        
        try:
            mcp_url = f"{self.valves.MCP_SERVER_URL.strip().rstrip('/')}/mcp"
            
            # Step 1: 发送initialize请求（不带session ID）
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
                        "name": "PubTator3 MCP Pipeline",
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
                        
                        # 处理响应，可能是JSON或SSE流
                        content_type = response.headers.get("Content-Type", "")
                        
                        if "text/event-stream" in content_type:
                            # 处理SSE流
                            init_response = None
                            async for line in response.content:
                                line_str = line.decode('utf-8').strip()
                                if line_str.startswith('data: '):
                                    try:
                                        data = json.loads(line_str[6:])  # 移除 'data: ' 前缀
                                        if data.get("id") == "init-1":  # 匹配我们的请求ID
                                            init_response = data
                                            break
                                    except json.JSONDecodeError:
                                        continue
                        else:
                            # 直接JSON响应
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
                        if hasattr(self, 'session_id') and self.session_id:
                            headers["Mcp-Session-Id"] = self.session_id
                        
                        async with session.post(
                            mcp_url,
                            json=initialized_notification,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                        ) as notify_response:
                            if notify_response.status not in [200, 202]:
                                pass  # 忽略initialized通知失败
                        
                        init_msg = "🔧 MCP会话初始化完成"
                        if stream_mode:
                            for chunk in self._emit_processing(init_msg, "mcp_discovery"):
                                yield f'data: {json.dumps(chunk)}\n\n'
                        else:
                            yield init_msg + "\n"
                    else:
                        error_text = await response.text()
                        raise Exception(f"Initialize failed - HTTP {response.status}: {error_text}")
                        
        except Exception as e:
            error_msg = f"❌ MCP会话初始化失败: {e}"
            if stream_mode:
                for chunk in self._emit_processing(error_msg, "mcp_discovery"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield error_msg + "\n"
            raise

    async def _discover_mcp_tools(self, stream_mode: bool = False) -> AsyncGenerator[str, None]:
        """通过MCP JSON-RPC协议发现服务器工具"""
        if not self.valves.MCP_SERVER_URL:
            raise Exception("MCP服务器地址未配置")
        
        start_msg = f"🔍 正在发现PubTator3 MCP工具..."
        if stream_mode:
            for chunk in self._emit_processing(start_msg, "mcp_discovery"):
                yield f'data: {json.dumps(chunk)}\n\n'
        else:
            yield start_msg + "\n"
        
        # 首先初始化MCP会话
        if not hasattr(self, '_session_initialized'):
            async for init_output in self._initialize_mcp_session(stream_mode):
                yield init_output
            self._session_initialized = True
        
        try:
            # 构建MCP JSON-RPC请求
            mcp_request = {
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": "tools-list-1"
            }
            
            mcp_url = f"{self.valves.MCP_SERVER_URL.strip().rstrip('/')}/mcp"
            
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
            if hasattr(self, 'session_id') and self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    mcp_url,
                    json=mcp_request,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                ) as response:
                    if response.status == 200:
                        # 处理响应，可能是JSON或SSE流
                        content_type = response.headers.get("Content-Type", "")
                        
                        if "text/event-stream" in content_type:
                            # 处理SSE流
                            mcp_response = None
                            async for line in response.content:
                                line_str = line.decode('utf-8').strip()
                                if line_str.startswith('data: '):
                                    try:
                                        data = json.loads(line_str[6:])  # 移除 'data: ' 前缀
                                        if data.get("id") == "tools-list-1":  # 匹配我们的请求ID
                                            mcp_response = data
                                            break
                                    except json.JSONDecodeError:
                                        continue
                        else:
                            # 直接JSON响应
                            mcp_response = await response.json()
                        
                        if not mcp_response:
                            raise Exception("No tools/list response received")
                        
                        if "error" in mcp_response:
                            raise Exception(f"MCP error: {mcp_response['error']}")
                        
                        tools = mcp_response.get("result", {}).get("tools", [])
                        
                        # 加载所有工具
                        for tool in tools:
                            tool_name = tool.get("name")
                            if tool_name:
                                self.mcp_tools[tool_name] = {
                                    "name": tool_name,
                                    "description": tool.get("description", ""),
                                    "input_schema": tool.get("inputSchema", {})
                                }
                        
                        self.tools_loaded = True
                        self.tools_loaded_time = time.time()  # 记录工具加载时间
                        
                        final_msg = f"✅ 发现 {len(self.mcp_tools)} 个PubTator3 MCP工具"
                        if len(self.mcp_tools) > 0:
                            final_msg += f": {', '.join(self.mcp_tools.keys())}"
                        
                        if stream_mode:
                            for chunk in self._emit_processing(final_msg, "mcp_discovery"):
                                yield f'data: {json.dumps(chunk)}\n\n'
                        else:
                            yield final_msg + "\n"
                        
                    else:
                        error_text = await response.text()
                        raise Exception(f"HTTP {response.status}: {error_text}")
                        
        except Exception as e:
            error_msg = f"❌ PubTator3 MCP工具发现失败: {e}"
            if stream_mode:
                for chunk in self._emit_processing(error_msg, "mcp_discovery"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield error_msg + "\n"
            raise

    def _are_tools_expired(self) -> bool:
        """检查MCP工具是否已过期"""
        if not self.tools_loaded or self.tools_loaded_time is None:
            return True
        
        current_time = time.time()
        expire_seconds = self.valves.MCP_TOOLS_EXPIRE_HOURS * 3600  # 转换为秒
        return (current_time - self.tools_loaded_time) > expire_seconds

    async def _ensure_tools_loaded(self, stream_mode: bool = False) -> AsyncGenerator[str, None]:
        """确保MCP工具已加载且未过期"""
        need_reload = False
        reason = ""
        
        if not self.tools_loaded:
            need_reload = True
            reason = "工具未加载"
        elif self._are_tools_expired():
            need_reload = True
            expired_hours = (time.time() - self.tools_loaded_time) / 3600
            reason = f"工具已过期 ({expired_hours:.1f} 小时前加载)"
        
        if need_reload:
            reload_msg = f"🔄 {reason}，正在重新发现PubTator3 MCP工具..."
            if stream_mode:
                for chunk in self._emit_processing(reload_msg, "mcp_discovery"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield reload_msg + "\n"
            
            # 清除旧的工具和会话状态
            self.mcp_tools = {}
            self.tools_loaded = False
            self.tools_loaded_time = None
            if hasattr(self, '_session_initialized'):
                delattr(self, '_session_initialized')
            self.session_id = None
            
            async for discovery_output in self._discover_mcp_tools(stream_mode):
                yield discovery_output

    async def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """使用MCP JSON-RPC协议调用工具"""
        if not self.valves.MCP_SERVER_URL:
            return {"error": "MCP服务器地址未配置"}
        
        if not self.tools_loaded or self._are_tools_expired():
            try:
                async for output in self._ensure_tools_loaded(stream_mode=False):
                    # Silently consume the debug output in this context
                    pass
            except Exception as e:
                return {"error": f"工具加载失败: {str(e)}"}
        
        if tool_name not in self.mcp_tools:
            return {"error": f"工具 '{tool_name}' 不可用"}
        
        try:
            # 构建MCP JSON-RPC请求
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
            if hasattr(self, 'session_id') and self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    mcp_url,
                    headers=headers,
                    json=jsonrpc_payload,
                    timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                ) as response:
                    if response.status == 200:
                        # 处理响应，可能是JSON或SSE流
                        content_type = response.headers.get("Content-Type", "")
                        if "text/event-stream" in content_type:
                            # 处理SSE流
                            result = None
                            request_id = jsonrpc_payload["id"]
                            async for line in response.content:
                                line_str = line.decode('utf-8').strip()
                                if line_str.startswith('data: '):
                                    try:
                                        data = json.loads(line_str[6:])  # 移除 'data: ' 前缀
                                        if data.get("id") == request_id:  # 匹配我们的请求ID
                                            result = data
                                            break
                                    except json.JSONDecodeError:
                                        continue
                        else:
                            # 直接JSON响应
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
            logger.error(f"MCP工具调用超时: {tool_name}")
            return {"error": "请求超时"}
        except aiohttp.ClientError as e:
            logger.error(f"MCP HTTP请求失败: {e}")
            return {"error": f"HTTP请求失败: {str(e)}"}
        except Exception as e:
            logger.error(f"MCP工具调用失败: {e}")
            return {"error": str(e)}

    async def _execute_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """执行MCP工具并返回格式化结果"""
        result = await self._call_mcp_tool(tool_name, arguments)
        
        # 严格处理返回结果
        if "error" in result:
            return f"工具执行失败: {result['error']}"
        
        # 处理pubtator3 MCP服务的返回格式
        if "success" in result:
            if not result["success"]:
                return f"搜索失败: {result.get('error', '未知错误')}"
            
            # 成功的搜索结果
            if tool_name == "search_papers_by_abstract":
                papers = result.get("results", [])
                if not papers:
                    return "没有找到相关论文"
                
                # 格式化论文信息
                formatted_result = f"找到 {result.get('total_count', len(papers))} 篇相关论文:\n\n"
                for i, paper in enumerate(papers[:10], 1):  # 只显示前10篇
                    formatted_result += f"{i}. **{paper.get('title', '无题目')}**\n"
                    if paper.get('authors'):
                        authors_str = ', '.join(paper['authors']) if isinstance(paper['authors'], list) else str(paper['authors'])
                        formatted_result += f"   作者: {authors_str}\n"
                    if paper.get('date'):
                        formatted_result += f"   发表日期: {paper['date']}\n"
                    if paper.get('journal'):
                        formatted_result += f"   期刊: {paper['journal']}\n"
                    if paper.get('pmid'):
                        formatted_result += f"   PMID: {paper['pmid']}\n"
                    if paper.get('abstract'):
                        abstract = paper['abstract'][:400] + "..." if len(paper['abstract']) > 400 else paper['abstract']
                        formatted_result += f"   摘要: {abstract}\n"
                        if paper.get('abstract_source'):
                            formatted_result += f"   摘要来源: {paper['abstract_source']}\n"
                    
                    # 添加链接
                    links = []
                    if paper.get('doi'):
                        links.append(f"DOI: https://doi.org/{paper['doi']}")
                    if paper.get('pmid'):
                        links.append(f"PubMed: https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}")
                    if links:
                        formatted_result += f"   链接: {', '.join(links)}\n"
                    
                    formatted_result += "\n"
                
                return formatted_result
        
        # 如果有content字段（兼容其他MCP服务）
        if "content" in result and result["content"]:
            text_content = ""
            for content in result["content"]:
                if content.get("type") == "text":
                    text_content += content.get("text", "") + "\n"
            return text_content.strip()
        
        # 默认情况：直接返回JSON格式的结果
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _estimate_tokens(self, text: str) -> int:
        """简单的token估算函数"""
        if not text:
            return 0
        chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        english_text = ''.join(char if not ('\u4e00' <= char <= '\u9fff') else ' ' for char in text)
        english_words = len([word for word in english_text.split() if word.strip()])
        estimated_tokens = chinese_chars + int(english_words * 1.3)
        return max(estimated_tokens, 1)

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

    def _call_openai_api(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        """调用OpenAI API"""
        if not self.valves.OPENAI_API_KEY:
            return "错误: 未设置OpenAI API密钥"
        
        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # 构建消息列表，只有system_prompt不为空时才添加system消息
        messages = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": messages,
            "max_tokens": self.valves.OPENAI_MAX_TOKENS,
            "temperature": self.valves.OPENAI_TEMPERATURE,
        }
        
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        # 添加输入token统计
        if system_prompt and system_prompt.strip():
            self._add_input_tokens(system_prompt)
        self._add_input_tokens(user_prompt)
        
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.valves.OPENAI_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
            
            answer = result["choices"][0]["message"]["content"]
            self._add_output_tokens(answer)
            
            return answer
            
        except Exception as e:
            error_msg = f"OpenAI API调用错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            return error_msg

    def _stream_openai_response(self, user_prompt: str, system_prompt: str) -> Generator:
        """流式处理OpenAI响应"""
        if not self.valves.OPENAI_API_KEY:
            yield "错误: 未设置OpenAI API密钥"
            return
        
        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # 构建消息列表，只有system_prompt不为空时才添加system消息
        messages = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": messages,
            "max_tokens": self.valves.OPENAI_MAX_TOKENS,
            "temperature": self.valves.OPENAI_TEMPERATURE,
            "stream": True
        }
        
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
                            
        except Exception as e:
            error_msg = f"OpenAI流式API调用错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            yield error_msg

    def _emit_processing(self, content: str, stage: str = "processing") -> Generator[dict, None, None]:
        """发送处理过程内容"""
        yield {
            'choices': [{
                'delta': {
                    'processing_content': content + '\n',
                    'processing_title': STAGE_TITLES.get(stage, "处理中"),
                    'processing_stage': STAGE_GROUP.get(stage, "stage_group_1")
                },
                'finish_reason': None
            }]
        }

    def _get_system_prompt(self) -> str:
        """动态生成基于可用MCP工具的系统提示词"""
        base_prompt = """你是一个专业的学术论文搜索助手，能够使用PubTator3 MCP工具来查询学术论文的详细信息。

🔧 可用工具：
"""
        
        # 动态添加工具信息
        if self.mcp_tools:
            for tool_name, tool_info in self.mcp_tools.items():
                base_prompt += f"""
工具名称: {tool_name}
描述: {tool_info.get('description', '无描述')}
"""
                
                # 添加输入参数信息
                input_schema = tool_info.get('input_schema', {})
                if input_schema and 'properties' in input_schema:
                    base_prompt += "参数:\n"
                    for param_name, param_info in input_schema['properties'].items():
                        param_type = param_info.get('type', 'unknown')
                        param_desc = param_info.get('description', '无描述')
                        param_required = param_name in input_schema.get('required', [])
                        required_str = " (必需)" if param_required else " (可选)"
                        base_prompt += f"  - {param_name} ({param_type}){required_str}: {param_desc}\n"
                    base_prompt += "\n"
        else:
            base_prompt += "⚠️ 当前没有可用的MCP工具\n"
        
        base_prompt += """
🧠 使用指南：
1. 当用户询问学术论文相关信息时，分析他们的需求并选择合适的工具
2. search_papers_by_abstract工具用于基于摘要内容搜索论文，支持关键词搜索
3. 该工具会返回包含PMID、标题、作者、期刊、发表日期、DOI和完整摘要的论文信息
4. 搜索时应使用英文关键词，效果更好
5. 可以根据页面大小、页码等参数优化搜索结果
6. 工具支持多源摘要检索，会从Semantic Scholar、OpenAlex、CrossRef等来源获取完整摘要

🔍 搜索建议：
- 使用具体的研究主题关键词
- 可以组合多个相关术语
- 考虑使用作者姓名搜索
- 利用分页功能获取更多结果
- 启用完整摘要检索获取详细信息

🔄 工具调用格式：
如果需要调用工具，请回复：
TOOL_CALL:<工具名称>:<JSON参数>

示例：
- TOOL_CALL:search_papers_by_abstract:{"query": "machine learning", "page_size": 10, "include_full_abstracts": true}
- TOOL_CALL:search_papers_by_abstract:{"query": "COVID-19 vaccine", "page": 1, "page_size": 15, "max_concurrent": 3}
- TOOL_CALL:search_papers_by_abstract:{"query": "CRISPR gene editing", "include_full_abstracts": false}

如果不需要工具调用，请直接回答用户问题。可以多次调用工具获取更完整的信息。
"""
        
        return base_prompt

    def _build_conversation_context(self, user_message: str, messages: List[dict]) -> str:
        """构建完整的对话上下文"""
        # 构建对话历史
        conversation_history = []
        if messages and len(messages) > 1:
            # 取最近的2轮对话作为上下文（4条消息）
            recent_messages = messages[-4:] if len(messages) > 4 else messages
            for msg in recent_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role in ["user", "assistant"]:
                    # 对对话内容进行300长度截断
                    if len(content) > 300:
                        content = content[:300] + "..."
                    conversation_history.append({"role": role, "content": content})
        
        # 添加当前用户消息
        conversation_history.append({"role": "user", "content": user_message})
        
        # 构建完整的上下文提示
        context_text = ""
        for msg in conversation_history[:-1]:  # 除了最后一条消息
            role = "用户" if msg["role"] == "user" else "助手"
            context_text += f"{role}: {msg['content']}\n"
        
        full_user_prompt = f"""历史对话上下文:
{context_text if context_text else "无历史对话"}

当前用户问题: {user_message}

请根据上下文和当前问题，决定是否需要调用PubTator3 MCP工具。如果需要，请按照指定格式回复工具调用。
回答要忠于上下文、当前问题、工具返回的信息。"""
        
        return full_user_prompt

    def _parse_tool_call(self, ai_response: str) -> tuple[str, dict, str]:
        """解析AI响应中的工具调用
        
        Returns:
            tuple: (tool_name, tool_args, error_message)
            如果解析成功，error_message为None
            如果解析失败，tool_name和tool_args为None，返回错误信息
        """
        if not ai_response.startswith("TOOL_CALL:"):
            return None, None, None
        
        try:
            # 解析工具调用
            tool_call_str = ai_response.replace("TOOL_CALL:", "", 1)
            
            # 找到第一个冒号分隔工具名称和参数
            if ":" in tool_call_str:
                tool_name, tool_args_str = tool_call_str.split(":", 1)
                tool_name = tool_name.strip()
                tool_args = json.loads(tool_args_str)
            else:
                raise ValueError("无效的工具调用格式")
            
            # 验证工具是否存在
            if tool_name not in self.mcp_tools:
                raise ValueError(f"工具 '{tool_name}' 不存在")
            
            return tool_name, tool_args, None
            
        except (json.JSONDecodeError, ValueError) as e:
            return None, None, str(e)

    async def _execute_tool_call_with_feedback(self, tool_name: str, tool_args: dict, stream_mode: bool) -> AsyncGenerator[str, None]:
        """执行工具调用并提供进度反馈"""
        # 显示工具调用信息
        call_info = f"🔧 正在调用PubTator3 MCP工具 '{tool_name}'..."
        if stream_mode:
            for chunk in self._emit_processing(call_info, "tool_calling"):
                yield f'data: {json.dumps(chunk)}\n\n'
        else:
            yield call_info + "\n"
        
        # 显示工具调用参数
        tool_info = f"📝 工具调用参数: {json.dumps(tool_args, ensure_ascii=False)}"
        if stream_mode:
            for chunk in self._emit_processing(tool_info, "tool_calling"):
                yield f'data: {json.dumps(chunk)}\n\n'
        else:
            yield tool_info + "\n"
        
        # 调用MCP工具
        tool_result = await self._execute_mcp_tool(tool_name, tool_args)
        try:
            json_tool_result = json.loads(tool_result)
            tool_result = json.dumps(json_tool_result, indent=4)
        except json.JSONDecodeError:
            pass
        
        # 显示工具调用结果
        result_info = f"✅ 工具调用结果:\n```json\n{tool_result}\n```"
        if stream_mode:
            for chunk in self._emit_processing(result_info, "tool_calling"):
                yield f'data: {json.dumps(chunk)}\n\n'
        else:
            yield result_info + "\n"
        
        # 最后返回工具结果（作为特殊标记的字符串）
        yield f"TOOL_RESULT:{tool_result}"

    async def _generate_final_answer(self, user_message: str, tool_result: str, tool_name: str, tool_args: dict, full_user_prompt: str, system_prompt: str, stream_mode: bool) -> AsyncGenerator[str, None]:
        """生成最终回答"""
        if tool_result is not None:
            # 如果有工具调用结果，基于结果生成回答
            final_system_prompt = "你是专业的学术论文搜索专家，请基于提供的PubTator3 MCP工具调用结果，为用户提供准确、详细的回答。请包含你的分析和见解。"
            
            tool_summary = f"""基于以下PubTator3 MCP工具调用结果:

工具调用: {tool_name}
参数: {json.dumps(tool_args, ensure_ascii=False)}
结果: {tool_result}

用户问题: {user_message}

请基于以上工具调用结果为用户提供准确详细的回答，并加入你的专业分析和见解。注意：
1. 尽量输出完整的信息，不要省略重要的详细内容
2. 有资源地址（如DOI、PubMed链接等）时，使用markdown格式输出可点击链接"""
            
            if stream_mode:
                # 流式模式开始生成回答的标识
                answer_start_msg = {
                    'choices': [{
                        'delta': {
                            'content': "\n**📚 基于PubTator3工具调用结果的专业分析**\n"
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(answer_start_msg)}\n\n"
                
                # 流式生成最终回答
                for chunk in self._stream_openai_response(tool_summary, final_system_prompt):
                    # 包装成SSE格式
                    chunk_data = {
                        'choices': [{
                            'delta': {
                                'content': chunk
                            },
                            'finish_reason': None
                        }]
                    }
                    yield f"data: {json.dumps(chunk_data)}\n\n"
            else:
                yield "📚 **基于PubTator3工具调用结果的专业分析**\n"
                final_answer = self._call_openai_api(final_system_prompt, tool_summary)
                yield final_answer
        else:
            # 没有工具调用，直接返回AI响应
            if stream_mode:
                # 流式模式
                answer_start_msg = {
                    'choices': [{
                        'delta': {
                            'content': "\n**💭 回答**\n"
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(answer_start_msg)}\n\n"
                
                for chunk in self._stream_openai_response(full_user_prompt, system_prompt):
                    chunk_data = {
                        'choices': [{
                            'delta': {
                                'content': chunk
                            },
                            'finish_reason': None
                        }]
                    }
                    yield f"data: {json.dumps(chunk_data)}\n\n"
            else:
                yield "💭 **回答**\n"
                final_answer = self._call_openai_api(system_prompt, full_user_prompt)
                yield final_answer

    async def _process_user_message(self, user_message: str, messages: List[dict], stream_mode: bool) -> AsyncGenerator[str, None]:
        """处理用户消息，支持多轮MCP工具调用（重构后的简化版本）"""
        
        # 确保工具已加载且未过期
        try:
            async for tools_output in self._ensure_tools_loaded(stream_mode):
                yield tools_output
        except Exception as e:
            error_msg = f"❌ PubTator3 MCP工具加载失败: {str(e)}"
            if stream_mode:
                for chunk in self._emit_processing(error_msg, "mcp_discovery"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield error_msg + "\n"
            return
        
        # 获取系统提示词和构建上下文
        system_prompt = self._get_system_prompt()
        full_user_prompt = self._build_conversation_context(user_message, messages)
        
        # 显示AI决策进度
        decision_msg = "🤔 正在分析用户问题，决定是否需要调用PubTator3工具..."
        if stream_mode:
            for chunk in self._emit_processing(decision_msg, "tool_calling"):
                yield f'data: {json.dumps(chunk)}\n\n'
        else:
            yield decision_msg + "\n"
        
        # 尝试解析工具调用，如果失败则重试
        tool_name, tool_args = None, None
        
        for retry_count in range(self.valves.MAX_TOOL_CALLS):
            ai_response = self._call_openai_api(system_prompt, full_user_prompt)
            tool_name, tool_args, parse_error = self._parse_tool_call(ai_response)
            
            if parse_error is None:
                # 解析成功或无需工具调用
                if tool_name is None:
                    # 不需要工具调用
                    no_tool_msg = "💭 AI决定无需调用工具，正在生成回答..."
                    if stream_mode:
                        for chunk in self._emit_processing(no_tool_msg, "answer_generation"):
                            yield f'data: {json.dumps(chunk)}\n\n'
                    else:
                        yield no_tool_msg + "\n"
                break
            else:
                # 解析失败，重试
                if retry_count < self.valves.MAX_TOOL_CALLS - 1:
                    retry_msg = f"⚠️ 工具调用格式错误({parse_error})，正在重试({retry_count + 1}/{self.valves.MAX_TOOL_CALLS})..."
                    if stream_mode:
                        for chunk in self._emit_processing(retry_msg, "tool_calling"):
                            yield f'data: {json.dumps(chunk)}\n\n'
                    else:
                        yield retry_msg + "\n"
                    continue
                else:
                    # 达到最大重试次数
                    error_msg = f"❌ 工具调用解析失败，已重试{self.valves.MAX_TOOL_CALLS}次: {parse_error}"
                    if stream_mode:
                        for chunk in self._emit_processing(error_msg, "tool_calling"):
                            yield f'data: {json.dumps(chunk)}\n\n'
                    else:
                        yield error_msg + "\n"
                    return
        
        # 执行工具调用（如果需要）
        tool_result = None
        if tool_name and tool_args:
            async for output in self._execute_tool_call_with_feedback(tool_name, tool_args, stream_mode):
                if isinstance(output, str) and output.startswith('TOOL_RESULT:'):
                    # 这是最终的工具结果
                    tool_result = output.replace('TOOL_RESULT:', '', 1)
                else:
                    # 这是进度反馈
                    yield output
        
        # 生成最终回答
        async for output in self._generate_final_answer(
            user_message, tool_result, tool_name, tool_args, 
            full_user_prompt, system_prompt, stream_mode
        ):
            yield output

    def pipe(self, user_message: str, model_id: str, messages: List[dict], body: dict) -> Union[str, Generator, Iterator]:
        """主管道函数"""
        # 重置token统计
        self._reset_token_stats()

        if self.valves.DEBUG_MODE:
            print(f"📚 PubTator3 MCP学术论文助手收到消息: {user_message}")
            print(f"🔧 模型ID: {model_id}")
            print(f"📜 历史消息数量: {len(messages) if messages else 0}")
            print(f"🔗 MCP服务器: {self.valves.MCP_SERVER_URL}")

        # 验证输入
        if not user_message or not user_message.strip():
            yield "❌ 请输入有效的学术论文搜索问题或查询内容"
            return

        # 检查是否是流式模式  
        stream_mode = self.valves.ENABLE_STREAMING
        
        try:
            # MCP服务发现阶段
            if stream_mode:
                for chunk in self._emit_processing("🔍 正在准备PubTator3 MCP服务...", "mcp_discovery"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield "🔍 **阶段1**: 正在准备PubTator3 MCP服务...\n"
            
            # 在同步环境中运行异步代码 - 真正的流式处理
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # 创建异步生成器
                async_gen = self._process_user_message(user_message, messages, stream_mode)
                
                # 流式处理每个结果
                while True:
                    try:
                        result = loop.run_until_complete(async_gen.__anext__())
                        yield result
                    except StopAsyncIteration:
                        break
                
                # 最后发送完成信息
                if stream_mode:
                    # 流式模式结束
                    done_msg = {
                        'choices': [{
                            'delta': {},
                            'finish_reason': 'stop'
                        }]
                    }
                    yield f"data: {json.dumps(done_msg)}\n\n"
                    yield "data: [DONE]\n\n"
                    
                    # 添加token统计
                    token_info = self._get_token_stats()
                    token_msg = {
                        'choices': [{
                            'delta': {
                                'content': f"\n\n---\n📊 **Token统计**: 输入 {token_info['input_tokens']}, 输出 {token_info['output_tokens']}, 总计 {token_info['total_tokens']}"
                            },
                            'finish_reason': None
                        }]
                    }
                    yield f"data: {json.dumps(token_msg)}\n\n"
                else:
                    # 添加token统计信息
                    token_info = self._get_token_stats()
                    yield f"\n\n---\n📊 **Token统计**: 输入 {token_info['input_tokens']}, 输出 {token_info['output_tokens']}, 总计 {token_info['total_tokens']}"
                    
            finally:
                loop.close()

        except Exception as e:
            error_msg = f"❌ Pipeline执行错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            
            if stream_mode:
                error_chunk = {
                    'choices': [{
                        'delta': {
                            'content': error_msg
                        },
                        'finish_reason': 'stop'
                    }]
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"
                yield "data: [DONE]\n\n"
            else:
                yield error_msg
