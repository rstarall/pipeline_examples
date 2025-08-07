#!/usr/bin/env python3
"""
完整的Pipeline功能测试
"""

import os
import sys
import asyncio
import traceback

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_full_pipeline():
    """测试完整的pipeline功能"""
    print("🚀 测试完整Pipeline功能\n")
    
    # 设置环境变量
    os.environ["OPENAI_API_KEY"] = "test_key"
    os.environ["LIGHTRAG_BASE_URL"] = "http://localhost:9621"
    os.environ["ENABLE_STREAMING"] = "false"  # 关闭流式模式以便测试
    
    try:
        from v3.cot.lightrag_react_pipeline import Pipeline
        
        # 初始化pipeline
        pipeline = Pipeline()
        
        # 准备测试数据
        user_message = "什么是人工智能？"
        model_id = "gpt-4"
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮助您的吗？"},
            {"role": "user", "content": user_message}
        ]
        body = {}
        
        print(f"📝 测试消息: {user_message}")
        print("🔄 开始执行pipeline...")
        
        # 执行pipeline
        results = []
        try:
            for i, result in enumerate(pipeline.pipe(user_message, model_id, messages, body)):
                print(f"  结果 {i+1}: {str(result)[:100]}...")
                results.append(result)
                
                # 限制结果数量以避免无限循环
                if i >= 10:
                    print("  (限制输出，停止获取更多结果)")
                    break
                    
        except Exception as e:
            print(f"❌ Pipeline执行出错: {e}")
            traceback.print_exc()
            return
        
        print(f"\n✅ Pipeline执行完成，共获得 {len(results)} 个结果")
        
        # 分析结果
        if results:
            print("\n📊 结果分析:")
            for i, result in enumerate(results[:3]):  # 只显示前3个结果
                print(f"  结果 {i+1}: {type(result)} - {str(result)[:200]}...")
        else:
            print("⚠️ 没有获得任何结果")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        traceback.print_exc()

def test_streaming_mode():
    """测试流式模式"""
    print("\n🌊 测试流式模式\n")
    
    # 设置流式模式
    os.environ["ENABLE_STREAMING"] = "true"
    
    try:
        from v3.cot.lightrag_react_pipeline import Pipeline
        
        pipeline = Pipeline()
        
        user_message = "请介绍一下机器学习"
        messages = [{"role": "user", "content": user_message}]
        body = {}
        
        print(f"📝 流式测试消息: {user_message}")
        print("🔄 开始流式执行...")
        
        stream_results = []
        try:
            for i, result in enumerate(pipeline.pipe(user_message, "gpt-4", messages, body)):
                if isinstance(result, str) and result.startswith("data: "):
                    print(f"  流式数据 {i+1}: {result[:80]}...")
                else:
                    print(f"  其他结果 {i+1}: {str(result)[:80]}...")
                
                stream_results.append(result)
                
                # 限制结果数量
                if i >= 15:
                    print("  (限制流式输出)")
                    break
                    
        except Exception as e:
            print(f"❌ 流式执行出错: {e}")
            traceback.print_exc()
            return
        
        print(f"\n✅ 流式执行完成，共获得 {len(stream_results)} 个结果")
        
    except Exception as e:
        print(f"❌ 流式测试失败: {e}")
        traceback.print_exc()

def test_error_handling():
    """测试错误处理"""
    print("\n🚨 测试错误处理\n")
    
    try:
        from v3.cot.lightrag_react_pipeline import Pipeline
        
        pipeline = Pipeline()
        
        # 测试空消息
        print("测试空消息...")
        empty_results = list(pipeline.pipe("", "gpt-4", [], {}))
        print(f"  空消息结果: {empty_results}")
        
        # 测试无效消息
        print("测试空白消息...")
        blank_results = list(pipeline.pipe("   ", "gpt-4", [], {}))
        print(f"  空白消息结果: {blank_results}")
        
        print("✅ 错误处理测试完成")
        
    except Exception as e:
        print(f"❌ 错误处理测试失败: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    print("🧪 开始完整Pipeline测试\n")
    
    # 基本功能测试
    test_full_pipeline()
    
    # 流式模式测试
    test_streaming_mode()
    
    # 错误处理测试
    test_error_handling()
    
    print("\n🎉 所有测试完成！")