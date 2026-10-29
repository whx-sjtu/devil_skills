# PD 实验证据与判定

准备 contract、分析运行结果、比较 A/B 或复现历史 K3 实验时读取。

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

本工作区可选工具（先检查其实现对当前实验的适用性）：

```bash
"$PD_PYTHON" /app/test_scripts/dspark_pd/validation/summarize_gsm8k_ci.py \
  "$PD_CANONICAL" --threshold "$PD_THRESHOLD" \
  --draft-positions "$PD_DRAFT_POSITIONS" --require-pass
"$PD_PYTHON" /app/test_scripts/dspark_pd/validation/spec_acceptance.py \
  "$PD_METRICS_BEFORE" "$PD_METRICS_AFTER"
```

这些工具缺失时直接解析对应结果 JSON/JSONL 和 metrics；不需要为了出分数重新运行模型。工具可能含 K3 的固定参数校验，其他模型需按 contract 判断。无 spec 实验不要求 draft 计数器。

## 性能

用独立 benchmark 窗口，核对服务端参数、并发、真实输入/输出长度分布、完整测量时长、warmup、正式请求成功/错误、结束排空与取消。报告吞吐、TTFT/ITL 的 mean/p90 及样本数。

保留 AIPerf 官方 observation denominator；配置时长或 `benchmark_duration.avg` 不能直接替代它。短 smoke 的吞吐不能作为稳态结论，GSM8K 运行时间也不是正式 serving benchmark。

A/B 记录每个 case 的实际主机、GPU 型号/数量和 P/D 角色映射。自动分配可能使各组落在不同机器上；把这一差异列为潜在混杂变量，按匹配的节点/角色分组比较，或用重复测量评估机器间波动。若证据不足以隔离机器差异，保留结果并限制归因，不把全部差异解释为模型配置收益。

本工作区工具为 `validation/summarize_pd_benchmark.py ROOT --concurrency N --duration SECONDS --require-complete`。旧 `compare_pd_performance.py` 曾硬编码 C64、3600 秒和历史 reference run；先核对实现，不能仅更换 `--reference` 就当成通用比较器。

## 分层记录最终状态

保留五个独立结论：Actions、Slurm、workload、精度/性能验收、清理。workflow 可能根据 workload markers 对 Slurm 退出状态做 reconciliation；Actions 为 success 也可能同时存在 Slurm FAILED。

遇到退出错误，将结果写入、停止服务、首个异常的时间对齐到 UTC。只在证据支持时说异常发生于评测之后；时间先后不能单独证明底层失败原因，也不能删除失败状态。容器列表为空还需查询 rc=0；查询失败不是“无残留”。

交接报告包含：

1. run URL/ID/attempt、case、Slurm ID、节点、测试 SHA 和配置。
2. 每项 contract 的实测结果及证据路径。
3. 五层状态、错误/缺失证据、cleanup 和活跃监控位置。
4. 可复现所需的 inputs、matrix、manifests、日志/结果目录。

## 历史 K3 基线：用于复现，不作为通用默认值

[Run 37203257111](https://github.com/ROCm/ATOM/actions/runs/37203257111)，2026-10-04，Slurm `5423`：

| 项目 | 已记录值 |
| --- | --- |
| Harness | `ROCm/ATOM`，`whx/k3-gsm8k-connector-zeroing-20261004`，`fd03f650a35c87eb2726b97aa6c9e44f4b6f33a9` |
| vLLM 集成 | `whx-sjtu/vllm`，`34735d6776b9c43086fdf5c6c6392d9de45f322f` |
| Case | `kimi-k3-gsm8k-connector-zeroing-dspark3-tp8-dcp8-eager` |
| 模型 | `/mnt/models/moonshotai/Kimi-K3`；draft `/mnt/models/Inferact/Kimi-K3-DSpark` |
| 拓扑 | P8/D8，双方 TP8/DCP8，MoRI READ，eager，无 LMCache，自然 DSpark3 |
| 实际模型镜像 | `vllm/vllm-openai-rocm:nightly@sha256:659b28319fef4ea0e3d8f33e25b4c35d6f663f5d818a5b2fa06dceaf859234e4` |
| 实际 router 镜像 | `vllm/vllm-router:nightly-20260912-83944c4@sha256:ac68315ab8642c253571316a7ac377df51794665e5c20fb95e7b84b40f9021e3` |
| 历史资源与实际分配 | runner `atomesh-cicd`；account `amd-frameworks`；partition `amd-spur`；QoS `amd-frameworks-qos`；实际为 g13/g25 两节点，主机名仅作历史记录 |
| 精度 contract | 全量 GSM8K 1319 题，5-shot，C64，max_gen_toks=4096，无 limit；阈值 0.94 |
| 实测 | strict/flexible 均 1268/1319 = 96.1334%；P/D 各 1319 HTTP 200，无 evaluator 重试 |
| 自然接受率 | 96858/126675 = 76.4618%，三个 draft 位置均为正 |
| Actions | `completed / success` |
| Slurm / workload | `FAILED / 1:0`；workload `COMPLETED`，reconciled result rc=0 |
| 清理 | 双端 rank rc=0，cleanup 完成，容器查询 rc=0 且列表为空 |

该 harness `accuracy.threshold=0.0` 用于收集结果，独立验收仍要求 0.94。性能字段存在于 matrix，但 `ATOMESH_EVAL_ONLY=1`，所以这次不能提供正式性能结论。

评测结果时间为 13:46:18 UTC，P shutdown 为 13:46:22，P output-handler `EngineDeadError` 为 13:46:34。准确表述是“Actions 成功，模型精度通过且 workload/清理完成，保留 Slurm 失败和 teardown 异常”；不是 Actions 失败，也不是所有层都无异常。

集成还含 K3 grouping、TCP listener 和 discovery heartbeat 前置修复。这个结果属于上述集成及当时的 connector 实现，不能自动覆盖后续 PR 提交、FULL graph、WRITE 或性能配置。

本工作区原始证据入口：

- `/app/test_scripts/dspark_pd/remote-37203257111/`：Actions 元信息和最终 artifact。
- `/app/test_scripts/dspark_pd/native-migration/pr59164-connector-zeroing-20261004/`：`inputs.json`、本地及远端 matrix、源码前置补丁。
- `/app/test_scripts/dspark_pd/native-migration/pr59164-review-20261006/model-review.json`：独立重算、canonical 目录和时序。

这些文件不存在时优先从 run artifact 恢复。artifact 已过期则标明无法恢复的部分，保留已知版本/结果与其证据来源。
