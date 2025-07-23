"""
基于意图识别的问答Pipeline

这是一个支持workflow和agent两种模式的智能问答pipeline，
能够根据用户选择的模式调用相应的后端接口，支持流式输出和多轮对话。
"""

import json
import os
import asyncio
import requests
import uuid
from typing import List, Dict, Any, Union, Generator, Iterator,Literal, Optional, Callable
from pydantic import BaseModel, Field

# 常量定义
DEFAULT_WORKFLOW_URL = "http://127.0.0.1:8000/api/v1/conversations/{}/stream"
DEFAULT_AGENT_URL = "http://127.0.0.1:8000/api/v1/conversations/{}/stream"
DEFAULT_CREATE_CONVERSATION_URL = "http://127.0.0.1:8000/api/v1/conversations"

# 执行模式常量
WORKFLOW_MODE = "workflow"
AGENT_MODE = "agent"

# 响应类型常量
STATUS_TYPE = "status"
CONTENT_TYPE = "content"
PROGRESS_TYPE = "progress"
ERROR_TYPE = "error"

# HTTP请求头
DEFAULT_HEADERS = {
    'accept': 'text/event-stream',
    'Content-Type': 'application/json',
}

# 状态消息
STATUS_MESSAGES = {
    "initializing": "正在初始化对话...",
    "creating_conversation": "正在创建对话会话...",
    "sending_message": "正在发送消息...",
    "processing": "正在处理您的问题...",
    "streaming": "正在获取流式响应...",
    "completed": "处理完成",
    "error": "处理过程中出现错误"
}


class Pipeline:
    """意图识别问答Pipeline"""

    class Valves(BaseModel):
        """Pipeline配置参数"""

        # 后端服务配置
        BACKEND_BASE_URL: str = Field(
            default="http://117.50.252.245:8888",
            description="后端服务基础URL"
        )

        # 知识库API配置
        KNOWLEDGE_API_URL: str = Field(
            default="http://117.50.252.245:3000",
            description="知识库API基础URL"
        )

        # 默认执行模式
        DEFAULT_MODE: Literal["workflow", "agent"] = Field(
            default="workflow",
            description="默认执行模式 (workflow/agent)"
        )

        # 用户ID配置
        DEFAULT_USER_ID: str = Field(
            default="default_user",
            description="默认用户ID"
        )

        # 知识库配置
        KNOWLEDGE_BASES: str = Field(
            default='[{"name": "test", "description": "默认知识库"}]',
            description="知识库配置，JSON格式数组，包含name和description字段"
        )

        # 请求超时配置
        REQUEST_TIMEOUT: int = Field(
            default=300,
            description="请求超时时间（秒）"
        )

        # 流式响应配置
        STREAM_CHUNK_SIZE: int = Field(
            default=1024,
            description="流式响应块大小"
        )

        # 调试模式
        DEBUG_MODE: bool = Field(
            default=False,
            description="是否启用调试模式"
        )

    def __init__(self):
        """初始化Pipeline"""
        self.id = "intent_pipeline"
        self.name = "Intent Workflow Agent Pipeline"
        self.description = "基于意图识别的智能问答Pipeline，支持workflow和agent两种模式"

        # 初始化配置参数
        self.valves = self.Valves(
            **{k: os.getenv(k, v.default) for k, v in self.Valves.model_fields.items()}
        )
        
        # 检查是否有外部传入的知识库配置
        # 用户可以通过UI配置知识库

        # 对话会话缓存
        self._conversation_cache: Dict[str, str] = {}

        # 构建API端点URL
        self._build_api_urls()
        
        # 验证和解析知识库配置
        self._validate_knowledge_bases()

    def _build_api_urls(self) -> None:
        """构建API端点URL"""
        base_url = self.valves.BACKEND_BASE_URL.rstrip('/')
        self.create_conversation_url = f"{base_url}/api/v1/conversations"
        self.stream_chat_url = f"{base_url}/api/v1/conversations/{{}}/stream"

    async def on_startup(self):
        """Pipeline启动时调用"""
        pass

    async def on_shutdown(self):
        """Pipeline关闭时调用"""
        # 清理对话缓存
        self._conversation_cache.clear()

    def pipe(
        self,
        user_message: str,
        model_id: str,
        messages: List[dict],
        body: dict,
        __event_emitter__= None,
        __event_call__=None
    ) -> Union[str, Generator, Iterator]:
        """
        Pipeline主要处理方法

        Args:
            user_message: 用户消息
            model_id: 模型ID
            messages: 消息历史
            body: 请求体
            __event_emitter__: 事件发射器
            __event_call__: 事件调用器

        Returns:
            流式响应生成器
        """
        # 获取用户token
        user_token = body.get("user", {}).get("token")

        # 从body中获取执行模式和用户ID
        mode = body.get("mode", self.valves.DEFAULT_MODE)
        user_id = body.get("user_id", self.valves.DEFAULT_USER_ID)
        
        # 获取用户信息
        user_info = body.get("user", {})
        if not user_id or user_id == self.valves.DEFAULT_USER_ID:
            user_id = user_info.get("id", self.valves.DEFAULT_USER_ID)
        
        # 获取会话信息 - 支持前台传入的会话ID
        session_info = self._get_session_info(body)
        chat_id = session_info["chat_id"]
        session_id = session_info["session_id"]
        is_temporary = session_info["is_temporary"]

        # 验证执行模式
        if mode not in [WORKFLOW_MODE, AGENT_MODE]:
            mode = self.valves.DEFAULT_MODE

        # 生成缓存键 - 使用chat_id作为主键
        cache_key = f"{user_id}_{chat_id}_{mode}"
        
        # 每次调用都动态解析KNOWLEDGE_BASES配置
        self._validate_knowledge_bases()
        actual_knowledge_bases = self._parsed_knowledge_bases

        try:
            # 异步处理流式响应
            return self._process_stream_response(
                user_message=user_message,
                messages=messages,
                mode=mode,
                user_id=user_id,
                cache_key=cache_key,
                chat_id=chat_id,
                is_temporary=is_temporary,
                user_token=user_token,
                knowledge_bases=actual_knowledge_bases,
                __event_emitter__= __event_emitter__
            )
        except Exception as e:
            error_msg = f"Pipeline处理失败: {str(e)}"
            return self._create_error_response(error_msg)

    def _get_session_info(self, body: dict) -> dict:
        """
        获取会话信息，支持前台传入的会话ID
        
        Args:
            body: 请求体
            
        Returns:
            包含会话信息的字典
        """
        metadata = body.get("metadata", {})
        
        # 方式1: 从metadata中获取chat_id
        chat_id = metadata.get("chat_id")
        
        # 方式2: 直接从body中获取chat_id
        if not chat_id:
            chat_id = body.get("chat_id")
            
        # 方式3: 处理临时会话的session_id
        session_id = metadata.get("session_id")
        is_temporary = False
        
        # 处理临时会话
        if chat_id == "local" or not chat_id:
            is_temporary = True
            if session_id:
                chat_id = f"temporary-session-{session_id}"
            else:
                # 如果没有session_id，生成一个临时会话ID
                chat_id = f"temporary-session-{str(uuid.uuid4())}"
        
        # 如果仍然没有chat_id，生成一个默认的
        if not chat_id:
            chat_id = str(uuid.uuid4())
            is_temporary = True
            
        return {
            "chat_id": chat_id,
            "session_id": session_id,
            "is_temporary": is_temporary,
            "metadata": metadata
        }

    def _process_stream_response(
        self,
        user_message: str,
        messages: List[dict],
        mode: str,
        user_id: str,
        cache_key: str,
        chat_id: str,
        is_temporary: bool,
        user_token: str = None,
        knowledge_bases: List[Dict[str, str]] = None,
        __event_emitter__= None
    ) -> Generator[str, None, None]:
        """
        处理流式响应

        Args:
            user_message: 用户消息
            messages: 消息历史
            mode: 执行模式
            user_id: 用户ID
            cache_key: 缓存键
            chat_id: 前台传入的会话ID
            is_temporary: 是否为临时会话
            user_token: 用户认证token
            __event_emitter__: 事件发射器

        Yields:
            流式响应内容
        """
        conversation_id = None

        try:
            # 发送初始化状态
            yield from self._emit_status(
                __event_emitter__,
                STATUS_MESSAGES["initializing"]
            )

            # 获取或创建对话ID
            conversation_id = self._get_or_create_conversation(
                user_id=user_id,
                mode=mode,
                cache_key=cache_key,
                chat_id=chat_id,
                is_temporary=is_temporary,
                user_token=user_token,
                knowledge_bases=knowledge_bases,
                __event_emitter__=__event_emitter__
            )

            if not conversation_id:
                yield from self._create_error_response("无法创建对话会话")
                return

            # 发送消息并获取流式响应
            yield from self._send_message_and_stream(
                conversation_id=conversation_id,
                user_message=user_message,
                messages=messages,
                user_id=user_id,
                mode=mode,
                user_token=user_token,
                knowledge_bases=knowledge_bases,
                __event_emitter__=__event_emitter__
            )

        except Exception as e:
            error_msg = f"流式处理错误: {str(e)}"

            yield from self._emit_status(
                __event_emitter__,
                STATUS_MESSAGES["error"]
            )
            yield from self._create_error_response(error_msg)

    def _get_or_create_conversation(
        self,
        user_id: str,
        mode: str,
        cache_key: str,
        chat_id: str,
        is_temporary: bool,
        user_token: str = None,
        knowledge_bases: List[Dict[str, str]] = None,
        __event_emitter__=None
    ) -> Optional[str]:
        """
        获取或创建对话会话

        Args:
            user_id: 用户ID
            mode: 执行模式
            cache_key: 缓存键
            chat_id: 前台传入的会话ID
            is_temporary: 是否为临时会话
            user_token: 用户认证token
            __event_emitter__: 事件发射器

        Returns:
            对话ID，失败时返回None
        """
        try:
            # 如果前台传入了非临时会话ID，优先使用前台传入的会话ID
            if chat_id and not is_temporary and not chat_id.startswith("temporary-session-"):
                # 检查缓存中是否已有对话ID
                if cache_key in self._conversation_cache:
                    conversation_id = self._conversation_cache[cache_key]
                    if self.valves.DEBUG_MODE:
                        print(f"使用缓存的对话ID: {conversation_id}")
                    return conversation_id
                
                # 如果没有缓存，直接使用前台传入的会话ID
                conversation_id = chat_id
                self._conversation_cache[cache_key] = conversation_id
                return conversation_id

            # 对于临时会话或没有传入会话ID的情况，检查缓存
            if cache_key in self._conversation_cache:
                conversation_id = self._conversation_cache[cache_key]
                return conversation_id

            # 发送创建对话状态
            list(self._emit_status(
                __event_emitter__,
                STATUS_MESSAGES["creating_conversation"]
            ))

            # 创建新对话
            conversation_id = self._create_new_conversation(
                user_id=user_id,
                mode=mode,
                conversation_id=chat_id if not is_temporary else None,
                user_token=user_token,
                knowledge_bases=knowledge_bases
            )

            if conversation_id:
                # 缓存对话ID
                self._conversation_cache[cache_key] = conversation_id
                if self.valves.DEBUG_MODE:
                    print(f"创建新对话ID: {conversation_id}")

            return conversation_id

        except Exception as e:
            return None

    def _create_new_conversation(
        self,
        user_id: str,
        mode: str,
        conversation_id: str = None,
        user_token: str = None,
        knowledge_bases: List[Dict[str, str]] = None
    ) -> Optional[str]:
        """
        创建新对话会话

        Args:
            user_id: 用户ID
            mode: 执行模式
            conversation_id: 可选的对话ID，如果提供则作为请求参数传递
            user_token: 用户认证token

        Returns:
            对话ID，失败时返回None
        """
        try:
            # 构建请求数据
            request_data = {
                "user_id": user_id,
                "mode": mode,
                "knowledge_bases": knowledge_bases if knowledge_bases else self._parsed_knowledge_bases
            }
            
            # 如果提供了conversation_id，添加到请求数据中
            if conversation_id:
                request_data["conversation_id"] = conversation_id

            # 添加知识库API URL
            request_data["knowledge_api_url"] = self.valves.KNOWLEDGE_API_URL

            # 构建请求头
            headers = {'Content-Type': 'application/json'}
            if user_token:
                headers['Authorization'] = f'Bearer {user_token}'

            # 发送POST请求创建对话
            response = requests.post(
                self.create_conversation_url,
                json=request_data,
                headers=headers,
                timeout=self.valves.REQUEST_TIMEOUT
            )

            response.raise_for_status()

            # 解析响应
            result = response.json()
            if result.get("success") and result.get("data"):
                return result["data"].get("conversation_id")

            return None

        except Exception as e:
            return None

    def _send_message_and_stream(
        self,
        conversation_id: str,
        user_message: str,
        messages: List[dict],
        user_id: str,
        mode: str = None,
        user_token: str = None,
        knowledge_bases: List[Dict[str, str]] = None,
        __event_emitter__=None
    ) -> Generator[str, None, None]:
        """
        发送消息并处理流式响应

        Args:
            conversation_id: 对话ID
            user_message: 用户消息
            messages: 历史对话消息列表
            user_id: 用户ID
            mode: 执行模式
            user_token: 用户认证token
            __event_emitter__: 事件发射器

        Yields:
            流式响应内容
        """
        try:
            # 发送消息状态
            yield from self._emit_status(
                __event_emitter__,
                STATUS_MESSAGES["sending_message"]
            )

            # 构建请求数据
            request_data = {
                "conversation_id": conversation_id,
                "message": user_message,
                "messages": messages,  # 添加历史对话信息
                "user_id": user_id
            }
            
            # 添加mode参数（如果提供）
            if mode:
                request_data["mode"] = mode
            
            # 添加知识库配置
            request_data["knowledge_bases"] = knowledge_bases if knowledge_bases else self._parsed_knowledge_bases
            
            # 添加知识库API URL
            request_data["knowledge_api_url"] = self.valves.KNOWLEDGE_API_URL
            
            # 添加metadata以改善处理
            request_data["metadata"] = {
                "stream": True,
                "temperature": 0.7,
                "max_tokens": 2000
            }

            # 构建请求头
            headers = DEFAULT_HEADERS.copy()
            if user_token:
                headers['Authorization'] = f'Bearer {user_token}'

            # 构建流式聊天URL
            stream_url = self.stream_chat_url.format(conversation_id)


            # 发送流式请求
            response = requests.post(
                stream_url,
                json=request_data,
                headers=headers,
                stream=True,
                timeout=self.valves.REQUEST_TIMEOUT
            )

            response.raise_for_status()

            # 发送处理状态
            yield from self._emit_status(
                __event_emitter__,
                STATUS_MESSAGES["streaming"]
            )

            # 处理流式响应
            content_received = False
            for content in self._process_stream_lines(response, __event_emitter__):
                if content and content.strip():
                    content_received = True
                yield content
            
            # 如果没有收到任何内容，提供反馈
            if not content_received:
                yield from self._emit_status(
                    __event_emitter__,
                    "后端没有返回内容，可能是处理失败或配置问题"
                )
                yield "\n⚠️ 后端只返回了状态信息，没有生成回答内容。\n可能的原因：\n1. 后端服务配置问题\n2. 模型或知识库未正确加载\n3. 问题类型不在处理范围内\n\n请检查后端服务状态或联系管理员。\n"

        except requests.exceptions.RequestException as e:
            error_msg = f"请求错误: {str(e)}"
            yield from self._create_error_response(error_msg)

        except Exception as e:
            error_msg = f"发送消息失败: {str(e)}"
            yield from self._create_error_response(error_msg)

    def _process_stream_lines(
        self,
        response: requests.Response,
        __event_emitter__=None
    ) -> Generator[str, None, None]:
        """
        处理流式响应行

        Args:
            response: HTTP响应对象
            __event_emitter__: 事件发射器

        Yields:
            处理后的响应内容
        """
        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.strip():
                    continue

                # 处理SSE格式的数据
                if line.startswith("data: "):
                    data_content = line[6:].strip()

                    # 检查结束标记
                    if data_content == "[DONE]":
                        yield from self._emit_status(
                            __event_emitter__,
                            STATUS_MESSAGES["completed"]
                        )
                        break

                    # 解析JSON数据
                    try:
                        data = json.loads(data_content)
                        yield from self._handle_stream_data(data, __event_emitter__)
                    except json.JSONDecodeError:
                        continue
                        
                # 处理非SSE格式的直接内容（兼容性处理）
                elif line.strip() and not line.startswith("event:") and not line.startswith("id:"):
                    try:
                        data = json.loads(line.strip())
                        yield from self._handle_stream_data(data, __event_emitter__)
                    except json.JSONDecodeError:
                        # 如果不是JSON，可能是纯文本内容，直接输出
                        yield line.strip()

        except Exception as e:
            error_msg = f"处理流式数据失败: {str(e)}"
            yield from self._create_error_response(error_msg)

    def _handle_stream_data(
        self,
        data: Dict[str, Any],
        __event_emitter__=None
    ) -> Generator[str, None, None]:
        """
        处理流式数据

        Args:
            data: 流式数据
            __event_emitter__: 事件发射器

        Yields:
            处理后的内容
        """
        try:
            data_type = data.get("type", "")

            if data_type == CONTENT_TYPE:
                # 内容响应 - 直接输出内容
                content = data.get("content", "")
                if content:
                    yield content

            elif data_type == STATUS_TYPE:
                # 状态响应 - 发送状态事件
                description = data.get("description", "")
                stage = data.get("stage", "")

                # 修复编码问题并处理状态信息
                decoded_description = self._fix_encoding(description) if description else ""
                decoded_stage = self._fix_encoding(stage) if stage else ""
                
                if decoded_description:
                    yield from self._emit_status(__event_emitter__, decoded_description)
                elif decoded_stage:
                    yield from self._emit_status(__event_emitter__, f"当前阶段: {decoded_stage}")

            elif data_type == PROGRESS_TYPE:
                # 进度响应 - 发送进度事件
                progress = data.get("progress", 0)
                stage = data.get("stage", "")

                progress_msg = f"进度: {int(progress * 100)}%"
                if stage:
                    decoded_stage = self._fix_encoding(stage)
                    progress_msg += f" - {decoded_stage}"

                yield from self._emit_status(__event_emitter__, progress_msg)

            elif data_type == ERROR_TYPE:
                # 错误响应 - 输出错误信息
                error_msg = data.get("error", "未知错误")
                yield from self._create_error_response(error_msg)

            else:
                # 其他类型 - 尝试作为内容处理
                pass
                
                # 尝试查找可能的内容字段
                possible_content_fields = ["content", "message", "text", "response", "answer"]
                for field in possible_content_fields:
                    if field in data and data[field]:
                        yield str(data[field])
                        break

        except Exception as e:
            # 如果处理失败，尝试输出原始数据
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, str) and len(value) > 10:  # 可能是内容
                        yield value
                        break

    def _emit_status(
        self,
        __event_emitter__,
        description: str,
        done: bool = False
    ) -> Generator[str, None, None]:
        """
        发送状态事件

        Args:
            __event_emitter__: 事件发射器
            description: 状态描述
            done: 是否完成

        Yields:
            空生成器（用于兼容）
        """
        if __event_emitter__:
            try:
                # 使用asyncio运行异步事件发射器
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                loop.run_until_complete(__event_emitter__({
                    "type": "status",
                    "data": {
                        "description": description,
                        "done": done,
                    },
                }))

                loop.close()

            except Exception as e:
                pass

        # 返回空生成器以保持一致性
        if False:  # 永远不会执行，但使函数成为生成器
            yield

    def _fix_encoding(self, text: str) -> str:
        """
        在Docker UTF-8环境中，直接返回原始文本
        
        Args:
            text: 原始文本
            
        Returns:
            原始文本（不进行编码修复）
        """
        if not isinstance(text, str):
            return str(text)
        
        # 在正确配置的Docker UTF-8环境中，直接返回原始文本
        return text

    def _create_error_response(self, error_msg: str) -> Generator[str, None, None]:
        """
        创建错误响应

        Args:
            error_msg: 错误消息

        Yields:
            错误响应内容
        """
        yield f"\n❌ 错误: {error_msg}\n"

    def _validate_knowledge_bases(self) -> None:
        """验证知识库配置格式"""
        try:
            knowledge_bases = json.loads(self.valves.KNOWLEDGE_BASES)
            
            if not isinstance(knowledge_bases, list):
                raise ValueError("知识库配置必须是数组格式")
            
            for kb in knowledge_bases:
                if not isinstance(kb, dict) or 'name' not in kb or 'description' not in kb:
                    raise ValueError("知识库配置项必须包含name和description字段")
                    
            # 存储解析后的知识库配置
            self._parsed_knowledge_bases = knowledge_bases
                
        except (json.JSONDecodeError, ValueError) as e:
            # 使用默认配置
            self._parsed_knowledge_bases = [{"name": "test", "description": "默认知识库"}]

