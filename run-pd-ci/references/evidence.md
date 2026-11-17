# PD 实验证据与判定

准备 contract、分析运行结果、比较 A/B 或复现实验时读取。

## 一份结果对应一个版本和一个执行窗口

选取最终模型 artifact 内唯一的 `case-id/slurm_job-ID` 目录作为该 case 的 canonical 根目录。列出其中的 phase、rank 和 run token；同名文件存在于快照、容器副本、汇总 artifact 时只计 canonical 那一份。

| 要回答的问题 | 证据 |
| --- | --- |
| 实际执行了哪个版本？ | Actions head SHA、远端 matrix、各 rank 的安装 manifest、源码路径、镜像 digest、补丁列表/hash |
| P 和 D 真正分离运行了吗？ | 分配节点/角色、双方 argv 与 readiness、router 注册、请求及传输记录 |
| 请求确实使用了远端 KV 吗？ | external-token/load 数、READ/WRITE 提交与完成、P/D 请求关联、传输错误；HTTP 200 本身不够 |
| 评测是否覆盖目标？ | 实际 evaluator 命令、数据集及样本数、原始结果/样本、重试与错误、spec 计数器 |
| 作业与资源是否结束？ | Slurm 原始 state/exit code、rank rc、phase-complete、job-result、cleanup-complete、容器查询 rc 与列表 |

结果属于集成 SHA 时列出相对 PR/main 的前置修复。方法 AST 等价只能支持该方法范围的复用，不能把旧运行说成新提交的模型复测。单 P 模拟 ACK、单 D 本地生成可以用于诊断，但不提供真实 PD 传输证据。

## 精度

验收条件取自本次 contract，不能从工具默认 threshold 或旧实验继承。检查实际 few-shot、concurrency、limit、max generation、prompt/chat template、模型配置和数据集版本；与 YAML 比较只是其中一步。

从 canonical 原始样本重新计算正确数/总数，必要时记录样本 hash 和 strict/flexible 两种统计。按文件逐行读取 JSONL，避免 `str.splitlines()` 将样本文本中的 Unicode 分隔符误切成记录。跨 run A/B 核对题目 ID 与实际输入一致，再比较逐题变化；启动失败的组没有精度分数。

重试、错误和缺样单独统计。最终分数达到阈值但经历大量服务发现重试时，报告“精度通过、稳定性存在问题”。只有完整样本才可称全量评测完成。

有 speculative decoding 时，核对实际 `draft_sample_method` 与 `rejection_sample_method`。自然精度用真实拒绝采样；人为强制接受长度只用于明确约定的性能实验。使用同一 eval 窗口的 before/after counters，计算：

- token 接受率：`Δaccepted_tokens / Δdraft_tokens`。
- 每个 draft 位置的接受率；位置数来自实际 speculative 配置。
- 平均接受长度与 token 接受率不是同一指标，是否含 bonus token 需写清。

优先复用适用于当前 contract 的结果分析工具；没有合适工具时直接解析归档的 JSON/JSONL 和 metrics，不需要为了出分数重新运行模型。无 spec 实验不要求 draft 计数器。

## 性能

用独立 benchmark 窗口，核对服务端参数、并发、真实输入/输出长度分布、完整测量时长、warmup、正式请求成功/错误、结束排空与取消。报告吞吐、TTFT/ITL 的 mean/p90 及样本数。

保留 AIPerf 官方 observation denominator；配置时长或 `benchmark_duration.avg` 不能直接替代它。短 smoke 的吞吐不能作为稳态结论，GSM8K 运行时间也不是正式 serving benchmark。

A/B 记录每个 case 的实际主机、GPU 型号/数量和 P/D 角色映射。自动分配可能使各组落在不同机器上；把这一差异列为潜在混杂变量，按匹配的节点/角色分组比较，或用重复测量评估机器间波动。若证据不足以隔离机器差异，保留结果并限制归因，不把全部差异解释为模型配置收益。

使用性能汇总或比较工具前，核对其并发、时长、基线和完整性检查与本次 contract 一致，避免沿用硬编码的实验参数。

## 分层记录最终状态

保留五个独立结论：Actions、Slurm、workload、精度/性能验收、清理。workflow 可能根据 workload markers 对 Slurm 退出状态做 reconciliation；Actions 为 success 也可能同时存在 Slurm FAILED。

遇到退出错误，将结果写入、停止服务、首个异常的时间对齐到 UTC。只在证据支持时说异常发生于评测之后；时间先后不能单独证明底层失败原因，也不能删除失败状态。容器列表为空还需查询 rc=0；查询失败不是“无残留”。

交接报告包含：

1. run URL/ID/attempt、case、Slurm ID、节点、测试 SHA 和配置。
2. 每项 contract 的实测结果及证据路径。
3. 五层状态、错误/缺失证据、cleanup 和活跃监控位置。
4. 可复现所需的 inputs、matrix、manifests、日志/结果目录。

本地证据缺失时优先从对应 run 的 artifact 恢复。artifact 已过期则标明无法恢复的部分，保留已知版本/结果与其证据来源。
