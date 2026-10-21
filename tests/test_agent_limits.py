import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from agent_tools import run_agent


def tool_call(number):
    # 为每个模拟调用提供不同编号。
    return SimpleNamespace(id=f"call_{number}", function=SimpleNamespace(
        name="get_stock",
        arguments=json.dumps({"product_name": "机械键盘"}),
    ))


class TestAgentToolLimit(unittest.TestCase):
    def run_case(self, batches, limit):
        # 每个 batch 表示模型某一轮提出的一批工具调用。
        responses = [
            SimpleNamespace(content="", tool_calls=batch)
            for batch in batches
        ]
        responses.append(SimpleNamespace(content="模拟总结", tool_calls=[]))
        # 临时替换配置、模型、工具和文件记录，退出后自动恢复。
        with (
            patch("agent_tools.MAX_TOOL_CALLS", limit),
            patch("agent_tools.request_stream_message",
                  side_effect=responses) as model,
            patch("agent_tools.execute_tool",
                  return_value={"stock": 12}) as tool,
            patch("agent_tools.append_record"),
        ):
            reply, steps = run_agent(None, [], None)
        return reply, steps, model, tool

    def test_limit_across_rounds(self):
        # 两轮各执行一个工具，第三轮必须禁用工具并总结。
        reply, steps, model, tool = self.run_case(
            [[tool_call(1)], [tool_call(2)]], limit=2,
        )
        self.assertEqual(tool.call_count, 2)
        self.assertEqual(len(steps), 2)
        self.assertEqual(reply, "模拟总结")
        self.assertEqual(
            [call.args[3] for call in model.call_args_list],
            ["auto", "auto", "none"],
        )

    def test_overflow_in_same_batch(self):
        # 同一批提出三个调用，上限为一时只能执行第一个。
        _, steps, model, tool = self.run_case(
            [[tool_call(1), tool_call(2), tool_call(3)]], limit=1,
        )
        self.assertEqual(tool.call_count, 1)
        self.assertEqual(len(steps), 3)
        for step in steps[1:]:
            self.assertEqual(step["result"]["code"], "tool_limit_reached")
            self.assertFalse(step["result"]["executed"])
        # 被拒绝的调用也必须返回对应结果，保持调用协议完整。
        messages = model.call_args.args[1]
        ids = [m["tool_call_id"] for m in messages
               if isinstance(m, dict) and m.get("role") == "tool"]
        self.assertEqual(ids, ["call_1", "call_2", "call_3"])