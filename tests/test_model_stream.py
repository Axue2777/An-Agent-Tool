"""使用模拟 SDK 数据块检查模型流，不连接任何模型服务。"""
import unittest
from types import SimpleNamespace as N
from unittest.mock import MagicMock
from model_stream import request_stream_message


def chunk(text=None, tools=None, finish=None, empty=False):
    return N(choices=[] if empty else [
        N(delta=N(content=text, tool_calls=tools), finish_reason=finish),
    ])


def tool_part(index, call_id=None, name=None, arguments=None):
    return N(index=index, id=call_id, function=N(name=name, arguments=arguments))


class TestModelStream(unittest.TestCase):
    def prepare(self, chunks):
        client, context = MagicMock(), MagicMock()
        context.__enter__.return_value = iter(chunks)
        client.chat.completions.create.return_value = context
        return client, context

    def test_text_events_and_request_settings(self):
        client, context = self.prepare([chunk(empty=True), chunk("你"), chunk("好"), chunk(finish="stop")])
        events = []
        result = request_stream_message(client, [], [], "none", events.append)
        self.assertEqual(result.content, "你好")
        self.assertIsNone(result.tool_calls)
        self.assertEqual("".join(e["text"] for e in events if e["type"] == "text_delta"), "你好")
        self.assertEqual(events[0]["type"], "round_start")
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["tool_choice"], "none")
        self.assertTrue(kwargs["stream"])
        context.__exit__.assert_called_once()

    def test_fragmented_and_interleaved_calls_keep_ids_and_order(self):
        client, _ = self.prepare([
            chunk(tools=[tool_part(1, "call_b", "get_", '{"product_')]),
            chunk(tools=[tool_part(0, "call_a", "search_web", '{"query":"Vue"}')]),
            chunk(tools=[tool_part(1, name="stock", arguments='name":"机械键盘"}')]),
            chunk(finish="tool_calls"),
        ])
        result = request_stream_message(client, [], [], "auto")
        self.assertEqual([c.id for c in result.tool_calls], ["call_a", "call_b"])
        self.assertEqual(result.tool_calls[1].function.name, "get_stock")
        self.assertEqual(result.tool_calls[1].function.arguments, '{"product_name":"机械键盘"}')

    def test_missing_or_truncated_finish_is_error(self):
        for finish in (None, "length", "content_filter"):
            with self.subTest(finish=finish):
                client, context = self.prepare([chunk("部分内容", finish=finish)])
                with self.assertRaises(RuntimeError):
                    request_stream_message(client, [], [], "auto")
                context.__exit__.assert_called_once()

    def test_callback_cancellation_closes_upstream(self):
        client, context = self.prepare([chunk("不能继续"), chunk(finish="stop")])
        class Cancelled(Exception):
            pass
        def on_event(event):
            if event["type"] == "checkpoint":
                raise Cancelled()
        with self.assertRaises(Cancelled):
            request_stream_message(client, [], [], "auto", on_event)
        context.__exit__.assert_called_once()

    def test_upstream_exception_propagates(self):
        client, _ = self.prepare([])
        client.chat.completions.create.side_effect = RuntimeError("模拟上游故障")
        with self.assertRaisesRegex(RuntimeError, "模拟上游故障"):
            request_stream_message(client, [], [], "auto")

