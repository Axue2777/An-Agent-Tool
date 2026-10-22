from tests.support import AppCase


class TestHealthApi(AppCase):
    # 复用现有隔离环境，不读取真实密钥，也不调用模型。
    def test_health_returns_service_status(self):
        response = self.api.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "service": "agent-workspace"},
        )

        # 健康检查只能报告服务状态，不能触发 Agent。
        self.agent.assert_not_called()