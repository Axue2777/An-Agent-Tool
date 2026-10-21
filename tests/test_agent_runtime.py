"""补充工具参数、调用事件、耗时和循环兜底的测试。"""
import json
import unittest
from types import SimpleNamespace as N
from unittest.mock import patch
import agent_tools


def call(name="get_stock", args=None):
    return N(id="call_test", function=N(name=name, arguments=json.dumps(
        {"product_name": "机械键盘"} if args is None else args,
    )))


class TestAgentRuntime(unittest.TestCase):
    def test_invalid_json_and_argument_types(self):
        for arguments in ("{", "null", "[]", "123"):
            with self.subTest(arguments=arguments):
                request = call()
                request.function.arguments = arguments
                self.assertIn("error", agent_tools.execute_tool(request, None))
        for args in ({"product_name": 1}, {"product_name": "机械键盘", "extra": True}):
            self.assertIn("error", agent_tools.execute_tool(call(args=args), None))

    def test_plain_answer_does_not_execute_tools(self):
        with patch.object(agent_tools, "request_stream_message", return_value=N(content="回答", tool_calls=[])), patch.object(agent_tools, "execute_tool") as execute:
            reply, steps = agent_tools.run_agent(None, [], None)
        self.assertEqual((reply, steps), ("回答", []))
        execute.assert_not_called()

    def test_events_duration_and_markdown_share_real_result(self):
        events = []
        responses = [N(content=None, tool_calls=[call()]), N(content="回答", tool_calls=[])]
        with (
            patch.object(agent_tools, "request_stream_message", side_effect=responses),
            patch.object(agent_tools, "execute_tool", return_value={"stock": 12}),
            patch.object(agent_tools, "append_record") as record,
            patch.object(agent_tools, "perf_counter", side_effect=[10, 10.125]),
        ):
            _, steps = agent_tools.run_agent(None, [], None, events.append)
        self.assertEqual([e["type"] for e in events], ["tool_start", "tool_end"])
        self.assertEqual(events[-1]["duration_ms"], 125)
        self.assertEqual(steps[0]["duration_ms"], 125)
        self.assertIn("125", record.call_args.args[2])

    def test_rejected_search_has_no_execution_duration(self):
        responses = [N(content=None, tool_calls=[call("search_web", {"query": "Vue"})]), N(content="回答", tool_calls=[])]
        with patch.object(agent_tools, "request_stream_message", side_effect=responses), patch.object(agent_tools, "execute_tool") as execute, patch.object(agent_tools, "append_record"):
            _, steps = agent_tools.run_agent(None, [], None, web_search=False)
        execute.assert_not_called()
        self.assertIsNone(steps[0]["duration_ms"])

    def test_model_ignoring_final_none_is_stopped_at_twelve_rounds(self):
        # 每轮均提出工具调用，连最后一轮也不服从 none，必须明确失败。
        with (
            patch.object(agent_tools, "MAX_TOOL_CALLS", 100),
            patch.object(agent_tools, "request_stream_message", side_effect=lambda *a, **k: N(content=None, tool_calls=[call()])) as model,
            patch.object(agent_tools, "execute_tool", return_value={"stock": 12}) as execute,
            patch.object(agent_tools, "append_record"),
        ):
            with self.assertRaises(RuntimeError):
                agent_tools.run_agent(None, [], None)
        self.assertEqual(model.call_count, 12)
        self.assertEqual(model.call_args.args[3], "none")
        self.assertEqual(execute.call_count, 11)

    def test_unexpected_tool_exception_is_not_faked_as_success(self):
        with patch.object(agent_tools, "request_stream_message", return_value=N(content=None, tool_calls=[call()])), patch.object(agent_tools, "execute_tool", side_effect=RuntimeError("模拟工具异常")), patch.object(agent_tools, "append_record"):
            with self.assertRaisesRegex(RuntimeError, "模拟工具异常"):
                agent_tools.run_agent(None, [], None)

