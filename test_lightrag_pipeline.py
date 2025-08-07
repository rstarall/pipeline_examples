#!/usr/bin/env python3
"""
LightRAG Pipeline测试脚本
用于诊断语法和异步逻辑问题
"""

import os
import sys
import asyncio
import traceback
from typing import List, Dict, Any

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_import():
    """测试导入是否成功"""
    print("🔍 测试1: 导入测试")
    try:
        from v3.cot.lightrag_react_pipeline import Pipeline
        print("✅ 导入成功")
        return Pipeline
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        traceback.print_exc()
        return None

def test_initialization(Pipeline):
    """测试Pipeline初始化"""
    print("\n🔍 测试2: 初始化测试")
    try:
        pipeline = Pipeline()
        print("✅ 初始化成功")
        return pipeline
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        traceback.print_exc()
        return None

def test_basic_methods(pipeline):
    """测试基本方法"""
    print("\n🔍 测试3: 基本方法测试")
    
    # 测试同步方法
    try:
        # 测试_build_conversation_context
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        context = pipeline._build_conversation_context("Test message", messages)
        print(f"✅ _build_conversation_context: {context[:50]}...")
        
        # 测试_emit_processing
        processing_gen = pipeline._emit_processing("测试内容", "reasoning")
        chunk = next(processing_gen)
        print(f"✅ _emit_processing: {type(chunk)}")
        
        # 测试token统计
        pipeline._add_token_stats("input", "output")
        print(f"✅ _add_token_stats: {pipeline.token_stats}")
        
    except Exception as e:
        print(f"❌ 基本方法测试失败: {e}")
        traceback.print_exc()

async def test_async_methods(pipeline):
    """测试异步方法"""
    print("\n🔍 测试4: 异步方法测试")
    
    try:
        # 测试_reasoning_phase
        print("测试 _reasoning_phase...")
        messages = [{"role": "user", "content": "test"}]
        reasoning_gen = pipeline._reasoning_phase("测试问题", messages, False)
        
        result_count = 0
        async for result in reasoning_gen:
            result_type, content = result
            print(f"  - {result_type}: {str(content)[:100]}...")
            result_count += 1
            if result_count >= 3:  # 限制输出数量
                break
        
        print("✅ _reasoning_phase 测试完成")
        
    except Exception as e:
        print(f"❌ 异步方法测试失败: {e}")
        traceback.print_exc()

def test_pipe_method(pipeline):
    """测试pipe方法（当前被注释的状态）"""
    print("\n🔍 测试5: pipe方法测试")
    
    try:
        messages = [{"role": "user", "content": "测试消息"}]
        body = {}
        
        # 调用pipe方法
        result_gen = pipeline.pipe("测试问题", "gpt-4", messages, body)
        
        # 尝试获取结果
        results = list(result_gen)
        print(f"✅ pipe方法返回结果数量: {len(results)}")
        for i, result in enumerate(results[:3]):  # 只显示前3个结果
            print(f"  结果{i+1}: {str(result)[:100]}...")
            
    except Exception as e:
        print(f"❌ pipe方法测试失败: {e}")
        traceback.print_exc()

async def test_lightrag_connection(pipeline):
    """测试LightRAG连接（如果可用）"""
    print("\n🔍 测试6: LightRAG连接测试")
    
    try:
        # 测试_call_lightrag方法
        result = await pipeline._call_lightrag("test query", "mix")
        print(f"✅ LightRAG连接测试: {type(result)}")
        if isinstance(result, dict) and "error" in result:
            print(f"  预期的连接错误: {result['error']}")
        
    except Exception as e:
        print(f"❌ LightRAG连接测试失败: {e}")
        traceback.print_exc()

async def test_stream_method(pipeline):
    """测试流式方法"""
    print("\n🔍 测试7: 流式方法测试")
    
    try:
        # 测试_call_lightrag_stream
        stream_gen = pipeline._call_lightrag_stream("test query", "mix", "action")
        
        result_count = 0
        async for result in stream_gen:
            result_type, content = result
            print(f"  流式结果: {result_type} - {str(content)[:50]}...")
            result_count += 1
            if result_count >= 2:  # 限制输出数量
                break
                
        print("✅ 流式方法测试完成")
        
    except Exception as e:
        print(f"❌ 流式方法测试失败: {e}")
        traceback.print_exc()

def test_environment():
    """测试环境变量"""
    print("\n🔍 测试8: 环境变量测试")
    
    required_vars = [
        "OPENAI_API_KEY",
        "LIGHTRAG_BASE_URL", 
    ]
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: {'*' * min(len(value), 10)}...")
        else:
            print(f"⚠️ {var}: 未设置")

async def main():
    """主测试函数"""
    print("🚀 开始LightRAG Pipeline诊断测试\n")
    
    # 测试环境
    test_environment()
    
    # 测试导入
    Pipeline = test_import()
    if not Pipeline:
        return
    
    # 测试初始化
    pipeline = test_initialization(Pipeline)
    if not pipeline:
        return
    
    # 测试基本方法
    test_basic_methods(pipeline)
    
    # 测试异步方法
    await test_async_methods(pipeline)
    
    # 测试pipe方法
    test_pipe_method(pipeline)
    
    # 测试LightRAG连接
    await test_lightrag_connection(pipeline)
    
    # 测试流式方法
    await test_stream_method(pipeline)
    
    print("\n🎉 诊断测试完成！")

if __name__ == "__main__":
    # 设置一些基本的环境变量（如果未设置）
    if not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "test_key"
    if not os.getenv("LIGHTRAG_BASE_URL"):
        os.environ["LIGHTRAG_BASE_URL"] = "http://localhost:9621"
    
    # 运行测试
    asyncio.run(main())