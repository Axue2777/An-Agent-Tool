# Agent 工作台 v0.1.2

一个以学习和本地使用为目标的 Agent 项目。Vue 3 提供页面，FastAPI 提供本地接口，Electron 将前后端打包为 Windows 桌面程序。聊天可切换 DeepSeek、千问、智谱、OpenAI、Gemini，或填写其他 OpenAI 兼容接口；独立联网搜索工具目前只在智谱模式下提供。

支持在聊天中搜索公开资料、读取你选中的本机文件，并生成 Markdown、Word、Excel、PDF、PPTX、代码及图片。模型回复和工具进度通过事件流显示，聊天过程另存为 Markdown 日志。

## 当前功能

- 连续对话、Markdown 展示和模型回答流式输出。
- 可折叠侧栏，新建、切换、重命名、删除和置顶历史会话。
- SQLite 保存会话和消息；刷新后恢复上次选中的会话及未发送草稿。
- 多轮工具执行与可展开的执行记录。
- 新建聊天时自定义标题和 AI 角色；每个聊天有独立资料库。
- 每个聊天可随时重新编辑助手角色和语气；顶部展示当前及已使用的模型。
- 独立文件框列出附件与资料库文件，并标出已经读取的文件。
- DeepSeek 深度思考可开关；思考过程在回答上方实时显示，可折叠，刷新后仍保留。
- 资料库支持 TXT、Markdown、PDF、Word 和 UTF-8 库存 CSV；Agent 可检索当前聊天的资料与库存。
- 智谱联网搜索，返回网页标题、链接和摘要。
- 文本、Markdown、Word 和图片附件的文字提取与分段读取。
- 图片 OCR，以及 PDF 无文字页面的 OCR 处理。
- Markdown 报告生成与下载。
- 可制作 DOCX、XLSX、PDF、常用代码和数据文件；桌面版可逐个选择目录另存成果。
- 上传按钮可一次选择多个本机文件，支持 Excel、PPT、CSV、JSON、代码和原有文档格式。
- 桌面版「复制文件」先选择本机原文件，再选择目标位置；原文件保留，同名目标会提示失败。
- 根据逐页内容生成可编辑 PPTX；智谱 `glm-image` 生成图片并保存在当前聊天。
- 图片即使没有文字也能上传；点击该文件的「识图」后，确认将选中的图片发送给智谱视觉 API。
- 每个会话独立保存 Markdown 聊天日志。
- SQLite 保存新消息和成功回答的工具步骤，提供历史列表、详情接口。
- 软件内分别设置各服务商的模型编号和 API 密钥；密钥在当前 Windows 用户的凭据管理器中保存，重新打开软件无需重填。
- Windows 桌面版同时启动页面和本地后端。

历史会话以 SQLite 为来源；浏览器 localStorage 只记住当前选中的会话和未发送草稿。旧版仅存于浏览器的数据不会自动迁移。

## 技术结构

```text
Vue 页面
  → FastAPI /chat/stream
  → 当前选定的聊天模型：回答或提出工具请求
  → Python：按权限搜索、查询资料库、读取附件、保存报告
  → 聊天模型：根据工具结果继续行动或回答
  → SSE：向网页发送工具状态和文字片段

SQLite：保存新会话及消息
records/：保存 Markdown 日志、附件与报告
```

## 项目目录

```text
.
├── main.py                 # FastAPI 接口、模型配置及任务处理
├── api_settings.py         # 软件内 API 设置和 Windows 凭据保存
├── agent_tools.py          # 工具注册与多轮 Agent 循环
├── knowledge_store.py      # 每个聊天独立的资料库和库存数据
├── knowledge_tools.py      # 资料检索和库存查询工具定义
├── model_stream.py         # 模型流式响应与工具参数拼接
├── search_tools.py         # 智谱独立搜索 API
├── file_tools.py           # 当前会话附件的分段读取
├── report_tools.py         # Markdown 报告生成
├── creative_tools.py       # 识图、智谱生图和 PPTX 生成
├── output_tools.py         # Word、Excel、PDF、文本及代码文件生成
├── document_parser.py      # 文本、PDF、Word、图片解析入口
├── ocr_utils.py            # 图片和 PDF 页面的 OCR
├── chat_records.py         # Markdown 日志追加
├── database.py             # SQLite 初始化、写入与查询
├── dev.py                  # 一键启动开发版或已构建页面
├── api_server.py           # 后端打包入口
├── agent-backend.spec      # PyInstaller 配置
├── electron/               # 桌面程序入口与后端进程管理
│   ├── preload.cjs          # 只暴露另存和复制两个桌面操作
│   └── local-files.cjs      # 限制成果地址和文件名
├── fronted/                # Vue 项目，目录名目前确实为 fronted
│   ├── src/App.vue         # 聊天、侧栏和会话交互
│   ├── src/chat_stream.js  # 浏览器事件流读取
│   └── vite.config.js      # 开发时转发 /chat 请求
├── package.json            # Electron 及桌面打包命令
├── pyproject.toml          # Python 项目信息和固定版本的后端依赖
├── .env.example            # 不含真实密钥的配置模板
├── GITHUB_UPLOAD.md        # 首次上传 GitHub 的操作说明
├── agent.db                # 运行后生成，不提交
└── records/                # 运行后生成，不提交
```

## 环境要求

- Python 3.11 或更新的兼容版本，Windows 建议使用 64 位环境。
- Node.js 22.12 或更新的兼容版本，配套 npm。
- 至少一个所选服务商的有效 API 密钥；智谱联网搜索还需要对应接口权限和额度。
- OCR 需要独立安装 Tesseract 及简体中文、英文语言数据。

下列命令以 Windows PowerShell 为例，在项目根目录执行。

## 本地启动

### 1. 安装依赖

```powershell
# 确认当前 Python 版本至少为 3.11。
python --version
uv sync --locked
npm.cmd ci
npm.cmd ci --prefix fronted
```

`uv sync --locked` 使用 `pyproject.toml` 和 `uv.lock` 建立 `.venv`；如果尚未安装 uv，先安装 uv。浏览器自动检查还需要在 `tests` 目录安装其单独的 npm 依赖。

### 2. 启动开发版

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe dev.py
```

按终端显示的前端地址打开页面。`dev.py` 自动选择空闲端口并启动 FastAPI 与 Vite；按 `Ctrl+C` 停止。

页面右上角打开「API 设置」，选择服务商，填写模型编号和相应密钥并保存。切换服务商时，各自的模型编号和密钥会保留。千问的 Base URL 须与 API Key 所属地域一致；其他兼容服务可选「自定义 OpenAI 兼容接口」并填写可信任的 HTTPS Base URL。独立联网搜索只支持智谱模式，使用同一把智谱密钥调用单独的搜索接口。密钥保存在 Windows 凭据管理器；旧 `.env` 仅在未保存过软件设置时作为兼容来源。密钥不放入 Git 仓库。

生图使用智谱 `glm-image`，识图使用智谱 `glm-5.3-flash`；这两项需要智谱标准 API 密钥，即使聊天选择 DeepSeek 等其他服务也一样。选择其他聊天服务时，API 设置中也有单独的「智谱识图与生图密钥」输入框。模型、搜索、识图和生图可能分别计费。没有智谱密钥时，普通聊天、PPT 和本地 OCR 仍可使用。

### 3. 配置 OCR（需要识别图片时）

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

### 4. 构建和运行桌面版

```powershell
npm.cmd run pack:desktop
```

运行 `release\win-unpacked\AgentWorkspace.exe` 验证。需要安装包时执行 `npm.cmd run dist:desktop`，输出在 `release/`。这两个命令都会依次重建 Vue 页面、Python 后端，再打包桌面程序，避免把旧页面带进新安装包。桌面版将聊天数据保存在 `%LOCALAPPDATA%\AgentWorkspace`。

也可执行 `.\.venv\Scripts\python.exe dev.py --built`，由同一个本地后端提供已构建的页面与接口。

## 使用示例

新建聊天时可填写名称、助手名字、角色与个性；创建后也能在顶部修改助手名字和设定。选择本机文件后会先询问是否允许读取。库存 CSV 表头为 `product_name,stock`，例如 `机械键盘,12`；库存只属于上传它的聊天，不能当作实时商家库存。普通“上传资料”按钮用于当前聊天附件，与资料库分开。

- 普通聊天：“请解释 Vue 的响应式。”
- 搜索：“联网搜索 Vue 官方 computed 文档，并附来源链接。”
- 报告：“根据刚才的资料生成一份带来源的 Markdown 报告。”
- 附件：选择本机文件并确认，文件显示在「本聊天文件」框；输入问题后发送，附件编号不会写入输入框。之后要再次读取，可点文件旁的「下轮读取」并确认用途；也可在文件框删除。
- 桌面工作文件夹：顶部点「工作文件夹」选择固定目录；输入“读取工作文件夹中的文件并总结”后选择具体文件，确认文件名、用途和接收方。生成 Word、Excel、PDF 等成果后，软件逐份询问是否保存到该目录；取消则保留聊天内的下载链接。每次读写都需确认，且只读工作文件夹内的文件。
- 多文件：在「上传资料」一次选中多个文件，Agent 会根据本轮所选附件按需读取；Excel 和 PPT 会提取工作表或幻灯片文字。
- Word、Excel、PDF、代码：“根据这份资料制作一份 Word 总结 / Excel 表格 / PDF / Python 脚本。”成果可点「下载」；桌面版还可点「另存到…」选择具体目录。
- 复制文件：桌面版顶部点击「复制文件」，先选择现有文件，再选择目标目录与文件名。
- 识图：上传 PNG/JPG 后，在「本聊天文件」框点击对应的「识图」并确认发送给智谱；只有点击的图片会被发送。
- PPT：“制作一份三页的 Vue 入门 PPT，每页列出要点。”完成后点「下载 PPTX」。
- 生图：“画一张粉彩色的原创动漫风海边插画。”完成后在回答或执行记录中查看图片。
- 深度思考：选择 DeepSeek 后勾选输入框上方的「深度思考」，可展开或收起回答上方的思考过程。

## 主要接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /chat | 一次返回完整回答 |
| POST | /chat/stream | 事件流返回状态、正文片段和最终结果 |
| POST | /chat/upload/{conversation_id} | 上传并解析当前会话的附件 |
| GET | /chat/files/{conversation_id}/{file_id} | 下载报告、Word、Excel、PDF、PPTX、代码或查看生成图片 |
| GET | /chat/history | 查询 SQLite 会话列表 |
| GET | /chat/history/{conversation_id} | 查询某个会话的已保存消息 |
| POST | /chat/history | 创建聊天，可附自定义标题和角色 |
| PATCH | /chat/history/{conversation_id}/assistant | 修改当前聊天的助手设定 |
| GET | /chat/history/{conversation_id}/files | 查看附件和资料库文件 |
| DELETE | /chat/history/{conversation_id}/attachments/{file_id} | 删除当前聊天的附件 |
| POST | /chat/history/{conversation_id}/analyze-image | 显式识别选中的上传图片 |
| POST | /chat/history/{conversation_id}/knowledge | 上传当前聊天的资料库文件 |
| GET | /chat/history/{conversation_id}/knowledge | 查看当前聊天的资料库文件 |
| GET | /chat/settings | 查看当前服务商和配置状态，不返回密钥 |

conversation_id、file_id 使用 UUID。详情接口中的会话编号应来自历史列表，不是消息的自增数字编号。

## 数据保存

```text
records/
  会话UUID/
    chat.md                    # 消息、工具调用与错误事件
    attachments/附件UUID.txt    # 统一提取后的文字
    attachments/图片UUID.png    # 上传图片的原图
    artifacts/成果UUID.md       # Markdown 报告
    artifacts/成果UUID.pptx     # 可编辑演示文稿
    artifacts/成果UUID.docx     # Word 文档
    artifacts/成果UUID.xlsx     # Excel 表格
    artifacts/成果UUID.pdf      # PDF 文档
    artifacts/成果UUID.png      # 生成图片
agent.db                       # SQLite 会话与消息
```

源码运行时数据位于项目目录；安装版数据位于 `%LOCALAPPDATA%\AgentWorkspace`。旧 localStorage 和 Markdown 不会自动迁移。数据库与 Markdown 尚无跨存储事务，异常时两者可能不一致。

## 当前限制与待完成事项

- 本项目用于本地单用户学习，尚无登录、多用户隔离或面向公网的权限控制；桌面版只监听本机地址。
- 资料库文档目前使用简单关键词匹配，提问与原文措辞差异较大时可能检索不到。
- PDF 和其他格式的文字提取不保证完整还原原文排版；OCR 结果需要人工核对。
- Word 主要读取正文和顶层表格；文本框、图片、页眉页脚等未完整处理。
- OCR 可能有错字，混合图文页面仅在提取不到文字时尝试识别。
- 附件最多 10 MB，PDF 限制 100 页；读取工具每段最多 8000 字符，Agent 最多请求模型 12 轮。
- 分段读取仍会累计占用模型上下文，不适用于任意长度文档。
- 搜索返回摘要，不代表已经阅读全文；搜索结果和模型结论需要核对来源。
- 深度思考开关目前仅适用于 DeepSeek；其他聊天服务是否返回思考过程取决于其模型接口。PPT 当前采用文字与要点模板，复杂图表仍需手工排版。
- 识图会将用户确认选择的原图发送给智谱；本地 OCR 不需要上传图片到第三方。智谱生图与识图需要相应额度和模型权限。
- 自定义接口须支持 OpenAI Chat Completions 的流式输出和函数调用；不同服务商的模型能力并不完全相同，可先使用「测试聊天」验证连接，再在聊天里验证工具调用。
- 本机文件需要由你通过文件选择器明确选中；Agent 读取附件内容后，相关文字会随聊天请求发送给当前模型服务。图片的视觉识别仍需单独确认。
- 桌面版的复制和另存操作都由系统窗口选择具体位置；网页模式仍使用浏览器下载。生成的 Word、Excel、PDF 与 PPT 使用基础模板，复杂排版和公式可能需要后续人工调整。

## 常见问题

| 现象 | 排查方向 |
| --- | --- |
| 聊天密钥未配置 | 在页面「API 设置」里选择服务商、填写相应密钥并保存 |
| 智谱返回 429 或 1305 | 可能是模型繁忙或调用限制；稍后重试或切换到 DeepSeek 聊天 |
| 搜索 HTTP 401 | 检查智谱密钥是否有效、是否保存，重新加载配置 |
| HTTP 422 | 查看请求字段和 UUID 是否符合接口定义 |
| “任务失败，请查看后端终端” | 查看后端 Traceback；事件流的 HTTP 200 不代表任务最终成功 |
| No module named ... | 使用 .venv 中的解释器安装缺少的依赖 |
| OCR 找不到程序或语言 | 检查 Tesseract 路径和 chi_sim、eng 数据 |
| 新环境前端缺少依赖 | 在根目录执行 `npm.cmd ci` 与 `npm.cmd ci --prefix fronted` |

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
- [千问 OpenAI 兼容接口](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
- [OpenAI Chat API](https://developers.openai.com/api/reference/resources/chat)
- [Gemini OpenAI 兼容接口](https://ai.google.dev/gemini-api/docs/openai)
- [智谱联网搜索](https://docs.bigmodel.cn/cn/guide/tools/web-search)
