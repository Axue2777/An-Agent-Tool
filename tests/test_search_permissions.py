import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from agent_tools import run_agent


class TestSearchPermissions(unittest.TestCase):
    def run_case(self, enabled, ask_search=False):
        responses = []
        if ask_search:
            # 模拟模型提出搜索请求，包括关闭联网时的违规请求。
            call = SimpleNamespace(id="call_search_1", function=SimpleNamespace(
                name="search_web",
                arguments=json.dumps({"query": "Vue 官方文档"}),
            ))
            responses.append(SimpleNamespace(content="", tool_calls=[call]))
        responses.append(SimpleNamespace(content="模拟回答", tool_calls=[]))
        # 隔离次数限制，并阻止真实模型、工具执行和文件写入。
        with (
            patch("agent_tools.MAX_TOOL_CALLS", 8),
            patch("agent_tools.request_stream_message",
                  side_effect=responses) as model,
            patch("agent_tools.execute_tool",
                  return_value={"sources": []}) as tool,
            patch("agent_tools.append_record"),
        ):
            _, steps = run_agent(None, [], None, web_search=enabled)
        return steps, model, tool

    def test_disabled_hides_search(self):
        # 关闭联网后，传给模型的工具列表不包含搜索，但保留库存。
        _, model, tool = self.run_case(False)
        names = {item["function"]["name"]
                 for item in model.call_args.args[2]}
        self.assertNotIn("search_web", names)
        self.assertIn("get_stock", names)
        tool.assert_not_called()

    def test_disabled_rejects_search(self):
        # 即使模型仍要求搜索，后端也必须拦截。
        steps, _, tool = self.run_case(False, ask_search=True)
        tool.assert_not_called()
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["result"]["error"], "本轮未开启联网搜索")

    def test_enabled_after_disabled(self):
        # 关闭一次再开启，避免错误修改全局工具列表后无法恢复。
        self.run_case(False)
        steps, model, tool = self.run_case(True, ask_search=True)
        names = {item["function"]["name"]
                 for item in model.call_args.args[2]}
        self.assertIn("search_web", names)
        tool.assert_called_once()
        self.assertEqual(tool.call_args.args[0].function.name, "search_web")
        self.assertEqual(steps[0]["result"], {"sources": []})