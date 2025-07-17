from typing import AsyncGenerator, List, Dict
import asyncio
import json
import aiohttp
from pydantic import BaseModel


class Pipe:
    class Valves(BaseModel):
        # OpenAI配置
        OPENAI_API_BASE_URL: str = "https://openrouter.ai/api/v1"
        OPENAI_API_KEY: str = (
            "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"
        )
        OPENAI_MODEL: str = "gpt-4o"

        # 功能配置
        enable_confirmation: bool = True
        confirmation_threshold: int = 3  # 对话轮数阈值
        max_conversation_turns: int = 5

    def __init__(self):
        self.valves = self.Valves()
        self.conversation_count = 0  # 对话计数器

    async def pipe(
        self, body: dict, __event_emitter__=None, __event_call__=None, __user__=None
    ) -> AsyncGenerator:
        """
        带有OpenAI配置和多步聊天确认的pipe函数
        """

        try:
            # 增加对话计数
            self.conversation_count += 1

            # 发送开始状态
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "description": f"开始第{self.conversation_count}轮对话...",
                            "done": False,
                        },
                    }
                )

            # 检查是否需要用户确认
            if (
                self.valves.enable_confirmation
                and self.conversation_count >= self.valves.confirmation_threshold
                and __event_call__
            ):

                # 请求用户确认
                confirmation_result = await __event_call__(
                    {
                        "type": "confirmation",
                        "data": {
                            "title": "继续对话确认",
                            "message": f"这是第{self.conversation_count}轮对话，是否继续？",
                        },
                    }
                )

                if not confirmation_result:
                    yield "用户取消了对话。"
                    return

            # 检查OpenAI配置
            if not self.valves.OPENAI_API_KEY:
                yield "错误：请在Valves中配置OPENAI_API_KEY"
                return

            # 准备OpenAI请求
            messages = body.get("messages", [])

            headers = {
                "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": self.valves.OPENAI_MODEL,
                "messages": messages,
                "stream": True,
                "temperature": 0.7,
            }

            # 发送请求状态
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "description": f"正在请求{self.valves.OPENAI_MODEL}...",
                            "done": False,
                        },
                    }
                )

            # 调用OpenAI API
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.valves.OPENAI_API_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:

                    if response.status != 200:
                        error_text = await response.text()
                        yield f"API调用失败 ({response.status}): {error_text}"
                        return

                    # 处理流式响应
                    async for line in response.content:
                        line = line.decode("utf-8").strip()

                        if line.startswith("data: "):
                            data_str = line[6:]  # 移除 "data: " 前缀

                            if data_str == "[DONE]":
                                break

                            try:
                                data = json.loads(data_str)
                                choices = data.get("choices", [])

                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content", "")

                                    if content:
                                        yield content

                            except json.JSONDecodeError:
                                continue

            # 发送完成状态
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "description": f"第{self.conversation_count}轮对话完成",
                            "done": True,
                        },
                    }
                )

        except Exception as e:
            # 发送错误状态
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "description": f"处理过程中出现错误: {str(e)}",
                            "done": True,
                        },
                    }
                )
            yield f"❌ 处理过程中出现错误: {str(e)}"
