import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from agent_tools import execute_tool


class TestInventoryTool(unittest.TestCase):
    def setUp(self):
        # 使用固定测试数据，不依赖项目库存以后如何变化。
        inventory = patch.dict(
            "agent_tools.INVENTORY",
            {"机械键盘": 12, "无线鼠标": 0},
            clear=True,
        )
        inventory.start()
        self.addCleanup(inventory.stop)

    def invoke(self, name, arguments):
        # 模拟模型返回的工具请求，不向模型发送请求。
        call = SimpleNamespace(function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments, ensure_ascii=False),
        ))
        return execute_tool(call, None)

    def test_in_stock(self):
        # 有货：应返回找到商品及正确数量。
        result = self.invoke("get_stock", {"product_name": "机械键盘"})
        self.assertTrue(result["found"])
        self.assertEqual(result["stock"], 12)

    def test_zero_stock(self):
        # 库存为零仍是已知商品，不能当作商品不存在。
        result = self.invoke("get_stock", {"product_name": "无线鼠标"})
        self.assertTrue(result["found"])
        self.assertEqual(result["stock"], 0)

    def test_unknown_product(self):
        # 商品不存在：库存应未知，不能编造为零。
        result = self.invoke("get_stock", {"product_name": "测试商品"})
        self.assertFalse(result["found"])
        self.assertNotIn("stock", result)

    def test_missing_argument(self):
        # 缺少必要参数时，返回可交给模型处理的错误。
        self.assertIn("error", self.invoke("get_stock", {}))

    def test_unknown_tool(self):
        # 未注册的工具不得执行。
        self.assertIn("error", self.invoke("unknown_tool", {}))