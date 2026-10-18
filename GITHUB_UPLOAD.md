# 首次上传 GitHub

本说明适用于当前 D:\Agent：尚未初始化 Git 仓库。命令在 VS Code 的 PowerShell 终端执行。以下是操作说明，不会自动上传任何文件。

## 1. 在 GitHub 新建空仓库

打开 https://github.com/new ，填写仓库名，选择 Public 或 Private。

本地已有 README 和 .gitignore，创建远程仓库时不要勾选自动添加 README、.gitignore 或 LICENSE，避免产生独立初始提交。

创建后取得 HTTPS 仓库地址，例如：

```text
https://github.com/YOUR_NAME/YOUR_REPO.git
```

下面命令中的 YOUR_NAME 和 YOUR_REPO 必须换成你的实际值。

## 2. 初始化本地仓库

```powershell
# 进入真正的项目根目录。
cd D:\Agent

# 只需要初始化一次，main 是默认分支名称。
git init -b main
```

如果提交时提示缺少身份，在当前仓库配置自己的姓名、邮箱：

```powershell
# 只设置当前仓库；邮箱使用 GitHub 关联邮箱或隐私邮箱。
git config user.name "你的名字"
git config user.email "你的邮箱"
```

Git 提交身份不等于 GitHub 登录凭据。

## 3. 检查将要提交的文件

```powershell
# 检查敏感配置、聊天记录、数据库和依赖确实被忽略。
git check-ignore .env .venv records agent.db node_modules ocr_test.png

# 查看源码和忽略项；!! 表示被忽略。
git status --short --ignored
```

预期真实 .env、records、agent.db、.venv、node_modules 不进入提交。空白的 .env.example 应提交。

ocr_demo.py、ocr_utils.py 包含的是本地程序路径，不是 API Key，可以作为源码提交。ocr_test.png 作为个人测试图片已排除；其他个人文件仍需自行检查。

## 4. 暂存并提交

```powershell
# 将未被忽略的项目文件放入本次提交。
git add .

# 检查暂存文件名及实际修改内容。
git diff --cached --name-only
git diff --cached

# 确认内容后创建本地版本。
git commit -m "docs: add project README and initial source"
```

git add 不会上传；git commit 也只保存在本地。如果分页查看 diff，按 q 返回终端。

## 5. 关联仓库并上传

```powershell
# 替换为你刚创建的实际仓库地址。
git remote add origin https://github.com/YOUR_NAME/YOUR_REPO.git

# 核对地址后，推送 main 分支并设置默认上游。
git remote -v
git push -u origin main
```

HTTPS 推送可能弹出 GitHub 登录授权，按 Git 的凭据管理器或浏览器提示操作。不要将 API Key 当作 GitHub 密码。

如果已有关联地址，先 git remote -v 查看，不要重复添加。如果远程仓库已经有提交，先确认差异后合并，不使用强制推送覆盖。

## 6. 后续更新

```powershell
# 查看变化，再提交当前修改。
git status
git add .
git diff --cached --stat
git commit -m "feat: describe the change"
git push
```

## 可选：GitHub CLI 快捷方式

如果已经安装 gh，可以在完成本地 commit 后使用交互式命令代替网页创建仓库和手动关联：

```powershell
# 先完成浏览器登录，再按提示选择推送现有本地仓库。
gh auth login
gh repo create
```

按提示选择当前仓库、仓库名与可见性。此方式与手动 remote/push 二选一即可。

参考：https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github
