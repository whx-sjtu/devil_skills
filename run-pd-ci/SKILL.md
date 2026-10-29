---
name: run-pd-ci
description: Run and monitor prefill/decode (PD) GPU performance experiments through remote CI, especially ROCm/ATOM GitHub Actions and Slurm with vLLM and MoRI. Analyze existing accuracy/performance evidence through read-only logs and artifacts.
---

# 远程 CI 运行 PD 分离实验

把确定的源码和实验配置送到远程 GPU，跟踪真实 P/D 工作负载，交付可复核的结果和清理状态。当前可直接使用的平台是 ROCm/ATOM 的 GitHub Actions → Slurm → P/D 容器；本地只需 Git、已认证的 `gh` 和适合 harness 的 Python 环境。

## CI 资源约束

用户于 2026-10-12 明确要求：**CI 只用于 GPU 性能测试；每批最多发起 2 个 workflow，两批至少间隔 1 小时。** 对该用户的远程 PD 工作持续遵守此约束；后续明确指令可更新它。

- CPU 测试、配置预检、日志分析在本地执行。状态查询和日志采集使用现有 run 的只读 API、artifact 或已授权的集群访问；不派发 inspection workflow，也不为队列、健康或清理检查新建 CI。
- 重试、取消后重提均计入批次数和时间间隔。跨分支、跨 PD 任务合并计算；记录最近派发时间和下一批最早时间。到时不自动重提，先确认已有实验和本次测试目的。
- GPU 性能实验可在同一 workload 内包含必要的启动与正确性验收；不单独派发 CPU inspection 或纯诊断 CI。先复用已有实验证据。
- 接续任务时检查后台监控是否会调用 `gh workflow run`。保留只读监控；停用自动 inspection 派发，并清理已确认属于本任务的多余排队 inspection。
- 节点默认由调度器在已约定的 runner/account/partition/QoS 范围内自动分配，只指定节点数和每节点 GPU 数。历史主机名用于结果记录，不作为新实验的提交名单；仅在用户明确要求固定节点时采用该要求。自动分配的输入、默认节点池和提交参数核验见[平台操作](references/atomesh.md#节点选择)。

## 1. 接续现有任务并固定实验范围

先区分新建实验、接续 run、只读结果查询。已有 run ID 时先检查它，避免重新派发。用户只要求解释、链接、整理 skill 或分析归档时，完成对应工作即可。

用户要求运行或复现实验，且资源与参数已约定时，继续准备并派发，无需再次索取同一授权。继承当前会话的源码、公共代码修改限制和资源范围；创建实验专用分支不等于获准更新上游 PR。报告默认保存在本地，外部评论和 dashboard 发布依用户指令处理。

在实验目录中记录最小 contract，缺失的值优先从用户指定的历史 run 与实际 matrix 恢复：

- harness 仓库/分支/SHA、vLLM 仓库/完整 SHA、集成前置补丁、实际镜像 digest。
- 模型与 draft、P/D 节点数及每节点 GPU 数、节点选择方式、TP/DCP、connector、READ/WRITE、graph mode、LMCache、量化与 speculative 配置；分配后补记实际节点和 P/D 角色。
- 实验目的：启动检查、精度、性能或 A/B；并发、输入/输出长度、时长、数据集/评测参数和验收条件。
- 已约定的 runner/account/partition/QoS、超时和结果目录。

只在缺失信息会改变实验含义或资源范围时澄清；准备不依赖答案的工作。历史 K3 参数见 [结果核验与历史基线](references/evidence.md)，它们不是所有 PD 实验的默认值。

## 2. 准备可复现的候选

使用 ATOM/Slurm 时先读 [平台操作](references/atomesh.md)，核对目标分支上的 workflow inputs 和执行链。同名 workflow 在诊断分支上可能是另一套接口。

固定远端可获取的源码 SHA，在隔离 worktree 中修改实验配置。区分原生源码编译安装与旧镜像源码 overlay；用实际 launcher 判断，核对编译扩展与源码来源。把集成前置补丁单独记下，避免把集成结果称为纯 main 或单个 PR 的结果。

复现与 A/B 保持无关变量一致，包括模型、镜像、量化、graph mode、采样方式和评测输入。检查最终 P/D argv 和展开后的 JSON；case 名称不代表实际生效配置。

**完成条件：** contract、源码和 harness 版本、输入 JSON 可审阅，能够说明本次相对基线只改变了什么。

## 3. CPU 预检后派发一次

用 harness 自带的 matrix builder 展开明确的 case；检查 cell 数、节点数、每节点 GPU 数、节点选择参数、P/D 参数、评测参数与 contract 一致。执行 `pd_submit.sh --dry-run`，确认不会提交 Slurm。只运行本次配置/源码改动所需的静态检查与 CPU 测试。

按既有授权把准备好的实验提交推送到任务分支，记录远端 SHA，然后通过 workflow 的结构化 JSON inputs 派发。保存派发前后的 run 列表和时间，用 workflow、branch、head SHA 与创建时间锁定唯一 run；不要直接取全仓最新 run。

派发响应超时或不明确时，先查询是否已经创建 run/Slurm job。确认没有创建后才重试；重复失败时保留证据并报告阻塞，避免制造重复 GPU 作业。已有作业单纯 PENDING 时继续监控，不以重复提交或切换账号/QoS解决排队。

**完成条件：** 唯一 run URL/ID 已记录，远端实际 matrix 已下载并与本地预检结果比较。

## 4. 跟踪到实验结束

按层观察 Actions、Slurm、P/D 服务就绪、传输、评测进度。Actions `in_progress` 只表示 workflow 在运行；Slurm `RUNNING` 也不能证明模型已就绪。

状态查询使用 `gh run view` / `gh run watch`；Slurm 日志从已有 artifact、已暴露的日志或已授权的集群访问读取。运行日志暂不可读时记录最后观察时间并等待现有 run 更新，不新建 CI 获取快照。

让长时间监控运行于可恢复的进程中，记录 PID/session 和日志位置；已有本次 run 的监控时复用。交互中使用短轮询并持续汇报阶段进展，避免一个长等待阻塞沟通。队列限额、模型加载慢、服务错误分别诊断。

自动分配可能选中存在机器问题的节点。若任务因节点故障失败（如 GPU/RDMA、磁盘或容器运行时故障），及时向用户报告 run 链接、Slurm job ID、实际故障节点及 P/D 角色、失败阶段、关键错误和证据路径，并说明性能数据是否有效、资源清理是否完成。证据不足时标为“疑似机器问题”，明确尚未确认的部分。后续重试仍遵守既有授权与 CI 频率限制，不能用静默换节点重试代替故障报告。

如需取消，精确定位本次任务的 run/job/container，并从已有退出日志、清理 artifact 或已授权的集群查询核对 Slurm 离队与容器清理。证据暂不可得时标为未核实；不为取消核验另开 CI。

## 5. 归档并判断结果

按 [结果核验](references/evidence.md) 检查实际源码、真实 PD 传输、评测样本/性能窗口与退出清理。

从最终 artifact 为每个 case/Slurm job 选取唯一 canonical 目录；快照、容器副本和最终归档不可重复计数。一次 run 的多个 case 分别出结论。

分别报告 **Actions conclusion、Slurm state/exit code、workload 结果、精度/性能是否达到 contract、清理状态**。分数生成后的 teardown 异常按时间线解释，保留原始失败状态；评测通过不等于所有层均正常。

**完成条件：** 每项约定结果均有对应证据，或明确标为失败/缺失；若作业仍活跃，交接准确的监控位置和下一步，而不是报告实验已完成。

## 6. 交付

用户需要看到：run 链接、实际测试版本和配置、核心结果、失败/不确定项、清理状态、证据目录。保留 contract、输入、本地/远端 matrix、run 元信息和最终归档，便于下一次接续。

声称“当前提交通过”必须有该版本的执行证据。只验证了等价方法或之前的集成版本时标明范围；eager 精度、FULL graph、性能、单 P/D 诊断分别表述。
