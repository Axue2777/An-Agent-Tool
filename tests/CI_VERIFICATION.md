# GitHub 自动检查配置验证记录

日期：2026-10-21

## 已完成

- 添加 .github/workflows/checks.yml，包含推送、合并请求、手动触发。
- 使用只读仓库权限，没有配置真实模型或搜索密钥，没有自动部署步骤。
- actionlint 1.7.12 工作流静态检查通过，工具下载包已核对发布的 SHA256。
- npm ci --prefix tests 的锁文件安装通过，测试依赖独立于前端依赖。
- 当前可用环境执行完整检查：Python 94/94 通过，前端流解析 11/11 通过，浏览器交互与布局 18/18 通过。
- git diff --check 未发现补丁空白错误。
- 测试源码可以提交；密钥、数据库、聊天文件、依赖和测试产物仍被忽略。
- 没有替用户提交或推送代码。

## 尚未完成的验证

在 tests/_artifacts/ci-venv 中尝试使用 uv sync --locked 恢复干净环境：

- 锁文件检查和依赖解析完成，解析出 35 个包。
- 下载 pypdf 6.20.1 时，files.pythonhosted.org 请求超时，重试后退出。
- 因而没有在这个干净环境中执行测试；不能宣称干净安装已完整验证。
- 当前 .venv 未被修改；未为绕过下载超时更改版本或锁文件。

还没有把配置推送到 GitHub，因此远端 Actions 运行状态未验证。
提交后请到仓库 Actions → Agent Checks 查看首次执行结果。
远端环境还可能受网络、仓库 Actions 权限和依赖下载状态影响。

## 运行结果在哪里

- tests/CHECK_REPORT.md：本机最近一次完整测试报告。
- tests/_artifacts/summary.json：结构化统计。
- tests/_artifacts/browser-summary.json：网页交互逐项结果。
- tests/_artifacts/layout-*.png：桌面和窄屏截图。

本记录不是 GitHub 云端成功证明，也不代表真实 API 和真实 OCR 识别质量已验证。
