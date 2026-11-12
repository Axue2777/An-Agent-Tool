from openai.types.chat import ChatCompletionMessage
from openai import RateLimitError
from time import sleep


# 接收一轮模型流：实时发送正文，并拼出可继续处理的完整消息。
def request_stream_message(client, messages, tools, tool_choice, on_event=None,
                           *, model="deepseek-flash", provider="deepseek", thinking=False):
    text_parts = []
    reasoning_parts = []
    calls = {}
    finish_reason = None

    # 新一轮可能是继续使用工具，也可能开始生成最终回答。
    if on_event:
        on_event({"type": "round_start"})

    # 使用上下文管理器，正常结束或异常时都关闭上游连接。
    options = dict(model=model, messages=messages, tools=tools,
                   tool_choice=tool_choice, stream=True)
    # DeepSeek-only parameter: other compatible APIs may reject it.
    if provider == "deepseek":
        options["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}
    # 智谱 1305 是临时繁忙时，仅在尚未开始接收任何内容前补试一次。
    # 其他 429 可能是额度限制，不能反复请求。
    for attempt in range(2):
        try:
            upstream = client.chat.completions.create(**options)
            break
        except RateLimitError as error:
            body = getattr(error, "body", None)
            issue = body.get("error", body) if isinstance(body, dict) else {}
            code = issue.get("code") if isinstance(issue, dict) else None
            if provider != "zhipu" or str(code) != "1305" or attempt:
                raise
            sleep(1.5)
    with upstream as stream:
        for chunk in stream:
            # 每收到一个数据块就检查取消，包括只有工具参数的数据块。
            if on_event:
                on_event({"type": "checkpoint"})
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if choice.finish_reason:
                finish_reason = choice.finish_reason

            # 文字先用于实时展示，同时保留完整副本供日志和历史使用。
            if delta.content:
                text_parts.append(delta.content)
                if on_event:
                    on_event({"type": "text_delta", "text": delta.content})
            # DeepSeek 将思考过程与正文分开发送，供页面独立折叠显示。
            reasoning_delta = getattr(delta, "reasoning_content", None)
            if reasoning_delta:
                reasoning_parts.append(reasoning_delta)
                if on_event:
                    on_event({"type": "reasoning_delta", "text": reasoning_delta})

            # 一轮可能同时提出多个工具请求，按 index 分别拼接。
            for part in delta.tool_calls or []:
                call = calls.setdefault(part.index, {
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                })
                if part.id:
                    call["id"] = part.id
                if part.function:
                    call["function"]["name"] += part.function.name or ""
                    call["function"]["arguments"] += part.function.arguments or ""

    # 被截断或连接提前结束时，不能把不完整消息当成成功结果。
    if finish_reason not in {"stop", "tool_calls"}:
        raise RuntimeError(f"模型未正常结束，结束原因：{finish_reason}")

    # 恢复为原有 Agent 循环使用的消息对象，避免改动工具执行逻辑。
    return ChatCompletionMessage.model_validate({
        "role": "assistant", "content": "".join(text_parts) or None,
        "reasoning_content": "".join(reasoning_parts) or None,
        "tool_calls": [calls[index] for index in sorted(calls)] or None,
    })
