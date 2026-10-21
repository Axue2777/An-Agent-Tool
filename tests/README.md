# Agent 测试指南

这套检查使用 Python 标准库 unittest 和 Node 内置测试器。
测试脚本、运行日志、截图、网页构建产物均在 tests 内。
GitHub 工作流配置另放在规定的 .github/workflows 目录。

## 快速运行

在 VS Code 终端进入 D:\Agent 后执行：

~~~powershell
.\.venv\Scripts\python.exe tests\run_checks.py
~~~

含网页交互的完整检查：

~~~powershell
.\.venv\Scripts\python.exe tests\run_checks.py --browser
~~~

只运行 Python 用例，也可沿用原来的命令：

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
~~~

普通检查需要项目已安装的 Python 依赖，以及 Node 18 或更高版本。
完整网页检查建议使用 Node 22，与 GitHub 检查环境一致。
网页检查还需要 fronted/node_modules、Playwright 和 Microsoft Edge。
程序会尝试发现现有 Playwright，也可用 AGENT_PLAYWRIGHT_PATH 指定其模块目录。
不会自动安装包，也不会启动常驻开发服务器。

## 检查内容

| 文件 | 检查内容 |
| --- | --- |
| support.py | 临时数据库、文件隔离、禁止真实网络和密钥加载 |
| test_database_records.py | 标题、历史消息、顺序、并发写入、Markdown 留档 |
| test_files_reports.py | 附件分段读取、跨会话隔离、报告保存 |
| test_model_stream.py | 模型分包、工具参数拼接、中断、资源释放 |
| test_document_parsing.py | TXT、Markdown、DOCX、PDF、图片分派和 OCR 调用参数 |
| test_search_service.py | 搜索请求、状态码、超时、结果格式和异常响应 |
| test_agent_runtime.py | 工具参数、循环上限、执行记录和耗时 |
| test_api.py | 聊天、列表、详情、改名、删除、上传、下载 |
| test_cancellation.py | 任务注册、取消事件、固定回复、清理和继续聊天 |
| test_chat_stream.mjs | 11 项前端分包、中文解码、错误传播和释放检查 |
| test_frontend_stream.py | 从 Python 测试入口运行上述 Node 检查 |
| browser_checks.cjs | 真实 Vue 页面配合模拟接口的交互与响应式布局检查 |

原有的三个测试文件保持不变，也会被统一执行。

## 结果在哪里

- CHECK_REPORT.md：可直接阅读的检查报告。
- _artifacts/summary.json：机器可读的统计和失败详情。
- _artifacts/python-results.txt：Python 完整运行日志。
- _artifacts/frontend-stream.tap：11 项 Node 检查的详细结果。
- _artifacts/browser-summary.json：网页交互逐项结果。
- _artifacts/layout-*.png：不同宽度、侧栏开关状态的截图。

退出码 0 表示本次执行的检查通过；退出码 1 表示存在失败或执行错误。
跳过的检查会单独列出，不等于通过。
报告中的“执行错误”也可能是产品没有处理异常输入，不一定是测试程序错误。

## 隔离与边界

测试不会读取真实 .env，也不会调用 DeepSeek 或智谱收费接口。
后端测试使用系统临时目录和临时数据库；浏览器测试使用内存模拟接口。
检查前后比对业务代码和真实数据库指纹，以及 records 文件大小和修改时间。
报告不包含真实聊天内容或密钥。

OCR 实际识别质量、真实供应商鉴权和余额、模型回答质量未验证。
浏览器检查不能替代真实后端和前端的端到端联调。
登录鉴权、Electron 打包、正式部署不属于本轮检查范围。
浏览器脚本测试的是当前后端“每个 data 行包含完整 JSON”的事件协议，
不代表支持所有通用 SSE 协议特性。

测试源码现在可以正常提交，不需要 git add -f。
tests/.gitignore 继续排除依赖、生成的报告、截图和构建产物。

## GitHub 自动检查

工作流配置位于 .github/workflows/checks.yml。
推送和合并请求触发同一套隔离测试；结果和截图作为报告保存。
首次安装浏览器测试依赖可执行 npm.cmd ci --prefix tests。
工作流不需要真实 API 密钥，不会自动部署。

分步解释和上传操作见 [CI_GUIDE.md](CI_GUIDE.md)。

