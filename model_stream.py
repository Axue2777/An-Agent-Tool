from openai.types.chat import ChatCompletionMessage


# 接收一轮模型流：实时发送正文，并拼出可继续处理的完整消息。
def request_stream_message(client, messages, tools, tool_choice, on_event=None):
    text_parts = []
    calls = {}
    finish_reason = None

    # 新一轮可能是继续使用工具，也可能开始生成最终回答。
    if on_event:
        on_event({"type": "round_start"})

    # 使用上下文管理器，正常结束或异常时都关闭上游连接。
    with client.chat.completions.create(
        model="deepseek-flash",
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        stream=True,
        extra_body={"thinking": {"type": "disabled"}},
    ) as stream:
        for chunk in stream:
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
    return ChatCompletionMessage(
        role="assistant",
        content="".join(text_parts) or None,
        tool_calls=[calls[index] for index in sorted(calls)] or None,
    )