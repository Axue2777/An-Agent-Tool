# 下一步：让 GitHub 自动运行测试

## 这一阶段要学什么

CI（持续集成）就是“提交代码后自动检查”。
本项目的检查链路是：

~~~text
你提交并推送代码
  → GitHub 读取仓库中的工作流
  → 在临时 Windows 环境恢复 Python、Node 和依赖
  → 执行与本地相同的隔离测试
  → 用通过或失败标记结果
  → 保存报告、日志和截图供下载
~~~

这一步不部署网站，不打包 Electron，也不接入登录。

## 新增和调整的文件

| 文件 | 作用 |
| --- | --- |
| .github/workflows/checks.yml | GitHub 必须从这个目录读取自动检查配置 |
| tests/package.json | 声明只用于测试的 Playwright 版本，不影响 Vue 运行依赖 |
| tests/package-lock.json | 固定测试依赖的实际安装版本 |
| tests/.gitignore | 忽略测试依赖、临时构建、截图和每次生成的报告 |
| .gitignore | 不再排除整个 tests，使测试源码可以提交 |
| tests/run_checks.py | 继续复用统一入口，报告中的忽略规则说明同步更新 |

测试脚本和本指南仍在 tests 中；GitHub 配置必须位于 .github/workflows 中。

## 一、理解工作流

### 1. on：什么时候运行

push 表示推送代码后检查，pull_request 表示合并请求更新时检查。
workflow_dispatch 允许从 GitHub Actions 页面手动运行。
没有限定 main 分支，所以其他分支推送后也会检查。

### 2. permissions：能做什么

contents: read 只给读取仓库的权限。
工作流不主动写入仓库，不自动提交，也不使用 DeepSeek 或智谱密钥。
使用普通 pull_request 事件，不使用权限更高的 pull_request_target。

### 3. concurrency：避免重复排队

同一分支又有新提交时，取消已经过时的检查。
最新一次提交仍会完整执行。

### 4. jobs 和 steps：依次做什么

当前只有一个检查任务，运行在临时 Windows 环境：

- 下载代码时不保留提交凭证。
- 安装 uv 和 Python 3.11，用 uv sync --locked 按 uv.lock 恢复后端依赖。
- 安装 Node 22，分别对 fronted 和 tests 执行 npm ci。
- 为临时机器准备 Edge，用 Playwright 驱动真实 Vue 页面。
- 执行 uv run --no-sync python tests/run_checks.py --browser。
- 无论测试通过还是失败，都尝试上传指定的报告文件。

uv sync 比手动逐个安装依赖更省事；
--locked 会检查依赖清单与锁文件是否一致，不会悄悄修改锁文件。
npm ci 同样根据 package-lock.json 安装，清单与锁文件不一致时会报错。

如果安装依赖阶段失败，测试尚未运行，不等于产品功能有问题。
这时应查看第一个失败步骤的日志，排查版本或网络。

### 5. 测试失败为什么整项会标红

run_checks.py 失败时返回非零退出码。
工作流没有添加 continue-on-error，也没有吞掉退出码，因此不会假装成功。
上传报告的 always() 只保证失败后仍尝试保存报告，不会把失败改成通过。

## 二、本地怎么用

原来的命令不变：

~~~powershell
.\.venv\Scripts\python.exe tests\run_checks.py --browser
~~~

普通安装了 Node、项目 Python 依赖和前端依赖的新机器，还需要一次：

~~~powershell
npm.cmd ci --prefix tests
~~~

这会按测试锁文件安装 Playwright，运行检查时可以自动发现它。
本机已有可用 Edge 时，不需要安装额外浏览器，也不要照搬 CI 的浏览器安装步骤。
本机没有 Edge 时，请先安装 Edge，或按 Playwright 官方说明配置浏览器。

有 uv 的新环境可以用更简短的方式恢复后端并执行普通检查：

~~~powershell
uv sync --locked
uv run --no-sync python tests\run_checks.py
~~~

本地现有 .venv 正常时，不需要为了这一阶段重建它。

## 三、提交前检查

先在 D:\Agent 终端查看：

~~~powershell
git status --short
git diff --check
~~~

确认可以看到 .github 和 tests 源码。
.env、agent.db、records、node_modules、tests/_artifacts 不应被新增提交。
如果这些文件以前被跟踪过，.gitignore 无法自动取消跟踪，需要先单独处理。

确认待提交的修改都是本次希望保留的代码后：

~~~powershell
git add .
git diff --cached --stat
git commit -m "ci: add automated Agent checks"
git push
~~~

功能修复代码也必须提交，否则云端运行的是旧版本，原先的问题仍会导致测试失败。
git add . 会暂存当前项目中所有未被忽略的修改，执行前务必看清 git status。
本轮助手不会替你执行提交或推送。

## 四、在哪里看运行结果

1. 打开 GitHub 上的仓库。
2. 点击 Actions。
3. 找到 Agent Checks，打开最近一次推送对应的记录。
4. 展开失败的步骤查看日志，或在 Artifacts 下载 agent-check-results。

上传的报告只保留 7 天，包含测试结果和模拟页面截图。
没有上传整个项目目录，不会把 .env、records 或真实数据库当作报告上传。
首次手动运行通常要先把工作流推送到默认分支，再查看 Run workflow 按钮。

只写好本地配置，不等于 GitHub 已运行通过。
只有提交并推送后，才能验证远端 Actions 权限、网络和依赖恢复是否正常。

## 五、遇到红色结果怎么办

| 失败步骤 | 先检查什么 |
| --- | --- |
| 下载仓库或设置运行环境 | Actions 权限、网络、Action 是否可用 |
| 安装 Python 依赖 | pyproject.toml 与 uv.lock 是否同时更新并提交 |
| npm ci | 对应目录的 package.json 与 package-lock.json 是否一致 |
| 准备浏览器 | 查看 Edge 下载或安装日志 |
| Run isolated checks | 下载报告，先看失败测试名称和 traceback |
| 上传报告 | 是否已经运行到测试步骤并生成报告 |

没有要求配置任何真实 API 密钥。
网络下载依赖是必要准备，但模型和搜索调用在测试中仍然被模拟。
这些测试不验证真实供应商的鉴权、余额和回答质量，也不验证真实 OCR 识别质量。

## 官方参考

- [GitHub Actions 工作流说明](https://docs.github.com/en/actions/writing-workflows/about-workflows)
- [uv 的 GitHub Actions 集成](https://docs.astral.sh/uv/guides/integration/github/)
- [Node 环境与 npm 缓存](https://github.com/actions/setup-node)
- [测试报告上传](https://github.com/actions/upload-artifact)
- [Playwright 的浏览器配置](https://playwright.dev/docs/browsers)

