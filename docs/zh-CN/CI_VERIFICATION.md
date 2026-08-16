# 可移植凭证与 CI 复核

本机 Ledger 适合解释 AI 做了什么，但另一台机器不能直接信任开发者本机的忽略目录。因此，AG2C 会在每个受治理任务的提交中写入一份可跟随 Git 传播的凭证。

## 凭证绑定了什么

`.ag2c/receipts/<task-id>.json` 会记录：

- 任务起点、最终变更路径和精确内容摘要；
- 最终责任路由、验收状态和每项可信检查结果；
- 验证时使用的 Manifest 与 Policy 的 Git 对象；
- 失败次数、是否证明纠正，以及被阻止的危险操作；
- 凭证自身的规范 JSON 摘要。

`ag2c ci verify` 直接从 Git 对象重建变更，核对路径、文件模式、内容、策略、检查和凭证身份。凭证本身不参与产品内容摘要，不能靠“改凭证”伪造匹配结果。

## 本地复核

检出历史必须包含任务起点：

```bash
ag2c ci verify --commit HEAD
ag2c ci verify --commit HEAD --rerun
```

`--rerun` 还要求当前正好位于该提交且工作区干净。AG2C 会重建索引、按实际提交差异重新路由、确认检查计划没有变化，再把可信检查跑一遍。

## GitHub Actions

增加 `.github/workflows/ag2c.yml`：

```yaml
name: AG2C proof

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          fetch-depth: 0
      - uses: Holosukiyaa/AutoGovern2Code/.github/actions/verify@v0.4.0
```

公开 Action 会安装对应版本的 AG2C、核对凭证并默认重跑检查。只有其他 Job 已经运行完全相同的可信命令时，才应设置 `rerun: "false"`。

多人仓库应把这个 Job 设为分支保护的必需检查。本机 Git Guard 负责单人施工路径，远端分支保护负责约束协作者的推送与合并。

## 边界

凭证能证明提交内容、声明路由和检查结果相互一致。它不能证明项目选择的检查一定充分，也不能替代操作系统安全、仓库管理员权限和远端平台规则。
