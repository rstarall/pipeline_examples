#!/usr/bin/env python3
"""
LLM使用示例 - 集成PubChemPy MCP服务

这个示例展示如何在LLM对话中集成MCP化学搜索工具，
通过提示词指导LLM何时调用MCP服务来获取化学信息。
"""

import asyncio
import json
import logging
import os
import sys
import subprocess
from typing import List, Dict, Any, Optional
import httpx

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MCPChemicalTool:
    """远程化学搜索工具包装器"""
    
    def __init__(self, server_url: str = "http://localhost:8989"):
        self.server_url = server_url.rstrip('/')
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def start_mcp_server(self):
        """检查远程服务器连接"""
        try:
            # 测试服务器连接
            response = await self.client.get(f"{self.server_url}/health")
            if response.status_code == 200:
                logger.info(f"成功连接到远程服务器: {self.server_url}")
                return True
            else:
                logger.error(f"服务器连接失败: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"无法连接到远程服务器 {self.server_url}: {e}")
            return False
    
    async def search_chemical(self, query: str, search_type: str = "formula", use_fallback: bool = False) -> str:
        """搜索化学物质"""
        try:
            # 构建请求数据
            payload = {
                "query": query,
                "search_type": search_type,
                "use_fallback": use_fallback
            }
            
            # 发送HTTP请求
            response = await self.client.post(
                f"{self.server_url}/search",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get("success") and result.get("results"):
                    # 格式化搜索结果
                    response_text = f"🧪 化学搜索结果\n"
                    response_text += f"查询: {result['query']}\n"
                    response_text += f"搜索类型: {result['search_type']}\n"
                    response_text += f"数据源: {result.get('source', 'unknown')}\n"
                    response_text += f"找到 {len(result['results'])} 个化合物\n\n"
                    
                    for i, compound in enumerate(result['results'], 1):
                        response_text += f"--- 化合物 {i} ---\n"
                        
                        if compound.get('cid'):
                            response_text += f"PubChem CID: {compound['cid']}\n"
                        if compound.get('iupac_name'):
                            response_text += f"IUPAC名称: {compound['iupac_name']}\n"
                        if compound.get('molecular_formula'):
                            response_text += f"分子式: {compound['molecular_formula']}\n"
                        if compound.get('molecular_weight'):
                            response_text += f"分子量: {compound['molecular_weight']:.2f} g/mol\n"
                        if compound.get('smiles'):
                            response_text += f"SMILES: {compound['smiles']}\n"
                        if compound.get('inchi_key'):
                            response_text += f"InChI Key: {compound['inchi_key']}\n"
                        
                        if compound.get('synonyms'):
                            synonyms_text = ", ".join(compound['synonyms'][:5])
                            if len(compound['synonyms']) > 5:
                                synonyms_text += f" (还有 {len(compound['synonyms']) - 5} 个)"
                            response_text += f"同义词: {synonyms_text}\n"
                        
                        if compound.get('properties'):
                            response_text += "化学性质:\n"
                            for key, value in compound['properties'].items():
                                if value is not None:
                                    key_formatted = key.replace('_', ' ').title()
                                    response_text += f"  {key_formatted}: {value}\n"
                        
                        response_text += "\n"
                    
                    return response_text.strip()
                
                elif result.get("error"):
                    return f"搜索失败: {result['error']}"
                else:
                    return "未找到匹配的化学物质"
            
            else:
                return f"服务器错误: HTTP {response.status_code}"
                
        except Exception as e:
            logger.error(f"化学搜索请求失败: {e}")
            return f"搜索失败: {str(e)}"
    
    async def cleanup(self):
        """清理资源"""
        await self.client.aclose()
        logger.info("HTTP客户端已关闭")

class OpenAIClient:
    """OpenAI API客户端"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.client = httpx.AsyncClient(timeout=60.0)
        
        if not self.api_key:
            logger.warning("未设置OPENAI_API_KEY，将使用模拟响应")
    
    async def chat_completion(self, messages: List[Dict[str, str]], model: str = "gpt-3.5-turbo") -> str:
        """调用OpenAI Chat API"""
        if not self.api_key:
            # 模拟响应，用于演示
            return await self._mock_response(messages)
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 1000
            }
            
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=data
            )
            
            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"]
            else:
                logger.error(f"OpenAI API调用失败: {response.status_code} {response.text}")
                return "抱歉，AI服务暂时不可用。"
                
        except Exception as e:
            logger.error(f"OpenAI API调用异常: {e}")
            return "抱歉，AI服务出现错误。"
    
    async def _mock_response(self, messages: List[Dict[str, str]]) -> str:
        """模拟AI响应（当没有API密钥时使用）"""
        user_message = messages[-1]["content"].lower() if messages else ""
        
        # 模拟智能转换和工具调用（优先使用英文名称）
        chemical_mappings = {
            "咖啡因": ("caffeine", "name"),
            "水": ("water", "name"),
            "乙醇": ("ethanol", "name"),
            "阿司匹林": ("aspirin", "name"),
            "葡萄糖": ("glucose", "name"),
            "苯": ("benzene", "name"),
            "甲烷": ("methane", "name"),
            "二氧化碳": ("carbon dioxide", "name"),
            "氨": ("ammonia", "name"),
            "维生素c": ("ascorbic acid", "name"),
            "维生素C": ("ascorbic acid", "name"),
            "盐酸": ("hydrochloric acid", "name"),
            "硫酸": ("sulfuric acid", "name"),
            "caffeine": ("caffeine", "name"),
            "aspirin": ("aspirin", "name"),
            "glucose": ("glucose", "name"),
            "water": ("water", "name"),
            "ethanol": ("ethanol", "name"),
            # 分子式和SMILES保持不变
            "h2o": ("H2O", "formula"),
            "co2": ("CO2", "formula"),
            "cco": ("CCO", "smiles"),
        }
        
        # 检查是否包含化学相关内容
        for keyword, (query, search_type) in chemical_mappings.items():
            if keyword in user_message:
                return f'TOOL_CALL:search_chemical:{{"query": "{query}", "search_type": "{search_type}"}}'
        
        # 检查是否是分子式模式
        import re
        # 简单的分子式检测 (如 C6H6, H2O, CO2 等)
        formula_pattern = r'\b[A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*)*\b'
        formulas = re.findall(formula_pattern, user_message.upper())
        for formula in formulas:
            if len(formula) >= 2 and any(char.isdigit() for char in formula):
                return f'TOOL_CALL:search_chemical:{{"query": "{formula}", "search_type": "formula"}}'
        
        # 检查是否包含化学相关关键词
        chemical_keywords = [
            "化学", "分子", "化合物", "元素", "化学式", "smiles", "分子式", 
            "结构", "性质", "分子量", "化学名"
        ]
        
        if any(keyword in user_message for keyword in chemical_keywords):
            return "请告诉我具体的化学物质名称，我可以帮您查询详细信息。比如您可以说：'咖啡因的分子式是什么'或'H2O是什么化合物'。"
        else:
            return "我是一个化学信息助手。如果您需要查询化学物质信息，请告诉我具体的化学名称（中文或英文）、分子式或SMILES字符串。"
    
    async def cleanup(self):
        """清理资源"""
        await self.client.aclose()

class ChemicalChatBot:
    """化学信息聊天机器人"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, mcp_server_url: Optional[str] = None):
        self.openai_client = OpenAIClient(api_key, base_url)
        self.mcp_tool = MCPChemicalTool(mcp_server_url or "http://localhost:8989")
        self.conversation_history = []
        
        # 系统提示词 - 指导AI何时调用MCP工具
        self.system_prompt = """你是一个专业的化学信息助手。你可以帮助用户查询化学物质的详细信息。

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

如果不需要搜索化学信息，请正常回答用户的问题。"""
    
    async def start(self):
        """启动聊天机器人"""
        # 检查远程MCP服务器连接
        if not await self.mcp_tool.start_mcp_server():
            logger.error("无法连接到远程MCP服务器，将无法搜索化学信息")
        
        # 初始化对话历史
        self.conversation_history = [
            {"role": "system", "content": self.system_prompt}
        ]
    
    async def process_message(self, user_input: str) -> str:
        """处理用户消息"""
        # 添加用户消息到历史
        self.conversation_history.append({"role": "user", "content": user_input})
        
        # 获取AI响应
        ai_response = await self.openai_client.chat_completion(self.conversation_history)
        
        # 检查是否需要调用工具
        if ai_response.startswith("TOOL_CALL:search_chemical:"):
            tool_args_str = ai_response.replace("TOOL_CALL:search_chemical:", "")
            try:
                tool_args = json.loads(tool_args_str)
                
                # 调用MCP工具
                tool_result = await self.mcp_tool.search_chemical(
                    query=tool_args.get("query", ""),
                    search_type=tool_args.get("search_type", "formula"),
                    use_fallback=tool_args.get("use_fallback", False)
                )
                
                # 将工具结果添加到对话历史
                tool_context = f"[化学搜索结果]\n{tool_result}\n\n请基于以上搜索结果回答用户的问题。"
                self.conversation_history.append({"role": "system", "content": tool_context})
                
                # 重新获取AI响应
                final_response = await self.openai_client.chat_completion(self.conversation_history)
                self.conversation_history.append({"role": "assistant", "content": final_response})
                
                return final_response
                
            except json.JSONDecodeError:
                error_msg = "工具调用格式错误，无法解析参数"
                self.conversation_history.append({"role": "assistant", "content": error_msg})
                return error_msg
        else:
            # 普通对话响应
            self.conversation_history.append({"role": "assistant", "content": ai_response})
            return ai_response
    
    async def cleanup(self):
        """清理资源"""
        await self.openai_client.cleanup()
        await self.mcp_tool.cleanup()

async def interactive_chat():
    """交互式聊天主函数"""
    print("🧪 化学信息聊天机器人")
    print("=" * 50)
    print("这是一个集成了远程化学搜索服务的智能化学助手")
    print("你可以询问化学物质的信息，如分子式、性质、结构等")
    print("输入 'quit' 或 'exit' 退出程序")
    print("=" * 50)
    
    # 检查环境变量
    api_key = os.getenv("OPENAI_API_KEY")
    mcp_server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8989")
    
    if not api_key:
        print("⚠️  未检测到OPENAI_API_KEY环境变量")
        print("   将使用模拟模式演示功能")
        print("   设置环境变量以使用真实AI：")
        print("   export OPENAI_API_KEY='your-api-key'")
        print()
    
    print(f"🌐 远程服务器地址: {mcp_server_url}")
    print()
    
    # 初始化聊天机器人
    chatbot = ChemicalChatBot(api_key, mcp_server_url=mcp_server_url)
    
    try:
        await chatbot.start()
        
        print("✅ 聊天机器人已启动，请开始对话：\n")
        
        while True:
            # 获取用户输入
            try:
                user_input = input("用户: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n\n👋 再见！")
                break
            
            if user_input.lower() in ['quit', 'exit', '退出']:
                print("👋 再见！")
                break
            
            if not user_input:
                continue
            
            # 处理用户消息
            print("AI: 正在思考...", end="", flush=True)
            try:
                response = await chatbot.process_message(user_input)
                print(f"\rAI: {response}\n")
            except Exception as e:
                print(f"\r❌ 处理消息时出错: {e}\n")
    
    finally:
        # 清理资源
        await chatbot.cleanup()

async def demo_conversations():
    """演示对话示例"""
    print("🧪 化学信息聊天机器人 - 演示模式")
    print("=" * 50)
    
    # 演示对话 - 展示3种搜索类型
    demo_cases = [
        {
            "user": "咖啡因的分子式是什么？",
            "description": "中文名转英文名搜索 (name)"
        },
        {
            "user": "H2O是什么化合物？",
            "description": "分子式搜索 (formula)"
        },
        {
            "user": "CCO代表什么化学物质？",
            "description": "SMILES字符串搜索 (smiles)"
        },
        {
            "user": "aspirin有什么作用？",
            "description": "英文名称搜索 (name)"
        },
        {
            "user": "今天天气怎么样？",
            "description": "非化学相关问题"
        }
    ]
    
    mcp_server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8989")
    chatbot = ChemicalChatBot(mcp_server_url=mcp_server_url)
    
    try:
        await chatbot.start()
        
        for i, case in enumerate(demo_cases, 1):
            print(f"\n--- 演示 {i}: {case['description']} ---")
            print(f"用户: {case['user']}")
            
            response = await chatbot.process_message(case['user'])
            print(f"AI: {response}")
            
            # 小延迟，模拟真实对话
            await asyncio.sleep(1)
    
    finally:
        await chatbot.cleanup()

def main():
    """主函数"""
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        # 演示模式
        asyncio.run(demo_conversations())
    else:
        # 交互模式
        asyncio.run(interactive_chat())

if __name__ == "__main__":
    main()
