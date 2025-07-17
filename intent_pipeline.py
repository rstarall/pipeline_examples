"""
编写pipelines\pipelines\intent_pipeline.py.py
1.一个基于意图识别的问答pipeline,支持选择模式(workflow和agent)
2.根据用户选择分别调用后端的workflow和agent接口(在Values中配置)
3.支持流式输出,支持多轮对话
4.需要向后端传入user参数
5.不要使用第三方库，直接使用后端接口，可参考examples\pipelines\integrations\langgraph_pipeline\langgraph_stream_pipeline.py
6.请预留必要的Values参数
7.注意解耦和封装，代码结构清晰，常量数据在前面定义
8.推荐使用的状态提醒接口:
 __event_emitter__=None, 
 __event_call__=None,
状态返回信息使用
if __event_emitter__:
    await __event_emitter__(
        {
            "type": "status",
            "data": {
                "description": f"{result.status.message}",
                "done": False,
            },
        }
    )
操作使用提醒:
# 请求用户确认
confirmation_result = await __event_call__(
    {
        "type": "confirmation",
        "data": {
            "title": "命令执行确认",
            "message": f"是否执行命令{result.status.command}？",
        },
    }
)

if not confirmation_result:
    yield "用户取消了操作。"
    return

"""