#!/usr/bin/env python3
"""
直接测试Pipeline中的_query_lightrag_stream方法
"""

import sys
import os

# 添加父目录到路径以便导入pipeline
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from cot_lightrag_stream_pipeline import Pipeline
except ImportError:
    print("❌ 无法导入Pipeline类，请检查文件路径")
    sys.exit(1)

import json
import time
from datetime import datetime


def test_pipeline_stream_method():
    """测试Pipeline中的_query_lightrag_stream方法"""
    
    print("🧪 直接测试Pipeline的_query_lightrag_stream方法")
    print("=" * 60)
    
    # 创建Pipeline实例
    try:
        pipeline = Pipeline()
        print("✅ Pipeline实例创建成功")
    except Exception as e:
        print(f"❌ 创建Pipeline实例失败: {e}")
        return False
    
    # 测试查询
    test_query = "什么是人工智能？"
    test_mode = "hybrid"
    test_stage = "stage1_retrieval"
    
    print(f"📝 测试查询: {test_query}")
    print(f"🔧 查询模式: {test_mode}")
    print(f"📋 处理阶段: {test_stage}")
    print("-" * 40)
    
    start_time = time.time()
    total_content = ""
    stream_count = 0
    final_result = None
    
    try:
        print("📨 开始接收流式数据:")
        
        for stream_data in pipeline._query_lightrag_stream(test_query, test_mode, test_stage):
            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            
            if stream_data.startswith("data: "):
                # 流式数据
                stream_count += 1
                print(f"[{timestamp}] 📦 流式数据块 #{stream_count}")
                
                # 解析流式数据内容
                try:
                    data_content = stream_data[6:].strip()  # 去掉"data: "前缀
                    if data_content.endswith("\n\n"):
                        data_content = data_content[:-2]
                    
                    chunk_data = json.loads(data_content)
                    if "choices" in chunk_data:
                        delta = chunk_data["choices"][0].get("delta", {})
                        processing_content = delta.get("processing_content", "")
                        processing_title = delta.get("processing_title", "")
                        processing_stage = delta.get("processing_stage", "")
                        
                        print(f"   📄 标题: {processing_title}")
                        print(f"   🏷️  阶段: {processing_stage}")
                        print(f"   📝 内容: {processing_content[:100]}{'...' if len(processing_content) > 100 else ''}")
                        
                        total_content += processing_content
                        
                except json.JSONDecodeError as e:
                    print(f"   ⚠️ 解析流式数据失败: {e}")
                    print(f"   📄 原始数据: {stream_data[:200]}...")
                    
                print("-" * 40)
                    
            else:
                # 最终结果
                try:
                    final_data = json.loads(stream_data)
                    print(f"[{timestamp}] 🎯 最终结果:")
                    
                    if "response" in final_data:
                        final_result = final_data["response"]
                        print(f"   ✅ 成功: {len(final_result)} 字符")
                        print(f"   📄 内容预览: {final_result[:200]}{'...' if len(final_result) > 200 else ''}")
                    elif "error" in final_data:
                        final_result = final_data["error"]
                        print(f"   ❌ 错误: {final_result}")
                        
                except json.JSONDecodeError as e:
                    print(f"   ⚠️ 解析最终结果失败: {e}")
                    print(f"   📄 原始数据: {stream_data}")
        
        end_time = time.time()
        duration = end_time - start_time
        
        print("=" * 60)
        print("📊 测试完成统计:")
        print(f"   ⏱️  总耗时: {duration:.2f} 秒")
        print(f"   📦 流式数据块数: {stream_count}")
        print(f"   📝 流式内容总长度: {len(total_content)} 字符")
        print(f"   🎯 最终结果长度: {len(str(final_result)) if final_result else 0} 字符")
        
        # 内容对比
        if final_result and isinstance(final_result, str):
            if total_content.strip() == final_result.strip():
                print("   ✅ 流式内容与最终结果一致")
            else:
                print("   ⚠️ 流式内容与最终结果不一致")
                print(f"      流式长度: {len(total_content)}")
                print(f"      最终长度: {len(final_result)}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试执行失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""
    print("🚀 Pipeline流式方法测试工具")
    print(f"⏰ 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    success = test_pipeline_stream_method()
    
    if success:
        print("\n🎉 测试成功！Pipeline的_query_lightrag_stream方法工作正常")
    else:
        print("\n❌ 测试失败！请检查Pipeline配置和LightRAG服务状态")
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main() 