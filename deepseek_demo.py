import os
import json
import httpx
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
    http_client=httpx.Client(trust_env=False, timeout=30.0),
    max_retries=0,
)

inventory = {"机械键盘": 12, "无线鼠标": 0, "显示器": 5}


def get_stock(product_name: str) -> dict:
    if product_name not in inventory:
        return {"product_name": product_name, "found": False}
    return {
        "product_name": product_name,
        "found": True,
        "stock": inventory[product_name],
    }


tools = [{
    "type": "function",
    "function": {
        "name": "get_stock",
        "description": "查询指定商品的库存。未找到商品表示库存未知。",
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "description": "商品名称，例如机械键盘、无线鼠标、显示器",
                },
            },
            "required": ["product_name"],
            "additionalProperties": False,
        },
    },
}]


def run_turn(messages):
    for step in range(5):
        response = client.chat.completions.create(
            model="deepseek-flash",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            extra_body={"thinking": {"type": "disabled"}},
        )
        message = response.choices[0].message
        messages.append(message)

        if not message.tool_calls:
            print("模型回答：", message.content)
            break

        for call in message.tool_calls:
            print("模型请求调用：", call.function.name, call.function.arguments)
            try:
                if call.function.name != "get_stock":
                    raise ValueError("不支持的工具")
                arguments = json.loads(call.function.arguments)
                if (
                    not isinstance(arguments, dict)
                    or set(arguments) != {"product_name"}
                    or not isinstance(arguments["product_name"], str)
                ):
                    raise ValueError("工具参数必须包含字符串 product_name")
                result = get_stock(**arguments)
            except (ValueError, TypeError) as error:
                result = {"error": str(error)}

            print("Python 执行结果：", result)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
    else:
        print("已达到本轮调用次数上限。请缩小问题范围。")


if __name__ == "__main__":
    messages = [
        {"role": "system", "content": (
            "你是商品助手。涉及库存的问题必须使用 get_stock 查询，不能猜测。"
            "结合对话理解用户的问题。商品名称不明确时先询问用户。"
            "商品包括机械键盘、无线鼠标、显示器；键盘指机械键盘，鼠标指无线鼠标。"
            "未找到商品时说明库存未知。"
        )},
    ]

    print("库存助手已启动，输入 exit 或 退出结束。")
    while True:
        question = input("你：").strip()
        if question.lower() in {"exit", "退出"}:
            print("对话已结束。")
            break
        if not question:
            continue

        messages.append({"role": "user", "content": question})
        run_turn(messages)
