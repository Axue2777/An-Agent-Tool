"""停止信号、部分回复记录和流式任务收尾测试。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4
import database
from tests.support import AppCase


class TestCancellation(AppCase):
    def test_stop_signal_check(self):
        signal = Event()
        self.main.check_cancelled(signal)
        signal.set()
        with self.assertRaises(self.main.TaskCancelled):
            self.main.check_cancelled(signal)

    def test_cancel_endpoint_sets_signal_and_unknown_is_idempotent(self):
        task_id, signal = uuid4(), Event()
        self.main.active_tasks[str(task_id)] = signal
        response = self.api.post(f"/chat/tasks/{task_id}/cancel")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "cancelling")
        self.assertTrue(signal.is_set())
        self.main.active_tasks.clear()
        self.assertEqual(self.api.post(f"/chat/tasks/{task_id}/cancel").json()["status"], "not_running")
        self.assertEqual(self.api.post("/chat/tasks/not-uuid/cancel").status_code, 422)

    def test_cancelled_partial_text_not_saved_as_complete_answer(self):
        signal, events = Event(), []
        def generate(*args, on_event, **kwargs):
            on_event({"type": "round_start"})
            on_event({"type": "text_delta", "text": "未完成内容"})
            signal.set()
            on_event({"type": "checkpoint"})
            raise AssertionError("停止后不应继续")
        self.agent.side_effect = generate
        request = self.main.ChatRequest(**self.request())
        with self.assertRaises(self.main.TaskCancelled):
            self.main.process_chat(request, events.append, signal)
        messages = database.get_conversation(self.chat_id)["messages"]
        self.assertEqual([m["content"] for m in messages], ["你好", "对话内容被主动停止"])
        text = (self.records / str(self.chat_id) / "chat.md").read_text(encoding="utf-8")
        self.assertIn("内容不完整", text)
        self.assertIn("未完成内容", text)
        self.assertNotIn("checkpoint", [e["type"] for e in events])

    def test_cancel_after_result_before_persistence(self):
        signal = Event()
        def generate(*args, **kwargs):
            signal.set()
            return "不应作为成功回答入库", []
        self.agent.side_effect = generate
        with self.assertRaises(self.main.TaskCancelled):
            self.main.process_chat(self.main.ChatRequest(**self.request()), stop_event=signal)
        messages = database.get_conversation(self.chat_id)["messages"]
        self.assertEqual(messages[-1]["content"], "对话内容被主动停止")

    def test_successful_stream_forwards_events_and_cleans_registry(self):
        def generate(*args, on_event, **kwargs):
            on_event({"type": "round_start"})
            on_event({"type": "checkpoint"})
            on_event({"type": "text_delta", "text": "流式回答"})
            return "流式回答", []
        self.agent.side_effect = generate
        response = self.api.post("/chat/stream", json=self.request())
        self.assertEqual(response.status_code, 200)
        events = self.events(response)
        self.assertEqual(events[0]["type"], "start")
        self.assertEqual(events[-1]["type"], "done")
        self.assertNotIn("checkpoint", [e["type"] for e in events])
        self.assertEqual(self.main.active_tasks, {})

    def test_failed_stream_sends_error_not_done_and_cleans_registry(self):
        self.agent.side_effect = RuntimeError("private-internal")
        response = self.api.post("/chat/stream", json=self.request())
        events = self.events(response)
        self.assertEqual([e["type"] for e in events], ["start", "error"])
        self.assertNotIn("private-internal", response.text)
        self.assertEqual(self.main.active_tasks, {})

    def test_running_stream_can_be_cancelled_and_next_request_works(self):
        entered, release = Event(), Event()
        def slow_agent(*args, on_event, **kwargs):
            on_event({"type": "round_start"})
            entered.set()
            if not release.wait(5):
                raise RuntimeError("测试等待超时")
            on_event({"type": "checkpoint"})
            return "不应返回", []
        self.agent.side_effect = slow_agent
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.api.post, "/chat/stream", json=self.request())
            try:
                self.assertTrue(entered.wait(5))
                with self.main.task_lock:
                    task_ids = list(self.main.active_tasks)
                self.assertEqual(len(task_ids), 1)
                response = self.api.post(f"/chat/tasks/{task_ids[0]}/cancel")
                self.assertEqual(response.status_code, 202)
            finally:
                release.set()
            events = self.events(future.result(timeout=10))
        self.assertEqual(events[-1]["type"], "cancelled")
        self.assertEqual(self.main.active_tasks, {})
        self.agent.side_effect = None
        self.agent.return_value = ("下一轮正常", [])
        self.assertEqual(self.api.post("/chat", json=self.request("下一轮")).status_code, 200)

