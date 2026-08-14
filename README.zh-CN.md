# DEG

**Deterministic Engineering Governance，确定性工程治理。**

[English](README.md) | [入口切片方法](docs/zh-CN/ENTRY_SLICING.md) | [Policy 字段参考](docs/POLICY_REFERENCE.md) | [接入指南](docs/ADOPTION.md) | [架构](docs/ARCHITECTURE.md)

DEG 是开发期的外置治理控制面。它读取代码仓，按明确规则把文件和公开合同映射到责任所有者，展开跨边界生产者与消费者，选择可信检查器，并把验收结果写入哈希链 Ledger。被治理产品不导入 DEG，也不依赖 DEG 才能构建或运行。

## 它解决什么问题

全仓一份超长 AI 指南太宽，关键词搜索又不足以判断所有权和验收范围。DEG 从稳定坐标开始：

```text
精确文件路径                       公开合同
    |                                |
    v                                v
主 Floor + 局部 Knowledge       Boundary Binding
    |                                |
    +---- 显式依赖             生产者 + 消费者 + Scenario
                     \          /
                       检查计划
```

入口未归属、归属冲突或合同未知时，DEG 会保守扩大读取和验证范围，不会因为不确定而少跑检查。

## 安装

DEG 需要 Python 3.11 或更高版本，没有第三方运行依赖。

当前版本从源码安装：

```bash
git clone https://github.com/Holosukiyaa/DEG.git
cd DEG
python -m pip install -e .
```

发布到 PyPI 后，也可以使用 `python -m pip install deg-governance` 安装同一个 `deg` 命令。

## 五分钟开始

在已有代码仓根目录运行：

```bash
deg init
```

审阅 `.deg/manifest.json` 和 `.deg/policy.json` 后：

```bash
deg index build
deg index findings
deg slice --path app:src/example.py --output .deg/state/change-slice.md
deg check --path app:src/example.py
deg ledger verify
```

初始化生成的 `git diff --check` 只是示例。正式接入时必须替换为项目真实的单元测试、构建、合同检查和端到端场景。

## 主要命令

| 命令 | 用途 |
| --- | --- |
| `deg init` | 创建最小 Manifest 和 Policy。 |
| `deg index build` | 扫描受治理文件并计算责任覆盖。 |
| `deg index verify` | 检查策略、仓库版本和代码事实是否变化。 |
| `deg slice` | 编译有限责任闭包和检查计划。 |
| `deg check` | 执行切片选中的可信 checker。 |
| `deg ledger verify` | 验证证据事件的哈希链。 |
| `deg doctor` | 检查配置、工具、索引和 Ledger。 |

## 两份配置

`.deg/manifest.json` 描述目标仓在哪里、扫描哪些根目录、状态放在哪里。

`.deg/policy.json` 描述：

- `Constitution`：全局不变量；
- `Floor`：唯一主要所有权；
- `Knowledge`：局部、当前的代码导航；
- `Boundary`：跨组件交接；
- `Scenario`：真实消费者场景；
- 显式关系、公开合同绑定和可信 checker。

完整例子见 [`examples/minimal`](examples/minimal)。

## 八条设计原则

1. 目标描述意图，但不能单独决定所有权。
2. 每个受治理文件必须恰好有一个主要 Floor。
3. 公开合同必须经 Boundary 展开到生产者、消费者和场景。
4. Knowledge 负责解释当前代码，不拥有合规规则。
5. 不确定性扩大读取与验证，不扩大修改权限。
6. 静态覆盖通过不等于产品验收通过。
7. Checker 使用 argv 数组配置，不通过 shell 执行。
8. 被治理产品不依赖 DEG 才能运行。

正式建模前请先完整阅读[入口切片方法](docs/zh-CN/ENTRY_SLICING.md)。

## 当前状态

DEG `0.1` 是 Alpha 版本。Manifest、Policy、Slice、Index 和 Ledger 都带有 schema 版本，但稳定兼容承诺从 `1.0` 开始。

## 许可证

MIT
