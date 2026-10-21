# Agent 工作台

一个以学习和本地使用为目标的网页 Agent 项目。前端使用 Vue 3，后端使用 FastAPI，DeepSeek 负责对话与工具选择，智谱提供联网搜索。

支持在聊天中查询示例库存、搜索公开资料、读取上传附件，并生成可下载的 Markdown 报告。模型回复和工具进度通过事件流显示，聊天过程另存为 Markdown 日志。

## 当前功能

- 连续对话、Markdown 展示和模型回答流式输出。
- 可折叠侧栏，新建、切换、重命名、删除和置顶浏览器历史会话。
- 刷新恢复上次选中的浏览器会话。
- 多轮工具执行与可展开的执行记录。
- 智谱联网搜索，返回网页标题、链接和摘要。
- 文本、Markdown、Word 和图片附件的文字提取与分段读取。
- 图片 OCR 和 PDF 无文字页面的 OCR 处理逻辑，PDF 分支仍有已知问题，见“当前限制”。
- Markdown 报告生成与下载。
- 每个会话独立保存 Markdown 聊天日志。
- SQLite 保存新消息和成功回答的工具步骤，提供历史列表、详情接口。

当前 Vue 历史仍以浏览器 localStorage 为来源，SQLite 查询接口已接入后端，跨浏览器历史恢复和旧记录迁移尚未完成。

## 技术结构

```text
Vue 页面
  → FastAPI /chat/stream
  → DeepSeek：回答或提出工具请求
  → Python：搜索、读取附件、查询示例库存、保存报告
  → DeepSeek：根据执行结果继续行动或回答
  → SSE：向网页发送工具状态和文字片段

SQLite：保存新会话及消息
records/：保存 Markdown 日志、附件与报告
```

## 项目目录

```text
.
├── main.py                 # FastAPI 接口、模型配置及任务处理
├── agent_tools.py          # 工具注册与多轮 Agent 循环
├── model_stream.py         # 模型流式响应与工具参数拼接
├── search_tools.py         # 智谱独立搜索 API
├── file_tools.py           # 当前会话附件的分段读取
├── report_tools.py         # Markdown 报告生成
├── document_parser.py      # 文本、PDF、Word、图片解析入口
├── ocr_utils.py            # 图片和 PDF 页面的 OCR
├── chat_records.py         # Markdown 日志追加
├── database.py             # SQLite 初始化、写入与查询
├── fronted/                # Vue 项目，目录名目前确实为 fronted
│   ├── src/App.vue         # 聊天、侧栏和会话交互
│   ├── src/chat_stream.js  # 浏览器事件流读取
│   └── vite.config.js      # 开发时转发 /chat 请求
├── package.json            # 当前放在根目录的 Markdown 展示依赖
├── pyproject.toml          # Python 项目信息和固定版本的后端依赖
├── .env.example            # 不含真实密钥的配置模板
├── GITHUB_UPLOAD.md        # 首次上传 GitHub 的操作说明
├── agent.db                # 运行后生成，不提交
└── records/                # 运行后生成，不提交
```

## 环境要求

- Python 3.11 或更新的兼容版本，Windows 建议使用 64 位环境。
- Node.js 22.12 或更新的兼容版本，配套 npm。
- 有效的 DeepSeek API Key；联网搜索另外需要智谱 API Key 和对应服务额度。
- OCR 需要独立安装 Tesseract 及简体中文、英文语言数据。

下列命令以 Windows PowerShell 为例，在项目根目录执行。

## 本地启动

### 1. 创建环境并安装后端依赖

```powershell
# 确认当前 Python 版本至少为 3.11，再创建虚拟环境。
python --version
python -m venv .venv

# 使用项目自己的解释器安装运行所需依赖。
.\.venv\Scripts\python.exe -m pip install fastapi uvicorn httpx openai pydantic python-dotenv python-multipart pypdf python-docx pillow pytesseract pypdfium2 tzdata
```

如果已经有可用的 .venv，可跳过创建环境。项目已用 pyproject.toml 和 uv.lock 固定后端依赖；
已安装 uv 的环境可以直接执行 uv sync --locked，替代手动逐个安装依赖。

### 2. 配置密钥

在项目根目录创建 .env，按 .env.example 的字段填写：

```dotenv
# 聊天和工具选择使用 DeepSeek。
DEEPSEEK_API_KEY=你的DeepSeek密钥

# 联网搜索使用智谱，不能填 DeepSeek 密钥。
ZHIPU_API_KEY=你的智谱密钥
```

main.py 按脚本位置加载 .env，并以文件配置覆盖同名环境变量。保存 .env 后完整重启后端；密钥不放入前端或 Git 仓库。

### 3. 配置 OCR

安装 [Tesseract](https://tesseract-ocr.github.io/tessdoc/Installation.html)，并安装 chi_sim、eng 语言数据。目前 ocr_utils.py 使用这个 Windows 路径：

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

安装在其他位置时，需要调整 ocr_utils.py 的配置。

```powershell
# 检查识别程序和语言数据。
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --version
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs
```

### 4. 启动后端

```powershell
# 开发模式：保存 Python 源码后自动重载。
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

接口文档：http://127.0.0.1:8000/docs

### 5. 启动前端

另开一个终端，先在项目根目录执行，再进入 fronted：

```powershell
# 当前 marked、dompurify 声明在根目录，先恢复这部分依赖。
npm.cmd ci

# 安装 Vue 项目依赖，启动并自动打开浏览器。
cd fronted
npm.cmd ci
npm.cmd run dev -- --open
```

以前端终端实际输出的地址为准，通常是 http://localhost:5173 。后端终端同时保持运行。

Vite 开发服务器将 /chat 开头的请求转发至 http://127.0.0.1:8000 。生产部署或 Electron 打包时需要单独处理接口地址与静态页面服务。

## 使用示例

- 普通聊天：“请解释 Vue 的响应式。”
- 示例工具：“查询机械键盘和无线鼠标库存。”
- 搜索：“联网搜索 Vue 官方 computed 文档，并附来源链接。”
- 报告：“根据刚才的资料生成一份带来源的 Markdown 报告。”
- 附件：选择文件上传，确认输入框中出现附件编号，再发送分析要求。

库存只是本地示例数据：机械键盘 12 件、无线鼠标 0 件、显示器 5 件，不提供真实购物或下单功能。

## 主要接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /chat | 一次返回完整回答 |
| POST | /chat/stream | 事件流返回状态、正文片段和最终结果 |
| POST | /chat/upload/{conversation_id} | 上传并解析当前会话的附件 |
| GET | /chat/files/{conversation_id}/{file_id} | 下载生成的 Markdown 报告 |
| GET | /chat/history | 查询 SQLite 会话列表 |
| GET | /chat/history/{conversation_id} | 查询某个会话的已保存消息 |

conversation_id、file_id 使用 UUID。详情接口中的会话编号应来自历史列表，不是消息的自增数字编号。

## 数据保存

```text
records/
  会话UUID/
    chat.md                    # 消息、工具调用与错误事件
    attachments/附件UUID.txt    # 统一提取后的文字
    artifacts/报告UUID.md       # 生成的成果
agent.db                       # SQLite 会话与消息
```

SQLite 从接入之后的新消息开始记录，旧 localStorage 和 Markdown 不会自动迁移。数据库与 Markdown 尚无跨存储事务，异常时两者可能不一致。

## 当前限制与待完成事项

- 本项目用于本地单用户学习，尚无登录、会话归属校验及面向公网的完整权限控制。
- Electron 桌面打包尚未实现；当前需要分别运行前后端。
- 当前没有接入完整的任务取消功能。
- 前端历史管理仍使用 localStorage，后端数据库尚未成为全部历史操作的主数据源。
- 当前 PDF 分支缺少将页面文字追加到 parts 的步骤，可能返回空内容，仍需修复后验证；其他格式也不保证完整还原原文排版。
- Word 主要读取正文和顶层表格；文本框、图片、页眉页脚等未完整处理。
- OCR 可能有错字，混合图文页面仅在提取不到文字时尝试识别。
- 附件最多 10 MB，PDF 限制 100 页；读取工具每段最多 8000 字符，Agent 最多请求模型 12 轮。
- 分段读取仍会累计占用模型上下文，不适用于任意长度文档。
- 搜索返回摘要，不代表已经阅读全文；搜索结果和模型结论需要核对来源。
- 依赖清单、配置和前后端目录结构仍在整理。

## 常见问题

| 现象 | 排查方向 |
| --- | --- |
| KeyError: DEEPSEEK_API_KEY | 检查 .env 的名称、位置、是否保存，以及服务是否重启 |
| 搜索 HTTP 401 | 检查智谱密钥是否有效、是否保存，重新加载配置 |
| HTTP 422 | 查看请求字段和 UUID 是否符合接口定义 |
| “任务失败，请查看后端终端” | 查看后端 traceback，不能仅凭事件流的 HTTP 200 判断任务成功 |
| No module named ... | 使用 .venv 中的解释器安装缺少的依赖 |
| OCR 找不到程序或语言 | 检查 Tesseract 路径和 chi_sim、eng 数据 |
| 新环境前端缺少 Markdown 库 | 当前需同时安装根目录和 fronted 的 npm 依赖 |

## 开发与上传

首次上传步骤见 [GITHUB_UPLOAD.md](GITHUB_UPLOAD.md)。

### 自动检查

本地完整检查命令：

~~~powershell
.\.venv\Scripts\python.exe tests\run_checks.py --browser
~~~

测试使用模拟模型、搜索和临时数据库，不需要真实 API 密钥。
GitHub 配置位于 .github/workflows/checks.yml，推送或合并请求后自动检查，
并保存报告和模拟页面截图；不会自动部署应用。
完整操作说明及每一步的作用见 [tests/CI_GUIDE.md](tests/CI_GUIDE.md)。

仓库保留源码、依赖清单、锁文件和空白配置模板。真实 .env、.venv、node_modules、agent.db、records、私人测试图片等通过 .gitignore 排除。

目前未指定开源许可证；发布前可根据用途选择并添加 LICENSE。

## 参考

- [Vue](https://cn.vuejs.org/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [DeepSeek API](https://api-docs.deepseek.com/zh-cn/)
- [智谱联网搜索](https://docs.bigmodel.cn/cn/guide/tools/web-search)
