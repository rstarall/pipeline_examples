"""
编写基于serper API的联网搜索pipeline,意图识别json返回
1.定义并识别网站类型
  wiki:url匹配wikipedia
  百度百科:url匹配baike.baidu
  MBA智库百科:wiki.mbalib
  论文:url匹配arxiv,doi,pdf
  其他:url匹配其他
2.阶段1:
    - 根据用户历史问题和当前问题输出优化后的问题(json格式，中英版本):
    {
    "optimized_question_cn": "优化后的问题",
    "optimized_question_en": "优化后的问题(英文)",
    }
    - process展示优化后的问题
3.阶段2:
  - 根据优化后的问题进行联网搜索,中文英文各10个结果
  - 根据结果url识别网站类型(识别不了则为其他),处理为json格式
  - 将20个结果的json输入LLM，让LLM根据问题和结果选择最恰当的10(可配置)个网页地址
  - process展示信息源
4.阶段4:
   - 根据阶段3的10个网页地址进行联网内容获取(协程并发)，获取到的是html
   - LLM进行内容解析，输出json格式
   - process展示信息源
5.阶段5: 根据阶段4的内容和用户的问题进行最终的回答，答案要忠于信息源,内容丰富，准确

参考文件:
api参考:v2\search\test\serper_test.py
处理参考:v2\search\searxng_openai_pipeline.py
"""