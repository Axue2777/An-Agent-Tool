"""统一运行测试并生成报告；不读取真实密钥，不连接收费服务。"""
import argparse
import hashlib
import io
import json
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "tests"
ARTIFACTS = HERE / "_artifacts"
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def snapshot():
    # 数据库只计算指纹，聊天文件仅记录元数据，报告不包含聊天正文。
    files = list(ROOT.glob("*.py")) + list((ROOT / "fronted" / "src").rglob("*"))
    files += [ROOT / "agent.db"]
    result = {}
    for path in files:
        if path.is_file():
            result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    records = ROOT / "records"
    if records.exists():
        for path in records.rglob("*"):
            if path.is_file():
                stat = path.stat()
                result[str(path.relative_to(ROOT))] = [stat.st_size, stat.st_mtime_ns]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="store_true", help="额外运行模拟接口的浏览器检查")
    args = parser.parse_args()
    ARTIFACTS.mkdir(exist_ok=True)
    before = snapshot()
    started = time.monotonic()
    log = io.StringIO()
    with redirect_stdout(log), redirect_stderr(log):
        suite = unittest.defaultTestLoader.discover(str(HERE), top_level_dir=str(ROOT))
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    (ARTIFACTS / "python-results.txt").write_text(log.getvalue(), encoding="utf-8")
    summary = {
        "time": datetime.now().astimezone().isoformat(),
        "python_tests": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "failures": [{"test": str(test), "traceback": trace} for test, trace in result.failures],
        "errors": [{"test": str(test), "traceback": trace} for test, trace in result.errors],
        "skipped": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
        "browser": {"status": "not_run"},
    }
    if args.browser:
        target = ARTIFACTS / "browser-summary.json"
        target.unlink(missing_ok=True)
        try:
            browser = subprocess.run(
                ["node", str(HERE / "browser_checks.cjs")], cwd=ROOT,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=240,
            )
            (ARTIFACTS / "browser-log.txt").write_text(browser.stdout + browser.stderr, encoding="utf-8")
            summary["browser"] = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {
                "status": "error", "message": browser.stdout + browser.stderr,
            }
        except (OSError, subprocess.TimeoutExpired) as error:
            summary["browser"] = {"status": "error", "message": str(error)}
    after = snapshot()
    browser_checks = summary["browser"].get("checks", [])
    summary["browser"]["total"] = len(browser_checks)
    summary["browser"]["passed"] = sum(item["status"] == "passed" for item in browser_checks)
    summary["protected_files_unchanged"] = before == after
    summary["changed_paths"] = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    summary["seconds"] = round(time.monotonic() - started, 2)
    (ARTIFACTS / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report = [
        "# Agent 自动化检查报告", "",
        f"运行时间：{summary['time']}", "",
        f"- Python 测试：{result.testsRun} 项，通过 {summary['passed']} 项。",
        f"- 断言失败：{len(result.failures)} 项；执行错误：{len(result.errors)} 项；跳过：{len(result.skipped)} 项。",
        "- 前端流解析：Python 中的一个测试项会另外执行 11 项 Node 检查，详情见 _artifacts/frontend-stream.tap。",
        f"- 浏览器检查：{summary['browser']['status']}，共 {summary['browser']['total']} 项，通过 {summary['browser']['passed']} 项。",
        f"- 业务代码、真实数据库指纹及聊天文件元数据保持不变：{summary['protected_files_unchanged']}。",
        "", "## 发现的问题", "",
    ]
    for item in summary["failures"] + summary["errors"]:
        name = item["test"]
        if "whitespace_only" in name:
            report.append("- 后端接口接收纯空白消息：应在 main.py 的输入校验处拒绝。")
        if "non_object_payload" in name:
            report.append("- 智谱返回的 JSON 不是对象时，search_tools.py 调用 .get() 导致异常。")
        if "non_object_result_item" in name:
            report.append("- 搜索结果含 null 等非对象条目时，search_tools.py 调用 .get() 导致异常。")
    for item in browser_checks:
        if item["status"] == "failed" and "筛选期间新建" in item["name"]:
            report.append("- 前端搜索历史期间新建聊天，会被旧关键词隐藏；App.vue 的 newChat 未清除筛选或保留当前选中项。")
    report.extend(["", "## 失败和错误详情", ""])
    for kind in ("failures", "errors"):
        for item in summary[kind]:
            report.extend([f"### {item['test']}", "", "~~~text", item["traceback"], "~~~", ""])
    if not summary["failures"] and not summary["errors"]:
        report.append("本次 Python 检查未发现失败。")
    for item in summary["browser"].get("checks", []):
        report.append(f"- [{item['status']}] {item['name']}" + (f"：{item['error']}" if item.get("error") else ""))
    report.extend([
        "", "## 检查边界", "",
        "- 模型、联网搜索、流式回复均使用模拟数据；没有验证真实 API 密钥、余额、供应商可用性或回答准确性。",
        "- 文档解析使用生成的测试文档；OCR 调用被模拟，未验证本机 Tesseract 安装和真实识别质量。",
        "- 浏览器测试使用真实 Vue 页面和模拟后端，不能替代真实服务端与页面联调。",
        "- 没有测试登录鉴权、Electron 打包或部署，因为本轮未实现这些功能。",
        "- 测试源码可以提交；tests/.gitignore 排除依赖、生成的报告和运行产物。",
        "- 测试脚本和运行产物位于 tests 内；GitHub 工作流位于 .github/workflows。",
    ])
    (HERE / "CHECK_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Python: {summary['passed']}/{result.testsRun} passed; failures={len(result.failures)} errors={len(result.errors)} skipped={len(result.skipped)}")
    print(f"Browser: {summary['browser']['status']}; protected files unchanged: {summary['protected_files_unchanged']}")
    print(f"Report: {HERE / 'CHECK_REPORT.md'}")
    for item in summary["failures"] + summary["errors"]:
        print("FAILED:", item["test"])
    failed = result.failures or result.errors or not summary["protected_files_unchanged"] or summary["browser"]["status"] in ("failed", "error")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

