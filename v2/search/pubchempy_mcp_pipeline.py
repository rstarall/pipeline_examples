"""
参考v2\search\pubchempy_mcp\src\llm_use.py编写本pipeline
1.采用流式输出,允许中间工具调用(流式回答等待不要返回Done),调用完继续流式回答，直到结束返回Done
2.工具调用时使用_emit_processing输出调用和返回结果
3.注意你的提示词是一个化合物化学公式问答助手，根据搜索返回的json进行知识问答
4.参考v2\search\serper_openai_pipeline.py，不需要搜索，可多次调用工具
"""

import os
import json
import requests
import asyncio
import aiohttp
import time
from typing import List, Union, Generator, Iterator, Dict, Any, Optional
from pydantic import BaseModel
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 后端阶段标题映射
STAGE_TITLES = {
    "chemical_analysis": "化学分析",
    "tool_calling": "工具调用",
    "answer_generation": "生成回答",
}

STAGE_GROUP = {
    "chemical_analysis": "stage_group_1",
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
        MCP_REMOTE_URL: str
        MCP_TIMEOUT: int

    def __init__(self):
        self.name = "PubChemPy MCP Chemical Pipeline"
        
        # 初始化token统计
        self.token_stats = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        }
        
        # MCP客户端配置
        self.mcp_request_id = 1
        
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
                "MCP_REMOTE_URL": os.getenv("MCP_REMOTE_URL", "http://localhost:8000/mcp"),
                "MCP_TIMEOUT": int(os.getenv("MCP_TIMEOUT", "30")),
            }
        )

    async def on_startup(self):
        print(f"PubChemPy MCP Chemical Pipeline启动: {__name__}")
        
        # 验证必需的API密钥
        if not self.valves.OPENAI_API_KEY:
            print("❌ 缺少OpenAI API密钥，请设置OPENAI_API_KEY环境变量")
        
        # 验证MCP服务器地址
        print(f"🔗 MCP服务器地址: {self.valves.MCP_REMOTE_URL}")
        if not self.valves.MCP_REMOTE_URL:
            print("❌ 缺少MCP服务器地址，请设置MCP_REMOTE_URL环境变量")

    async def on_shutdown(self):
        print(f"PubChemPy MCP Chemical Pipeline关闭: {__name__}")
        print("🔚 Pipeline已关闭")



    async def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """通过HTTP调用远程MCP工具"""
        if not self.valves.MCP_REMOTE_URL:
            return {"error": "MCP服务器地址未配置"}
        
        try:
            # 构建MCP调用请求
            request = {
                "jsonrpc": "2.0",
                "id": self.mcp_request_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            
            # 增加请求ID
            self.mcp_request_id += 1
            
            # 发送HTTP请求到远程MCP服务器
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            # 使用aiohttp进行异步HTTP请求
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.valves.MCP_REMOTE_URL,
                    headers=headers,
                    json=request,
                    timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        
                        if "result" in result:
                            return result["result"]
                        else:
                            return {"error": result.get("error", "Unknown error")}
                    else:
                        return {"error": f"HTTP {response.status}: {await response.text()}"}
                
        except asyncio.TimeoutError:
            logger.error("MCP工具调用超时")
            return {"error": "请求超时"}
        except aiohttp.ClientError as e:
            logger.error(f"MCP HTTP请求失败: {e}")
            return {"error": f"HTTP请求失败: {str(e)}"}
        except Exception as e:
            logger.error(f"MCP工具调用失败: {e}")
            return {"error": str(e)}

    async def _search_chemical(self, query: str, search_type: str = "formula", use_fallback: bool = False) -> str:
        """搜索化学物质"""
        result = await self._call_mcp_tool("search_chemical", {
            "query": query,
            "search_type": search_type,
            "use_fallback": use_fallback
        })
        
        if "content" in result and result["content"]:
            # 提取文本内容
            text_content = ""
            for content in result["content"]:
                if content.get("type") == "text":
                    text_content += content.get("text", "") + "\n"
            return text_content.strip()
        elif "error" in result:
            return f"搜索失败: {result['error']}"
        else:
            return "未找到相关化学信息"

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
        """获取系统提示词"""
        return """你是一个专业的化学信息助手。你可以帮助用户查询化学物质的详细信息。

当用户询问以下内容时，你需要调用化学搜索工具：
1. 询问特定化学物质的信息（如咖啡因、水、乙醇等）
2. 提供分子式并询问对应的化合物（如H2O、C8H10N4O2等）
3. 提供SMILES字符串并询问化合物信息（如CCO、CN1C=NC2=C1C(=O)N(C(=O)N2C)C等）
4. 询问化学物质的性质、结构、同义词等

⚠️ 重要：PubChem数据库主要使用英文，因此query参数必须为英文名称、分子式或SMILES字符串。

🧠 智能转换规则：
- 如果用户提供中文化学名称，请根据你的化学知识将其转换为对应的英文名称
- 优先使用英文化学名称搜索（推荐，更准确）
- 如果不确定中文名称对应的英文名，再考虑使用分子式搜索
- 如果用户直接提供了分子式或SMILES，直接使用

转换示例：
- "咖啡因" → "caffeine" (中文转英文名)
- "H2O" → "H2O" (分子式保持不变)
- "CCO" → "CCO" (SMILES保持不变)

如果你判断需要搜索化学信息，请回复：
TOOL_CALL:search_chemical:{"query": "转换后的英文/分子式/SMILES", "search_type": "搜索类型"}

其中search_type可以是：
- "name": 按英文化学名称搜索（推荐，更准确）
- "formula": 按分子式搜索
- "smiles": 按SMILES字符串搜索

调用示例：
- 用户问"咖啡因的分子式是什么" → TOOL_CALL:search_chemical:{"query": "caffeine", "search_type": "name"}
- 用户问"H2O是什么化合物" → TOOL_CALL:search_chemical:{"query": "H2O", "search_type": "formula"}
- 用户问"CCO代表什么" → TOOL_CALL:search_chemical:{"query": "CCO", "search_type": "smiles"}

如果不需要搜索化学信息，请正常回答用户的问题。如果需要多次调用工具来获取更多信息，可以继续调用。"""

    async def _process_user_message(self, user_message: str, messages: List[dict], stream_mode: bool) -> Generator:
        """处理用户消息，支持多轮工具调用"""
        
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

请根据上下文和当前问题，决定是否需要调用化学搜索工具。如果需要，请按照指定格式回复工具调用。"""
        
        tool_call_count = 0
        collected_tool_results = []
        
        while tool_call_count < self.valves.MAX_TOOL_CALLS:
            # 获取AI响应
            ai_response = self._call_openai_api(system_prompt, full_user_prompt)
            
            # 检查是否需要调用工具
            if ai_response.startswith("TOOL_CALL:search_chemical:"):
                tool_call_count += 1
                
                # 显示工具调用信息
                if stream_mode:
                    for chunk in self._emit_processing(f"🔧 正在调用化学搜索工具（第{tool_call_count}次）...", "tool_calling"):
                        yield f'data: {json.dumps(chunk)}\n\n'
                else:
                    yield f"🔧 正在调用化学搜索工具（第{tool_call_count}次）...\n"
                
                # 解析工具调用参数
                tool_args_str = ai_response.replace("TOOL_CALL:search_chemical:", "")
                try:
                    tool_args = json.loads(tool_args_str)
                    
                    # 显示工具调用参数
                    tool_info = f"📝 工具调用参数: {json.dumps(tool_args, ensure_ascii=False)}"
                    if stream_mode:
                        for chunk in self._emit_processing(tool_info, "tool_calling"):
                            yield f'data: {json.dumps(chunk)}\n\n'
                    else:
                        yield tool_info + "\n"
                    
                    # 调用MCP工具
                    tool_result = await self._search_chemical(
                        query=tool_args.get("query", ""),
                        search_type=tool_args.get("search_type", "formula"),
                        use_fallback=tool_args.get("use_fallback", False)
                    )
                    
                    # 显示工具调用结果
                    result_info = f"✅ 工具调用结果:\n{tool_result[:500]}{'...' if len(tool_result) > 500 else ''}"
                    if stream_mode:
                        for chunk in self._emit_processing(result_info, "tool_calling"):
                            yield f'data: {json.dumps(chunk)}\n\n'
                    else:
                        yield result_info + "\n"
                    
                    # 收集工具结果
                    collected_tool_results.append({
                        "call": tool_args,
                        "result": tool_result
                    })
                    
                    # 更新对话上下文，包含工具结果
                    tool_context = f"[化学搜索结果 {tool_call_count}]\n查询: {tool_args}\n结果: {tool_result}\n\n"
                    full_user_prompt = f"{full_user_prompt}\n\n{tool_context}基于以上搜索结果，请继续回答用户的问题。如果需要更多信息，可以继续调用工具。"
                    
                    # 继续下一轮，看是否需要更多工具调用
                    continue
                    
                except json.JSONDecodeError:
                    error_msg = "工具调用格式错误，无法解析参数"
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
            final_system_prompt = "你是专业的化学信息专家，请基于提供的化学搜索结果，为用户提供准确、详细的回答。"
            
            tool_summary = "基于以下化学搜索结果:\n\n"
            for i, result in enumerate(collected_tool_results, 1):
                tool_summary += f"搜索{i}: {json.dumps(result['call'], ensure_ascii=False)}\n"
                tool_summary += f"结果{i}: {result['result']}\n\n"
            
            final_user_prompt = f"{tool_summary}用户问题: {user_message}\n\n请基于以上搜索结果为用户提供准确详细的回答。"
            
            if stream_mode:
                # 流式模式开始生成回答的标识
                answer_start_msg = {
                    'choices': [{
                        'delta': {
                            'content': "\n**🧪 基于化学数据库信息回答**\n"
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
                yield "🧪 **基于化学数据库信息回答**\n"
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
            print(f"🧪 化学助手收到消息: {user_message}")
            print(f"🔧 模型ID: {model_id}")
            print(f"📜 历史消息数量: {len(messages) if messages else 0}")

        # 验证输入
        if not user_message or not user_message.strip():
            yield "❌ 请输入有效的化学问题或查询内容"
            return

        # 检查是否是流式模式  
        stream_mode = body.get("stream", False) and self.valves.ENABLE_STREAMING
        
        try:
            # 化学分析阶段
            if stream_mode:
                for chunk in self._emit_processing("🧪 正在分析化学问题...", "chemical_analysis"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield "🧪 **阶段1**: 正在分析化学问题...\n"
            
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