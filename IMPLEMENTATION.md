# 本轮实现与验证记录

日期：2026-10-11。以下路径均相对于项目根目录。

公开验证摘要见 [验证说明](docs/validation.md)。下文 `runs/` 与 `reports/` 中的原始证据属于本地实验产物，未随 Git 仓库发布；保留路径以识别历史批次。

本轮把原来的演示框架改成能检查执行完整性、保存原始证据并进行配对比较的实验原型。工程路径已实现并验证；独立人工验收和真实外部任务成绩仍未完成，不能据此宣称已经证明优于强化 CI。

## 已实现的改进

| 原问题 | 本轮改动 | 验证方式 |
| --- | --- | --- |
| 退出零可冒充通过 | pytest 完成协议、原始测试节点与完整执行阶段；需求断言执行记录 | 提前退出、空测试、全部跳过、缺少断言等回归 |
| HEAD 可移动、补丁不完整 | 固定初始 SHA、完整差异及快照恢复，纳入未跟踪/忽略/二进制文件 | 候选自行提交与二进制、中文、空格路径回放 |
| 任意 shell 与轨迹缺口 | 工作区文件工具、固定 run_tests、拒绝事件及运行前后文件变化 | 越界/.git/自由命令拒绝与轨迹回归 |
| 需求与参考实现不一致 | 加入原始回归测试；补齐金额/转账/账本/分页/认证/库存等合约 | 30 个正确参考通过、30 个遗漏需求参考被拒绝 |
| 新增测试及正常调试误报 | 区分新增测试和既有测试；失败编辑不算成功修改；调试后清除连续失败状态 | 良性新增测试、正常调试及失败编辑挑战 |
| 无法证明 trace 增量 | 加入最终恢复测试文件的过程变异；消融先经过测试、需求和 diff | 30 个最终 diff 无测试修改的过程案例 |
| 两组独立首次产出导致混杂 | 4 条件共享同一次首次补丁、相同重试次数上限及重生成方式 | 配对调用次数、共享哈希、反馈可见内容回归 |
| 日志不足、批次混用、成本重复 | run_id、原始模型响应/工具轨迹/补丁、源码与任务快照、实际返回 usage 计数 | 文件哈希/档案、SQLite 与 study 逐行核验 |
| 失败被当成人工干预 | 单独记录 human_interventions 事件，不从失败反推人工操作 | 无人工事件的失败结果仍为 0 条已记录干预 |
| 合成数据被当成真实检测率 | 明确来源、未标注/INVALID 分母及统计限制；盲评与双人标注入口 | 合成、未标注与人工标签流程回归 |
| Docker/外部数据只有名义入口 | Docker 接入统一执行后端；真实 SWE-bench 数据与官方 harness 桥接 | Docker 参数与阻塞测试；真实下载 10 条任务 |
| CI 示例被当成 PR 评级 | workflow 验证框架与参考实现；ci 输出明确标为合成回归 | CLI 预检与退出状态测试 |

任务加载器还会提前拒绝缺失需求实现、重复身份、越界路径、空需求和坏测试节点清单。验收文件在调用代理前完成格式与语法预检，避免付费之后才发现配置错误。

## 实际验证结果

整体回归：179 项通过；之后新增的 6 项验收/CLI 检查也通过，共 185 个已验证用例。最新定向命令执行 9 项，包含这 6 个新增用例及 3 个既有配对用例。

```powershell
python -B -m pytest tests -p no:cacheprovider --basetemp runs/full-final-20261011 --tb=short
python -B -m pytest tests/test_cli_integrity.py tests/test_paired_evidence.py -p no:cacheprovider --basetemp runs/cli-evidence-final-tests --tb=short
```

完成检查还包括源码语法、框架与原始任务 zip 档案完整性，以及真实/离线实验 JSON 与 SQLite payload 的一致性。仪表盘源码已更新并检查语法；本机没有安装 Streamlit，未进行实际浏览器验收。Docker 命令通过模拟测试，本机没有 Docker，不能称容器执行已通过。

### 330 个合成挑战

最终本地证据：JSON `reports/challenges-20261011-final.json`、报告 `reports/challenges-20261011-final.md`。8 个工作进程，30 个任务 × 11 类变异。

| 累计信号 | TP | FP | FN | TN |
| --- | --- | --- | --- | --- |
| tests | 0 | 0 | 150 | 150 |
| + requirements | 60 | 0 | 90 | 150 |
| + diff | 120 | 0 | 30 | 150 |
| + trace | 150 | 0 | 0 | 150 |

30 个 hollow_test 样本因原始测试节点缺失判为 INVALID，全部保留，未混入检测矩阵。150 个良性可评分样本全部没有复核信号。trace 在已有测试、需求和 diff 之后新增 30 个过程变异标记；这说明对应回归案例被覆盖，不能外推成真实代理总体召回率 100%。退化重采样区间明确显示为不可估计。

首批并行运行曾出现 10 个良性误报。原因是 pytest 在 Windows 向上枚举目录时遇到被其他工作进程清理的兄弟工作区。已增加 confcutdir 和独立 pytest 配置，保留候选仓库自己的 conftest；会话遍历等基础设施收集错误判 INVALID，普通候选测试模块导入错误仍是功能 FAIL。旧批次本地文件 `reports/challenges-20261011.json` 保留用于诊断，以最终批次作为修复后的回归依据。

### 配对实验

离线批次本地证据：报告 `runs/evidence/paired/offline-paired-20261011/study.md`、原始证据 `runs/evidence/paired/offline-paired-20261011/study.json`。todo/002 的两个首次样本都通过测试但遗漏需求；no_retry/tests_retry 均为 0/2，requirements_retry/full_retry 各在一次重试后达到 2/2。该批次只验证流程和反馈差异，不作为真实模型效果。

真实批次本地证据：报告 `runs/evidence/paired/deepseek-pilot-20261011-d/study.md`、原始证据 `runs/evidence/paired/deepseek-pilot-20261011-d/study.json`、盲评包 `runs/evidence/paired/deepseek-pilot-20261011-d/blind-review.json`。

- 任务：todo-app/002；1 次首次产出，4 条件共享。
- 请求模型：deepseek-chat；实际返回模型：deepseek-flash。
- temperature=0，每次代理最多 10 轮，单响应输出上限 2048，各重试条件最多 1 次。
- 首次实现通过可信测试与需求；四条件均 PASS，无重试，无复核警告。
- provider 实际返回的总用量为 9,052 tokens，共享首次调用只累计一次；本批次 usage_complete=true。
- 未提供经过独立审核的最终验收，也尚无真实双人标签。此次结果证明调用与证据链可运行，不能证明重试策略改善效果。

此前三份真实调试批次 a/b/c 因连接重置或证书链错误判 INVALID，保留在同目录。它们与成功批次合计已返回 14,892 tokens；中断请求可能另有用量，不能推导精确账单。增加有界传输重试和 usage_complete 标记；证书问题通过使用系统信任库解决，TLS 校验始终开启。密钥未写入项目、数据库或证据文件。

### 外部任务

真实数据本地文件：SWE-bench Lite 10 条 `reports/benchmarks/swebench-lite-10-20261011.json`。记录完整原始行、官方来源、实例 ID 和 sha256。选取源数据前 10 条，包含 gold/test_patch；正式生成补丁时应隔离这些答案字段。这不是随机或有代表性的外部样本。

官方评测预检本地文件：`reports/benchmarks/evaluations/swebench-lite-gold-preflight-20261011/evaluation.json`。当前 status=blocked，原因是 Docker CLI 和 swebench 包未安装，scores=null。没有运行真实外部仓库或生成外部成功率。Gold 模式是参考补丁环境校验，不能代表代理成绩。

接入依据：[HF Dataset Viewer](https://huggingface.co/docs/dataset-viewer/en/rows)、[SWE-bench 官方评测指南](https://www.swebench.com/SWE-bench/guides/evaluation/)。实际容器和已安装 harness 的版本兼容性仍需在可运行环境验收。

## 文件与使用

入口和命令见 [README](README.md)。主要实现分布在 core/workspace.py、core/artifacts.py、tools/executor.py、verifier/、feedback/loop.py、experiments/paired.py、experiments/swebench.py 和 report/。数据库默认改为 runs/vericoder_v2.sqlite；原有数据库与历史报告未覆盖。

代码已提供独立最终验收、两人盲评与分歧裁决入口，但不能代替实际审核者。正式研究仍需独立验收、真实代理多任务多次采样、预先固定预算与统计方案，以及 Docker 上的外部评测。当前本地后端不是安全沙箱；完成协议无法抵御任意恶意 Python 在同进程中篡改协议。
