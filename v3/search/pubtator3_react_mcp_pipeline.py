"""
使用ReAct模式，实现深度思考planning，并进行多轮pubtator3 MCP工具调用，最终给出回答。
1.Reasoning阶段，根据用户问题、历史会话、当前获取到的论文信息进行自主思考判断
  - 制定初次工具调用的Action, 调用pubtator3工具，获取论文信息
2.Action阶段，调用MCP工具，获取信息
3.Observation阶段(每次Action后都需要进行观察)
  - 根据Action的执行结果，判断是否足够回答用户的问题(问题的相关性，进一步探索的必要性)
  - 如果信息不充分，则制定新的Action(更新查询语句、使用前一步检索到的信息更新查询语句)，调用pubtator3工具，获取论文信息
  - 如果信息充分，则跳转答案生成阶段
4.答案生成阶段，根据用户问题、历史会话、当前获取到的信息，生成最终答案，并返回给用户
5.除了答案生成阶段，每个阶段使用_emit_processing方法，返回处理过程内容和思考，减少debug描述内容的输出
6.对于Action和Observation阶段，_emit_processing采用动态递进的processing_stage
"""