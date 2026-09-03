# 接入 AutoGovern2Code

Windows 用户接入 AG2C 只有一个动作：在托盘程序里选择 Git 工程。用户不用创建治理文件，也不用输入纳管命令。

## 安装

从[最新 GitHub Release](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest)下载 `AutoGovern2Code-Setup-Windows-x64.exe` 并双击。安装器会：

- 给当前用户安装自带运行环境的 AG2C，不要求 Python、管理员权限；本机有 Git 就用本机的，没有则下载到 AG2C 数据目录；
- 把同一份 Skill 安装到 Codex、Claude Code、Cursor 和通用 Agent Skills 目录；
- 把运行时加入用户 PATH，供 AI 自动调用；
- 启动托盘程序，并让它随当前用户登录启动。

托盘是本地桌面程序，不是 Web 管理台，也不是 Windows 服务。关闭窗口只是缩回托盘；已经纳管工程的 Git Guard 仍然独立生效。

## 加入现有工程

从托盘打开 AG2C，点击「添加项目」，选择一个非空 Git 仓库的根目录。AG2C 会：

1. 检测仓库的顶层区域和原生检查命令；
2. 在外部目录建立 Manifest、Policy、索引、Ledger、Hook 和工程记录；
3. 只向本机 `.git/config` 写入外部指针；
4. 保留已有 `pre-commit` Hook，并在 AG2C 通过后继续调用它；
5. 不改变工作区、暂存区和 HEAD。

有未提交修改的工程也可以先加入列表，但托盘会显示“需要处理”，正式工作副本恢复干净前，AG2C 不会启动受治理施工。

工程里不会新增 `.ag2c`、AG2C 生成的 `AGENTS.md`、`CLAUDE.md` 或凭证，也不会为了纳管产生一次工程提交。

## 平时怎么用

以后照常向编程 AI 提需求。兼容的 harness 会选择 `ag2c-governed-development` Skill，Skill 再通过本机 Git 配置识别这个工程已经纳管。路由、外部 worktree、验证、提交、fast-forward 合并和证据记录都由它完成。

托盘把三个事实分开显示：

- **AI 入口**：当前 Skill 装到了哪些已支持的工具；
- **交付**：外部治理档案和 Git 门禁有没有接通；
- **实际记录**：已经完成的任务，以及它们实现或修复了什么。

受治理任务完成只表示流程交付，不等于产品验收。在工程声明公开契约或边界/场景检查之前，产品状态保持未登记。这样不会把「装过 Skill」或「流程走完」说成「产品已经做完」。

## 换电脑或重新 clone

纳管信息故意不跟 Git 传播。换电脑后重新安装 AG2C，在托盘里把新的 clone 再加入一次即可。不同 clone 可以有不同路径、工具和 worktree，所以各自保存治理状态更符合实际。

如果是整夹复制（带着 `.git`），本机 `.git/config` 里可能还留着旧电脑的用户目录路径。添加项目或 `ag2c doctor --repair` 会先判断外部档案是否还在：拷来了就接上原来的 project-key 和历史；没拷来就在本机重新纳入，并说明旧历史不可恢复。

## 停止、恢复或卸载

托盘里的三个动作是分开的：

- **停止治理**会恢复之前的 `core.hooksPath`，移除本机 Git 指针，但项目仍留在列表里。历史证据默认保留。档案还在时，**恢复治理**不必重新纳管。
- **卸载项目**会取消该 clone 的登记，并删除对应的治理档案。
- Windows **卸载程序**会删除运行时、开机启动项、PATH 项和未被用户修改的 Skill，但不会改写用户工程。除非先卸载了项目，外部证据仍然保留。

## 旧版本迁移

选择带有旧 `.ag2c` 或 `.deg` 的仓库时，AG2C 会把治理内容和历史证据搬到外部。由于这一步需要从仓库删除旧治理文件，它会在干净正式工作副本中创建一个范围很小的维护提交；只删除旧治理目录和 AG2C 管理的说明块，不碰用户自己的说明。

给 AI 和维护者使用的等价命令是 `ag2c setup --project .`、`ag2c upgrade`、`ag2c migrate` 和 `ag2c doctor --repair`。
