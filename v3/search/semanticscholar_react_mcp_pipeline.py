"""
基于v2\search\semanticscholar_mcp\src\mcp_server.py，参考v3\search\paperlist_react_mcp_pipeline.py编写本pipeline
使用ReAct模式，实现深度思考，并进行多轮Semantic Scholar MCP工具调用，最终给出回答。
1.Reasoning阶段，根据用户问题、历史会话、当前获取到的论文信息进行自主思考判断
  - 制定初次工具调用的Action, 调用semantic scholar工具，获取论文信息
2.Action阶段，调用MCP工具，获取信息
3.Observation阶段(每次Action后都需要进行观察)
  - 根据Action的执行结果，判断是否足够回答用户的问题(问题的相关性，进一步探索的必要性)
  - 如果信息不充分，则制定新的Action(更新查询关键词、使用前一步检索到的信息更新查询关键词)，调用semantic scholar工具，获取论文信息
  - 如果信息充分，则跳转答案生成阶段
4.答案生成阶段，根据用户问题、历史会话、当前获取到的信息，生成最终答案，并返回给用户
5.除了答案生成阶段，每个阶段使用_emit_processing方法，返回处理过程内容和思考，减少debug描述内容的输出
6.对于Action和Observation阶段，_emit_processing采用动态递进的processing_stage
7.注意代码的整洁简练，函数的解耦，避免重复代码和过多debug输出
8.注意：Semantic Scholar MCP工具支持复杂的学术查询，可以使用专业术语、作者名称、期刊名等
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

# ReAct阶段标题映射
STAGE_TITLES = {
    "reasoning": "🤔 推理分析",
    "action": "🔧 执行动作", 
    "observation": "👁️ 观察结果",
    "answer_generation": "📝 生成答案",
    "mcp_discovery": "🔍 MCP服务发现"
}

STAGE_GROUP = {
    "reasoning": "stage_group_1",
    "action": "stage_group_2",
    "observation": "stage_group_3", 
    "answer_generation": "stage_group_4",
    "mcp_discovery": "stage_group_0"
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
        MAX_REACT_ITERATIONS: int
        MIN_PAPERS_THRESHOLD: int
        
        # MCP配置
        MCP_SERVER_URL: str
        MCP_TIMEOUT: int
        MCP_TOOLS_EXPIRE_HOURS: int

    def __init__(self):
        self.name = "Semantic Scholar ReAct MCP Academic Paper Pipeline"
        
        # 初始化token统计
        self.token_stats = {
            "input_tokens": 0, 
            "output_tokens": 0,
            "total_tokens": 0,
            "api_calls": 0
        }
        
        # MCP工具缓存
        self.mcp_tools = {}
        self.tools_loaded = False
        self.tools_loaded_time = None
        self.session_id = None
        
        # ReAct状态
        self.react_state = {
            "papers_collected": [],  # 存储关键论文信息（字典格式）
            "query_history": [],
            "query_terms_used": set(),  # 已使用的查询词集合
            "extracted_keywords_history": set(),  # 历史提取的关键词集合
            "current_iteration": 0,
            "current_offset": 0,  # 当前偏移量
            "current_limit": 10,  # 当前每页数量
            "query_offsets": {}  # 记录每个查询词使用的偏移量 {query: offset}
        }
        
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
                "MAX_REACT_ITERATIONS": int(os.getenv("MAX_REACT_ITERATIONS", "10")),
                "MIN_PAPERS_THRESHOLD": int(os.getenv("MIN_PAPERS_THRESHOLD", "20")),
                
                # MCP配置 - 默认指向semantic scholar服务
                "MCP_SERVER_URL": os.getenv("MCP_SERVER_URL", "http://localhost:8992"),
                "MCP_TIMEOUT": int(os.getenv("MCP_TIMEOUT", "30")),
                "MCP_TOOLS_EXPIRE_HOURS": int(os.getenv("MCP_TOOLS_EXPIRE_HOURS", "12")),
            }
        )

    async def on_startup(self):
        print(f"Semantic Scholar ReAct MCP Pipeline启动: {__name__}")
        if not self.valves.OPENAI_API_KEY:
            print("❌ 缺少OpenAI API密钥")
        print(f"🔗 MCP服务器: {self.valves.MCP_SERVER_URL}")

    async def on_shutdown(self):
        print(f"Semantic Scholar ReAct MCP Pipeline关闭: {__name__}")

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
                        "name": "Semantic Scholar ReAct MCP Pipeline",
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
        
        start_msg = f"🔍 正在发现Semantic Scholar MCP工具..."
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
                        
                        final_msg = f"✅ 发现 {len(self.mcp_tools)} 个Semantic Scholar MCP工具"
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
            error_msg = f"❌ Semantic Scholar MCP工具发现失败: {e}"
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
            reload_msg = f"🔄 {reason}，正在重新发现Semantic Scholar MCP工具..."
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
        """执行MCP工具并返回原始结果"""
        result = await self._call_mcp_tool(tool_name, arguments)
        
        # 直接返回原始JSON结果，让LLM自主处理内容
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _call_openai_api(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        """调用OpenAI API并统计token使用量"""
        if not self.valves.OPENAI_API_KEY:
            return "错误: 未设置OpenAI API密钥"
        
        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        # 统计输入token数量（用字符数估计）
        input_text = ""
        for msg in messages:
            input_text += msg.get("content", "")
        input_tokens = len(input_text)
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": messages,
            "max_tokens": self.valves.OPENAI_MAX_TOKENS,
            "temperature": self.valves.OPENAI_TEMPERATURE,
        }
        
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.valves.OPENAI_TIMEOUT)
            response.raise_for_status()
            result = response.json()
            
            # 获取响应内容
            response_content = result["choices"][0]["message"]["content"]
            
            # 统计输出token数量（用字符数估计）
            output_tokens = len(response_content)
            
            # 更新统计信息
            self.token_stats["input_tokens"] += input_tokens
            self.token_stats["output_tokens"] += output_tokens
            self.token_stats["total_tokens"] += input_tokens + output_tokens
            self.token_stats["api_calls"] += 1
            
            return response_content
        except Exception as e:
            return f"OpenAI API调用错误: {str(e)}"

    def _stream_openai_response(self, user_prompt: str, system_prompt: str) -> Generator:
        """流式处理OpenAI响应并统计token使用量"""
        if not self.valves.OPENAI_API_KEY:
            yield "错误: 未设置OpenAI API密钥"
            return
        
        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        # 统计输入token数量（用字符数估计）
        input_text = ""
        for msg in messages:
            input_text += msg.get("content", "")
        input_tokens = len(input_text)
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": messages,
            "max_tokens": self.valves.OPENAI_MAX_TOKENS,
            "temperature": self.valves.OPENAI_TEMPERATURE,
            "stream": True
        }
        
        # 用于累积输出内容
        output_content = ""
        
        try:
            response = requests.post(url, headers=headers, json=payload, stream=True, timeout=self.valves.OPENAI_TIMEOUT)
            response.raise_for_status()
            
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
                                output_content += delta
                                yield delta
                        except json.JSONDecodeError:
                            pass
            
            # 统计输出token数量并更新统计信息
            output_tokens = len(output_content)
            self.token_stats["input_tokens"] += input_tokens
            self.token_stats["output_tokens"] += output_tokens
            self.token_stats["total_tokens"] += input_tokens + output_tokens
            self.token_stats["api_calls"] += 1
            
        except Exception as e:
            yield f"OpenAI流式API调用错误: {str(e)}"

    async def _reasoning_phase(self, user_message: str, messages: List[dict], stream_mode: bool) -> AsyncGenerator[tuple, None]:
        """ReAct推理阶段 - 针对Semantic Scholar搜索特点进行优化"""
        context = self._build_conversation_context(user_message, messages)
        used_queries = list(self.react_state['query_terms_used'])
        
        reasoning_prompt = f"""你是专业的学术论文搜索助手。请基于用户问题和已有信息制定搜索策略。

用户问题: {user_message}
对话历史: {context}
已使用查询词: {used_queries}

**重要说明：**
- 本系统使用的是Semantic Scholar MCP工具，这是一个强大的学术搜索引擎
- 支持复杂的学术查询，包括专业术语、作者名称、期刊名称等
- 返回结果包含完整的论文元数据：标题、作者、摘要、引用数、期刊等

**分析任务：**
1. 判断是否需要搜索论文？
2. 如果需要搜索，从用户问题中提取核心学术查询关键词
3. 避免重复已使用的查询词: {used_queries}

**查询词要求（适配Semantic Scholar特点）：**
- 可以使用复杂的学术术语组合
- 支持作者名称查询（如 "author:Smith machine learning"）
- 支持期刊名称查询（如 "venue:Nature artificial intelligence"）
- 支持具体技术术语（如 "transformer attention mechanism"）
- 支持多词组合查询（如 "deep learning medical image segmentation"）

**示例：**
用户问题"机器学习在医学影像中的应用" → 查询: "machine learning medical imaging" 或 "deep learning medical image"
用户问题"Transformer架构的最新研究" → 查询: "transformer architecture attention mechanism"
用户问题"自然语言处理的BERT模型" → 查询: "BERT natural language processing"
用户问题"Geoffrey Hinton的深度学习研究" → 查询: "author:Geoffrey Hinton deep learning"

回复格式：
```json
{{
    "need_search": true/false,
    "query": "适合Semantic Scholar搜索的学术查询词",
    "reasoning": "基于用户问题和已有信息的分析",
    "sufficient_info": true/false
}}
```"""

        if stream_mode:
            for chunk in self._emit_processing("分析用户问题，制定适合Semantic Scholar搜索的策略...", "reasoning"):
                yield ("processing", f'data: {json.dumps(chunk)}\n\n')
        
        decision = self._call_openai_api("", reasoning_prompt, json_mode=True)
        
        try:
            decision_data = json.loads(decision)
            if stream_mode:
                reasoning_content = f"推理分析：{decision_data.get('reasoning', '无')}"
                for chunk in self._emit_processing(reasoning_content, "reasoning"):
                    yield ("processing", f'data: {json.dumps(chunk)}\n\n')
            
            yield ("decision", decision_data)
        except json.JSONDecodeError:
            yield ("decision", {"need_search": False, "sufficient_info": True, "reasoning": "解析失败"})

    async def _action_phase(self, query: str, limit: int = 10, offset: int = 0, stream_mode: bool = False) -> AsyncGenerator[tuple, None]:
        """ReAct动作阶段 - 使用Semantic Scholar工具"""
        # 更新当前偏移量状态
        self.react_state["current_offset"] = offset
        self.react_state["current_limit"] = limit
        self.react_state["query_offsets"][query] = offset
        
        if stream_mode:
            action_msg = f"执行论文搜索：{query} (偏移量{offset}，限制{limit}篇)"
            for chunk in self._emit_processing(action_msg, "action"):
                yield ("processing", f'data: {json.dumps(chunk)}\n\n')
        
        # 调用semantic scholar工具搜索论文
        tool_args = {
            "query": query,
            "limit": limit,
            "offset": offset
        }
        
        # 获取原始工具调用结果
        tool_result = await self._execute_mcp_tool("search_papers", tool_args)

        # 格式美化
        try:
            json_result = json.loads(tool_result)
            tool_result = json.dumps(json_result, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pass
        
        # 使用_emit_processing输出工具返回结果的markdown代码框
        if stream_mode:
            tool_output_msg = f"**工具调用结果:**\n\n```json\n{tool_result}\n```"
            for chunk in self._emit_processing(tool_output_msg, "action"):
                yield ("processing", f'data: {json.dumps(chunk)}\n\n')
        
        # 记录查询历史和查询词
        self.react_state['query_history'].append(query)
        self.react_state['query_terms_used'].add(query.lower())
        
        yield ("result", tool_result)

    async def _observation_phase(self, action_result: str, query: str, user_message: str, stream_mode: bool) -> AsyncGenerator[tuple, None]:
        """ReAct观察阶段 - 针对Semantic Scholar结果格式进行分析"""
        if stream_mode:
            for chunk in self._emit_processing("观察搜索结果，分析论文内容，提取新查询关键词...", "observation"):
                yield ("processing", f'data: {json.dumps(chunk)}\n\n')
        
        # 构建观察prompt
        used_queries = list(self.react_state['query_terms_used'])
        extracted_history = list(self.react_state['extracted_keywords_history'])
        unused_keywords = [kw for kw in extracted_history if kw.lower() not in self.react_state['query_terms_used']]
        current_offset = self.react_state.get('current_offset', 0)
        current_limit = self.react_state.get('current_limit', 10)
        
        observation_prompt = f"""你是专业的学术论文分析专家。请基于Semantic Scholar搜索结果进行深度分析：

用户问题: {user_message}  
使用的查询词: {query}
当前偏移量: {current_offset} (限制{current_limit}篇)
当前迭代: {self.react_state['current_iteration']}/{self.valves.MAX_REACT_ITERATIONS}
已使用查询词: {used_queries}
历史提取的关键词: {extracted_history}
历史未使用的关键词: {unused_keywords}

当前搜索结果原始数据:
{action_result}

**关键任务：**
1. 自主分析当前搜索结果的原始JSON数据，判断是否成功找到相关论文
2. 查看JSON中的success字段，了解搜索是否成功
3. 仔细分析JSON中"results"数组内论文的标题、作者、摘要、引用数等内容
4. 从论文内容中识别与用户问题直接相关的**关键词**和**专业术语**
5. 记录高相关度的关键论文信息（标题、作者、摘要、相关性权重）
6. 基于total_count判断是否还有更多结果需要获取
7. 选择能够进一步深入探索相关主题的新查询词

**针对Semantic Scholar的查询词选择策略：**
- 可以使用复杂的学术术语组合
- 支持作者查询：author:"作者名" + 主题
- 支持期刊查询：venue:"期刊名" + 主题  
- 支持具体技术术语和方法名称
- 优先级1: 从当前论文内容中提取的新专业名词
- 优先级2: 结合作者或期刊的深度查询
- 优先级3: 历史未使用的关键词（如果与用户问题相关）

**查询词示例：**
- 复合查询: "transformer attention mechanism NLP"
- 作者查询: "author:Yoshua Bengio deep learning"
- 期刊查询: "venue:Nature machine learning medical"
- 技术查询: "BERT fine-tuning language model"
- 领域查询: "computer vision object detection CNN"

**分页策略：**
- 基于total_count判断是否还有更多结果
- 如果当前结果相关性高且total_count > current_offset + current_limit，可考虑获取更多
- 使用current_offset + current_limit作为new_offset值
- 分页适用于当前查询词，避免频繁分页影响效率

**关键论文筛选标准：**
- 基于论文标题、摘要、引用数评估与用户问题的相关程度
- 优先考虑引用数较高的重要论文
- 记录所有找到的论文，但按相关性权重排序
- 相关性权重应反映论文对用户问题的直接相关程度（0.0-1.0）

回复格式：
```json
{{
    "relevance_score": 0-10,
    "sufficient_info": true/false,
    "need_more_search": true/false,
    "suggested_query": "新的学术查询词(if needed)",
    "query_source": "current_papers/author_focus/venue_focus/historical_keywords",
    "new_offset": 0,
    "limit": 10,
    "need_pagination": true/false,
    "pagination_reason": "分页原因说明(if needed)",
    "extracted_keywords": ["从当前论文中识别的关键术语列表"],
    "key_papers": [
        {{
            "title": "论文标题",
            "authors": "作者列表", 
            "year": "发表年份",
            "venue": "期刊/会议",
            "abstract": "摘要内容",
            "citation_count": "引用数",
            "relevance_weight": 0.0-1.0,
            "key_findings": "关键发现或结论",
            "urls": ["DOI链接", "开放访问PDF链接", "论文URL等"]
        }}
    ],
    "observation": "基于论文内容的详细分析"
}}
```"""

        observation = self._call_openai_api("", observation_prompt, json_mode=True)
        
        try:
            observation_data = json.loads(observation)
            
            # 处理提取的关键词历史记录
            extracted_keywords = observation_data.get('extracted_keywords', [])
            if extracted_keywords:
                self.react_state['extracted_keywords_history'].update(extracted_keywords)
            
            # 处理关键论文信息，更新papers_collected
            key_papers = observation_data.get('key_papers', [])
            selected_papers = []
            added_count = 0
            
            if key_papers:
                # 按相关性权重排序，选择前80%的论文
                papers_with_weights = []
                for paper in key_papers:
                    relevance_weight = paper.get('relevance_weight', 0.8)  # 默认权重0.8
                    papers_with_weights.append((paper, relevance_weight))
                
                # 按权重降序排序
                papers_with_weights.sort(key=lambda x: x[1], reverse=True)
                
                # 选择前80%的论文（至少5篇）
                num_to_select = max(5, int(len(papers_with_weights) * 0.8))
                selected_papers = papers_with_weights[:num_to_select]
                
                # 添加到收集列表，避免重复
                for paper, weight in selected_papers:
                    # 简单的重复检查：基于标题
                    paper_title = paper.get('title', '').strip().lower()
                    if paper_title and not any(
                        existing_paper.get('title', '').strip().lower() == paper_title 
                        for existing_paper in self.react_state['papers_collected']
                    ):
                        self.react_state['papers_collected'].append(paper)
                        added_count += 1
            
            if stream_mode:
                obs_content = f"观察分析：{observation_data.get('observation', '无')}"
                
                if extracted_keywords:
                    obs_content += f"\n提取的关键词：{', '.join(extracted_keywords)}"
                
                if key_papers:
                    obs_content += f"\n发现 {len(key_papers)} 篇关键论文"
                    obs_content += f"，按相关性选择({len(selected_papers)}篇)，实际新增({added_count}篇)已收录"
                
                query_source = observation_data.get('query_source', 'current_papers')
                source_desc = {
                    'author_focus': '作者聚焦查询',
                    'venue_focus': '期刊聚焦查询',
                    'historical_keywords': '历史关键词重用',
                    'current_papers': '当前论文提取'
                }.get(query_source, '当前论文提取')
                obs_content += f"\n建议查询词来源：{source_desc}"
                
                # 显示分页信息
                if observation_data.get('need_pagination', False):
                    new_offset = observation_data.get('new_offset', current_offset + current_limit)
                    limit = observation_data.get('limit', current_limit)
                    pagination_reason = observation_data.get('pagination_reason', '需要更多论文')
                    obs_content += f"\n分页建议：偏移量{new_offset} (限制{limit}篇) - {pagination_reason}"
                
                for chunk in self._emit_processing(obs_content, "observation"):
                    yield ("processing", f'data: {json.dumps(chunk)}\n\n')
            
            yield ("observation", observation_data)
        except json.JSONDecodeError:
            yield ("observation", {"sufficient_info": True, "need_more_search": False})

    async def _answer_generation_phase(self, user_message: str, messages: List[dict], stream_mode: bool) -> AsyncGenerator[str, None]:
        """答案生成阶段"""
        # 构建完整上下文
        context = self._build_conversation_context(user_message, messages)
        papers_summary = self._summarize_collected_papers()
        
        # 获取论文统计信息
        total_papers_count = len(self.react_state['papers_collected'])
        
        final_prompt = f"""基于收集到的论文信息回答用户问题：

用户问题: {user_message}
对话历史: {context}

📊 **检索统计**: 通过Semantic Scholar检索，共收集到 {total_papers_count} 篇相关学术论文

收集到的论文信息:
{papers_summary}

**重要要求：**
1. **充分利用所有收集到的论文信息** - 不要遗漏任何相关研究
2. **详细引用论文** - 每个观点都要标注来源论文的标题、作者、年份
3. **整合多篇研究** - 综合分析不同研究的发现，指出共识和分歧
4. **提供具体数据** - 引用论文中的具体研究数据、结果、结论、引用数
5. **结构化回答** - 按逻辑顺序组织内容，便于理解
6. **完整性** - 确保回答涵盖用户问题的各个方面
7. **学术权威性** - 优先引用高引用数的重要论文

请基于以上所有论文信息提供全面、详细、准确的回答。包含相关论文的完整引用信息（标题、作者、年份、期刊、引用数等）。
如果有DOI、URL、开放访问PDF链接，请务必使用markdown格式输出可点击链接(不要遗漏有效链接)。"""

        system_prompt = """你是专业的学术论文分析专家。你的任务是：
1. 仔细分析所有提供的论文信息
2. 充分利用每一篇相关论文的内容
3. 提供全面、详细、有深度的学术回答
4. 确保每个观点都有论文支撑和引用
5. 整合多个研究来源，提供综合性见解
6. 优先引用高影响力（高引用数）的论文
7. 在回答开头简要提及检索到的论文数量统计，体现研究的全面性"""

        if stream_mode:
            for chunk in self._stream_openai_response(final_prompt, system_prompt):
                chunk_data = {
                    'choices': [{
                        'delta': {'content': chunk},
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"
            
            # 输出token统计信息（流式模式）
            stats_text = self._get_token_stats_text()
            stats_chunk_data = {
                'choices': [{
                    'delta': {'content': stats_text},
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(stats_chunk_data)}\n\n"
        else:
            answer = self._call_openai_api(system_prompt, final_prompt)
            # 输出token统计信息（非流式模式）
            stats_text = self._get_token_stats_text()
            yield answer + stats_text

    def _get_token_stats_text(self) -> str:
        """格式化token统计信息"""
        stats = self.token_stats
        stats_text = f"""

---

**📊 Token使用统计**
- 输入Token数: {stats['input_tokens']:,} 字符
- 输出Token数: {stats['output_tokens']:,} 字符  
- 总Token数: {stats['total_tokens']:,} 字符
- API调用次数: {stats['api_calls']} 次
- 平均每次调用: {stats['total_tokens']//max(stats['api_calls'], 1):,} 字符

*注: Token数量基于字符数估算，实际使用量可能略有差异*
"""
        return stats_text

    def _build_conversation_context(self, user_message: str, messages: List[dict]) -> str:
        """构建对话上下文"""
        if not messages or len(messages) <= 1:
            return "无历史对话"
        
        context_text = ""
        recent_messages = messages[-4:] if len(messages) > 4 else messages
        for msg in recent_messages:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = msg.get("content", "")
            if len(content) > 200:
                content = content[:200] + "..."
            context_text += f"{role}: {content}\n"
        
        return context_text

    def _summarize_collected_papers(self) -> str:
        """总结收集到的关键论文信息"""
        if not self.react_state['papers_collected']:
            return "未收集到关键论文信息"
        
        summary = f"收集到 {len(self.react_state['papers_collected'])} 篇关键论文:\n\n"
        for i, paper in enumerate(self.react_state['papers_collected'], 1):
            summary += f"=== 关键论文 {i} ===\n"
            summary += f"标题: {paper.get('title', '未知标题')}\n"
            summary += f"作者: {paper.get('authors', '未知作者')}\n"
            if paper.get('year'):
                summary += f"年份: {paper.get('year')}\n"
            if paper.get('venue'):
                summary += f"期刊/会议: {paper.get('venue')}\n"
            if paper.get('citation_count'):
                summary += f"引用数: {paper.get('citation_count')}\n"
            summary += f"相关性权重: {paper.get('relevance_weight', 1.0)}\n"
            if paper.get('key_findings'):
                summary += f"关键发现: {paper.get('key_findings')}\n"
            if paper.get('urls'):
                urls = paper.get('urls')
                if isinstance(urls, list) and urls:
                    summary += f"相关链接: {', '.join(urls)}\n"
            if paper.get('abstract'):
                # 限制摘要长度，避免过长
                abstract = paper.get('abstract')
                if len(abstract) > 500:
                    abstract = abstract[:500] + "..."
                summary += f"摘要: {abstract}\n"
            summary += "\n"
        
        return summary

    async def _react_loop(self, user_message: str, messages: List[dict], stream_mode: bool) -> AsyncGenerator[str, None]:
        """ReAct主循环"""
        # 重置状态和token统计
        self.react_state = {
            "papers_collected": [],  # 存储关键论文信息（字典格式）
            "query_history": [],
            "query_terms_used": set(),  # 已使用的查询词集合
            "extracted_keywords_history": set(),  # 历史提取的关键词集合
            "current_iteration": 0,
            "current_offset": 0,  # 当前偏移量
            "current_limit": 10,  # 当前每页数量
            "query_offsets": {}  # 记录每个查询词使用的偏移量 {query: offset}
        }
        
        # 重置token统计
        self.token_stats = {
            "input_tokens": 0, 
            "output_tokens": 0,
            "total_tokens": 0,
            "api_calls": 0
        }
        
        # 确保工具已加载
        try:
            async for tools_output in self._ensure_tools_loaded(stream_mode):
                yield tools_output
        except Exception as e:
            error_msg = f"❌ Semantic Scholar MCP工具加载失败: {str(e)}"
            if stream_mode:
                for chunk in self._emit_processing(error_msg, "mcp_discovery"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield error_msg + "\n"
            return
        
        # 1. Reasoning阶段（只在开始执行一次）
        initial_decision = None
        async for phase_result in self._reasoning_phase(user_message, messages, stream_mode):
            result_type, content = phase_result
            if result_type == "processing":
                yield content
            elif result_type == "decision":
                initial_decision = content
                break
        
        # 检查是否需要搜索
        if not initial_decision.get("need_search", False) or initial_decision.get("sufficient_info", False):
            # 直接进入答案生成阶段
            async for answer_chunk in self._answer_generation_phase(user_message, messages, stream_mode):
                yield answer_chunk
            return
        
        # 2. Action-Observation循环
        max_iterations = self.valves.MAX_REACT_ITERATIONS
        current_query = initial_decision.get("query", "")
        
        while self.react_state['current_iteration'] < max_iterations and current_query:
            self.react_state['current_iteration'] += 1
            
            # Action阶段 - 获取当前查询的偏移量信息
            current_offset = self.react_state.get("current_offset", 0)
            current_limit = self.react_state.get("current_limit", 10)
            
            action_result = None
            async for phase_result in self._action_phase(current_query, current_limit, current_offset, stream_mode):
                result_type, content = phase_result
                if result_type == "processing":
                    yield content
                elif result_type == "result":
                    action_result = content
                    break
            
            # 等待action完全执行完成后再进行observation
            if action_result is None:
                break
                
            # Observation阶段
            observation = None
            async for phase_result in self._observation_phase(action_result, current_query, user_message, stream_mode):
                result_type, content = phase_result
                if result_type == "processing":
                    yield content
                elif result_type == "observation":
                    observation = content
                    break
            
            # 检查是否需要分页（优先级高于新查询）
            if observation and observation.get("need_pagination", False):
                # 分页：使用相同查询词，更新偏移量
                new_offset = observation.get("new_offset", current_offset + current_limit)
                new_limit = observation.get("limit", current_limit)
                
                # 更新偏移量状态
                self.react_state["current_offset"] = new_offset
                self.react_state["current_limit"] = new_limit
                
                # 继续使用相同查询词进行下一轮搜索
                # current_query 保持不变
                continue
            
            # 检查已收集论文数量，如果达到阈值则强制停止
            collected_papers_count = len(self.react_state['papers_collected'])
            if collected_papers_count >= self.valves.MIN_PAPERS_THRESHOLD:
                if stream_mode:
                    stop_content = f"\n✅ 已收集足够论文({collected_papers_count}篇 >= {self.valves.MIN_PAPERS_THRESHOLD}篇阈值)，停止搜索"
                    for chunk in self._emit_processing(stop_content, "observation"):
                        yield f'data: {json.dumps(chunk)}\n\n'
                break
            
            # 检查是否需要继续搜索
            if not observation or not observation.get("need_more_search", False) or observation.get("sufficient_info", False):
                break
            
            # 获取下一轮查询词（重置偏移量为0）
            current_query = observation.get("suggested_query", "")
            self.react_state["current_offset"] = 0  # 新查询词从偏移量0开始
            
            # 如果建议的查询词已经使用过，则停止
            if current_query and current_query.lower() in self.react_state['query_terms_used']:
                break
        
        # 3. 答案生成阶段
        async for answer_chunk in self._answer_generation_phase(user_message, messages, stream_mode):
            yield answer_chunk

    def pipe(self, user_message: str, model_id: str, messages: List[dict], body: dict) -> Union[str, Generator, Iterator]:
        """主管道函数"""
        if not user_message or not user_message.strip():
            yield "❌ 请输入有效的学术论文搜索问题"
            return

        stream_mode = self.valves.ENABLE_STREAMING
        
        try:
            # 在同步环境中运行异步ReAct循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async_gen = self._react_loop(user_message, messages, stream_mode)
                
                while True:
                    try:
                        result = loop.run_until_complete(async_gen.__anext__())
                        yield result
                    except StopAsyncIteration:
                        break
                
                # 流式模式结束标记
                if stream_mode:
                    done_msg = {
                        'choices': [{
                            'delta': {},
                            'finish_reason': 'stop'
                        }]
                    }
                    yield f"data: {json.dumps(done_msg)}\n\n"
                    yield "data: [DONE]\n\n"
                    
            finally:
                loop.close()

        except Exception as e:
            error_msg = f"❌ Pipeline执行错误: {str(e)}"
            if stream_mode:
                error_chunk = {
                    'choices': [{
                        'delta': {'content': error_msg},
                        'finish_reason': 'stop'
                    }]
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"
                yield "data: [DONE]\n\n"
            else:
                yield error_msg
