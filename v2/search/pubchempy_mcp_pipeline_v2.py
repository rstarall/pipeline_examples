"""
PubChemPy MCP Pipeline V2 - 基于MCP协议的化学信息查询管道

功能特性:
1. 通过MCP JSON-RPC协议的tools/list方法动态发现工具，根据tag进行过滤
2. 使用MCP JSON-RPC协议进行工具调用
3. 支持流式输出和多轮工具调用
4. 智能工具选择和参数生成
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
        MCP_TAG: str
        MCP_TIMEOUT: int

    def __init__(self):
        self.name = "PubChemPy MCP Chemical Pipeline V2"
        
        # 初始化token统计
        self.token_stats = {
            "input_tokens": 0, 
            "output_tokens": 0,
            "total_tokens": 0
        }
        
        # MCP工具缓存
        self.mcp_tools = {}
        self.tools_loaded = False
        
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
                "MAX_TOOL_CALLS": int(os.getenv("MAX_TOOL_CALLS", "5")),
                
                # MCP配置
                "MCP_SERVER_URL": os.getenv("MCP_SERVER_URL", "http://localhost:8989"),
                "MCP_TAG": os.getenv("MCP_TAG", "search"),
                "MCP_TIMEOUT": int(os.getenv("MCP_TIMEOUT", "30")),
            }
        )

    async def on_startup(self):
        print(f"PubChemPy MCP Chemical Pipeline V2启动: {__name__}")
        
        # 验证必需的API密钥
        if not self.valves.OPENAI_API_KEY:
            print("❌ 缺少OpenAI API密钥，请设置OPENAI_API_KEY环境变量")
        
        # 验证MCP服务器地址
        print(f"🔗 MCP服务器地址: {self.valves.MCP_SERVER_URL}")
        print(f"🏷️ MCP标签: {self.valves.MCP_TAG}")
        if not self.valves.MCP_SERVER_URL:
            print("❌ 缺少MCP服务器地址，请设置MCP_SERVER_URL环境变量")
        
        # 发现MCP工具
        try:
            await self._discover_mcp_tools()
            print(f"✅ 成功发现 {len(self.mcp_tools)} 个MCP工具")
        except Exception as e:
            print(f"❌ MCP工具发现失败: {e}")

    async def on_shutdown(self):
        print(f"PubChemPy MCP Chemical Pipeline V2关闭: {__name__}")
        print("🔚 Pipeline已关闭")

    async def _initialize_mcp_session(self):
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
                        "name": "PubChemPy MCP Pipeline",
                        "version": "2.0.0"
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
                            logger.info(f"Got session ID from server: {self.session_id}")
                        
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
                                logger.warning(f"Initialized notification failed: {notify_response.status}")
                        
                        logger.info("MCP session initialized successfully")
                    else:
                        error_text = await response.text()
                        raise Exception(f"Initialize failed - HTTP {response.status}: {error_text}")
                        
        except Exception as e:
            logger.error(f"MCP session initialization failed: {e}")
            raise

    async def _discover_mcp_tools(self):
        """通过MCP JSON-RPC协议发现服务器工具"""
        if not self.valves.MCP_SERVER_URL:
            raise Exception("MCP服务器地址未配置")
        
        # 首先初始化MCP会话
        if not hasattr(self, '_session_initialized'):
            await self._initialize_mcp_session()
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
                        
                        # 根据tag过滤工具并解析工具信息
                        for tool in tools:
                            tool_tags = tool.get("tags", [])
                            # 只加载匹配指定tag的工具
                            if self.valves.MCP_TAG in tool_tags:
                                tool_name = tool.get("name")
                                if tool_name:
                                    self.mcp_tools[tool_name] = {
                                        "name": tool_name,
                                        "description": tool.get("description", ""),
                                        "input_schema": tool.get("inputSchema", {}),
                                        "tags": tool_tags
                                    }
                        
                        self.tools_loaded = True
                        logger.info(f"Successfully discovered {len(self.mcp_tools)} MCP tools with tag '{self.valves.MCP_TAG}'")
                    else:
                        error_text = await response.text()
                        raise Exception(f"HTTP {response.status}: {error_text}")
                        
        except Exception as e:
            logger.error(f"MCP tool discovery failed: {e}")
            raise



    async def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """使用MCP JSON-RPC协议调用工具"""
        if not self.valves.MCP_SERVER_URL:
            return {"error": "MCP服务器地址未配置"}
        
        if not self.tools_loaded:
            try:
                await self._discover_mcp_tools()
            except Exception as e:
                return {"error": f"工具发现失败: {str(e)}"}
        
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
        
        if "content" in result and result["content"]:
            # 提取文本内容
            text_content = ""
            for content in result["content"]:
                if content.get("type") == "text":
                    text_content += content.get("text", "") + "\n"
            return text_content.strip()
        elif "error" in result:
            return f"工具执行失败: {result['error']}"
        else:
            return "工具执行未返回有效结果"

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
        base_prompt = """你是一个专业的化学信息助手，能够使用MCP工具来查询化学物质的详细信息。

🔧 可用工具：
"""
        
        # 动态添加工具信息
        if self.mcp_tools:
            for tool_name, tool_info in self.mcp_tools.items():
                base_prompt += f"""
工具名称: {tool_name}
描述: {tool_info.get('description', '无描述')}
标签: {', '.join(tool_info.get('tags', []))}
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
1. 当用户询问化学物质信息时，分析他们的需求并选择合适的工具
2. PubChem数据库主要使用英文，因此query参数应为英文名称、分子式或SMILES字符串
3. 如果用户提供中文化学名称，请转换为对应的英文名称
4. 优先使用英文化学名称搜索（更准确）

转换示例：
- "咖啡因" → "caffeine" (中文转英文名)
- "H2O" → "H2O" (分子式保持不变)
- "CCO" → "CCO" (SMILES保持不变)

🔄 工具调用格式：
如果需要调用工具，请回复：
TOOL_CALL:<工具名称>:<JSON参数>

示例：
- TOOL_CALL:search_chemical:{"query": "caffeine", "search_type": "name"}
- TOOL_CALL:search_chemical:{"query": "H2O", "search_type": "formula"}
- TOOL_CALL:search_chemical:{"query": "CCO", "search_type": "smiles"}

如果不需要工具调用，请直接回答用户问题。可以多次调用工具获取更完整的信息。
"""
        
        return base_prompt

    async def _process_user_message(self, user_message: str, messages: List[dict], stream_mode: bool) -> AsyncGenerator[str, None]:
        """处理用户消息，支持多轮MCP工具调用"""
        
        # 确保工具已加载
        if not self.tools_loaded:
            try:
                if stream_mode:
                    for chunk in self._emit_processing("🔍 正在发现MCP工具...", "mcp_discovery"):
                        yield f'data: {json.dumps(chunk)}\n\n'
                else:
                    yield "🔍 正在发现MCP工具...\n"
                
                await self._discover_mcp_tools()
                
                discovery_info = f"✅ 发现 {len(self.mcp_tools)} 个MCP工具: {', '.join(self.mcp_tools.keys())}"
                if stream_mode:
                    for chunk in self._emit_processing(discovery_info, "mcp_discovery"):
                        yield f'data: {json.dumps(chunk)}\n\n'
                else:
                    yield discovery_info + "\n"
                    
            except Exception as e:
                error_msg = f"❌ MCP工具发现失败: {str(e)}"
                if stream_mode:
                    for chunk in self._emit_processing(error_msg, "mcp_discovery"):
                        yield f'data: {json.dumps(chunk)}\n\n'
                else:
                    yield error_msg + "\n"
                return
        
        # 获取系统提示词
        system_prompt = self._get_system_prompt()
        
        # 构建对话历史
        conversation_history = []
        if messages and len(messages) > 1:
            # 取最近的几轮对话作为上下文
            recent_messages = messages[-6:] if len(messages) > 6 else messages
            for msg in recent_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role in ["user", "assistant"]:
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

请根据上下文和当前问题，决定是否需要调用MCP工具。如果需要，请按照指定格式回复工具调用。
回答要忠于上下文、当前问题、工具返回的信息。"""
        
        tool_call_count = 0
        collected_tool_results = []
        
        while tool_call_count < self.valves.MAX_TOOL_CALLS:
            # 获取AI响应
            ai_response = self._call_openai_api(system_prompt, full_user_prompt)
            
            # 检查是否需要调用工具 - 支持通用格式 TOOL_CALL:<工具名称>:<JSON参数>
            if ai_response.startswith("TOOL_CALL:"):
                tool_call_count += 1
                
                # 解析工具调用
                try:
                    # 去除前缀并解析
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
                        error_msg = f"工具 '{tool_name}' 不存在"
                        if stream_mode:
                            for chunk in self._emit_processing(f"❌ {error_msg}", "tool_calling"):
                                yield f'data: {json.dumps(chunk)}\n\n'
                        else:
                            yield f"❌ {error_msg}\n"
                        break
                    
                    # 显示工具调用信息
                    call_info = f"🔧 正在调用MCP工具 '{tool_name}'（第{tool_call_count}次）..."
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
                    
                    # 显示工具调用结果
                    result_info = f"✅ 工具调用结果:\n{tool_result[:500]}{'...' if len(tool_result) > 500 else ''}"
                    if stream_mode:
                        for chunk in self._emit_processing(result_info, "tool_calling"):
                            yield f'data: {json.dumps(chunk)}\n\n'
                    else:
                        yield result_info + "\n"
                    
                    # 收集工具结果
                    collected_tool_results.append({
                        "tool": tool_name,
                        "call": tool_args,
                        "result": tool_result
                    })
                    
                    # 更新对话上下文，包含工具结果
                    tool_context = f"[MCP工具调用结果 {tool_call_count}]\n工具: {tool_name}\n查询: {tool_args}\n结果: {tool_result}\n\n"
                    full_user_prompt = f"{full_user_prompt}\n\n{tool_context}基于以上工具调用结果，请继续回答用户的问题。如果需要更多信息，可以继续调用工具。"
                    
                    # 继续下一轮，看是否需要更多工具调用
                    continue
                    
                except (json.JSONDecodeError, ValueError) as e:
                    error_msg = f"工具调用格式错误: {str(e)}"
                    if stream_mode:
                        for chunk in self._emit_processing(f"❌ {error_msg}", "tool_calling"):
                            yield f'data: {json.dumps(chunk)}\n\n'
                    else:
                        yield f"❌ {error_msg}\n"
                    break
            else:
                # 不需要工具调用，生成最终回答
                break
        
        # 生成最终回答
        if collected_tool_results:
            # 如果有工具调用结果，基于结果生成回答
            final_system_prompt = "你是专业的化学信息专家，请基于提供的MCP工具调用结果，为用户提供准确、详细的回答。"
            
            tool_summary = "基于以下MCP工具调用结果:\n\n"
            for i, result in enumerate(collected_tool_results, 1):
                tool_name = result.get('tool', 'unknown')
                tool_call = result.get('call', {})
                tool_result = result.get('result', '')
                tool_summary += f"工具调用{i}: {tool_name}\n"
                tool_summary += f"参数{i}: {json.dumps(tool_call, ensure_ascii=False)}\n"
                tool_summary += f"结果{i}: {tool_result}\n\n"
            
            final_user_prompt = f"{tool_summary}用户问题: {user_message}\n\n请基于以上工具调用结果为用户提供准确详细的回答。"
            
            if stream_mode:
                # 流式模式开始生成回答的标识
                answer_start_msg = {
                    'choices': [{
                        'delta': {
                            'content': "\n**🧪 基于MCP工具调用结果回答**\n"
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(answer_start_msg)}\n\n"
                
                # 流式生成最终回答
                for chunk in self._stream_openai_response(final_user_prompt, final_system_prompt):
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
                yield "🧪 **基于MCP工具调用结果回答**\n"
                final_answer = self._call_openai_api(final_system_prompt, final_user_prompt)
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
                yield ai_response

    def pipe(self, user_message: str, model_id: str, messages: List[dict], body: dict) -> Union[str, Generator, Iterator]:
        """主管道函数"""
        # 重置token统计
        self._reset_token_stats()

        if self.valves.DEBUG_MODE:
            print(f"🧪 MCP化学助手V2收到消息: {user_message}")
            print(f"🔧 模型ID: {model_id}")
            print(f"📜 历史消息数量: {len(messages) if messages else 0}")
            print(f"🔗 MCP服务器: {self.valves.MCP_SERVER_URL}")
            print(f"🏷️ MCP标签: {self.valves.MCP_TAG}")

        # 验证输入
        if not user_message or not user_message.strip():
            yield "❌ 请输入有效的化学问题或查询内容"
            return

        # 检查是否是流式模式  
        stream_mode = body.get("stream", False) and self.valves.ENABLE_STREAMING
        
        try:
            # MCP服务发现阶段
            if stream_mode:
                for chunk in self._emit_processing("🔍 正在准备MCP服务...", "mcp_discovery"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield "🔍 **阶段1**: 正在准备MCP服务...\n"
            
            # 在同步环境中运行异步代码
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # 处理用户消息，可能包含多次工具调用
                async def run_process():
                    results = []
                    async for result in self._process_user_message(user_message, messages, stream_mode):
                        results.append(result)
                    return results
                
                # 获取所有结果并逐个yield
                results = loop.run_until_complete(run_process())
                for result in results:
                    yield result
                
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