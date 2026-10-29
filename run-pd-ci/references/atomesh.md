# ROCm/ATOM → Slurm 操作

使用该平台准备、派发或监控实验时读取。基础平台细节核对于 2026-10-07，自动节点选择路径补核于 2026-10-13；每次以目标 harness SHA 的文件为准。

## 找到入口和源码加载方式

仓库为 `ROCm/ATOM`，workflow 通常为 `.github/workflows/atomesh-benchmark.yaml`。

| 文件 | 作用 |
| --- | --- |
| `.github/benchmark/models_atomesh.yaml` | 模型、case、源码、服务/评测配置及 YAML 继承 |
| `.github/scripts/atomesh/pd_matrix.py` | 展开最终 cell |
| `.github/scripts/atomesh/pd_submit.sh` | 导出 cell 参数、dry-run 或提交 Slurm |
| `.github/scripts/atomesh/pd_slurm_job.sh` | 节点分配、容器、阶段执行与清理 |
| `.github/scripts/atomesh/pd_server_atom.sh` | 根据 backend 选择服务 launcher |
| `.github/scripts/atomesh/pd_server_vllm.sh` | vLLM 安装与 P/D 启动 |

历史可复现 harness：[fd03f650a35c87eb2726b97aa6c9e44f4b6f33a9](https://github.com/ROCm/ATOM/tree/fd03f650a35c87eb2726b97aa6c9e44f4b6f33a9)。本工作区相应 checkout 是 `/app/k3-gsm8k-connector-zeroing-20261004`。目录不存在时从仓库获取指定 revision；skill 不依赖该本地目录才能运行。

这一版 K3 使用 `vllm.source.repo/sha`，在容器内创建独立 venv，从源码编译安装，并生成 `native-manifest-rank-*.json`。旧分支还保留 `vllm.fork` overlay 和 patches 路径；不要因为 launcher 里有 overlay 函数就认定当前 case 使用它。

检查 workflow 中的 node pool、账号映射、自动取消旧作业和容器预清理配置。历史 `ATOMESH_STALE_CELL_IDS` 是特定实验残留名单；新的实验只包含已确认归属本任务的目标。节点名称与账号能从旧 run 恢复，但空闲状态和当前授权不能从旧 run 推断。

## 节点选择

默认按节点数和每节点 GPU 数申请，由调度器选择实际主机。2026-10-13 用户确认，C48 [run 38312105401](https://github.com/ROCm/ATOM/actions/runs/38312105401) 的固定主机请求造成调度死锁；复现历史参数或做 A/B 时也应沿用自动分配，并在结果中记录实际分配。

对支持自动分配的 `atomesh-cicd` / TW→Spur 路径，核验完整链路：

1. workflow 节点 input 使用该版本支持的 `auto` 或空值；本地 matrix builder 使用 workflow 解析后的空值，不把字面量 `auto` 当作主机名传入。
2. 清空本地和远端实验 workflow 的 `ATOMESH_NODE_POOL`，并检查 case/YAML 继承和环境变量是否仍填入主机名单。只清空 input 或只改本地环境均不充分。
3. 展开的 cell 应为 `nodes: []`，`num_nodes` 和每节点 GPU 数按 contract 保留。历史版本曾把候选名单长度误当成申请节点数，须分别检查。
4. 检查实际提交命令构造路径，确认没有 `-w`、`--nodelist` 或等价的固定主机约束。已核对的 Spur helper 对非空候选池也会生成 `-w`，扩大名单不能代替移除约束。
5. 派发后比较远端 matrix，并从该次正式性能 run 的提交日志、分配元信息确认实际参数和节点。

其他 runner 先核对其接口：有些版本要求非空候选池，不能直接套用上述空值。区分平台要求的候选范围与强制主机名单，在已约定资源范围内选择受支持的调度方式。

## 准备 inputs 与本地 matrix

使用 `gh auth status` 确认已有认证即可；凭证通过现有 GitHub 配置提供，不写进 skill、inputs 或归档。选择已准备的 Python 环境；本工作区 harness 使用 `/app/.venv/bin/python`，vLLM CPU 测试使用 `/app/vllm-k3-native/.venv/bin/python`。

先从目标分支读取 `workflow_dispatch.inputs`。正式 PD 常用 inputs 如下；具体值由 contract 填入：

| input | 说明 |
| --- | --- |
| `suite` / `case_names` | 通常 `vllm`，明确选择一个或少量 case |
| `atomesh_slurm_submit_runner` | 已约定的提交 runner |
| `atomesh_slurm_account` / `atomesh_slurm_partition` | 配额与分区；检查最终 QoS 映射 |
| `atomesh_1p1d_nodes` / `atomesh_2p1d_nodes` / `atomesh_single_node` | 默认使用目标 workflow 支持的自动分配值；同时按[节点选择](#节点选择)检查默认池和最终提交参数 |
| `atomesh_image` | 固定 digest，并核对展开后的实际镜像 |
| `eval_concurrency` / `benchmark_concurrency` | 两种不同负载的并发 |
| `run_model_benchmark` | 该 workflow 的模型任务开关，纯精度 case 也可能需要 `true` |
| `publish_dashboard` | 独立实验通常为 `false` |

纯精度 case 是否跳过性能，继续检查 cell 的 `ATOMESH_EVAL_ONLY=1` 和 `run_eval`；不要仅由 `run_model_benchmark` 的名字判断。历史 K3 matrix 的性能并发是 16、评测并发是 64，且实际只运行评测。

将下面 `PD_*` 变量设为本次 contract 的实际值：`PD_HARNESS`、`PD_OUT`、`PD_PYTHON`、`PD_CASE`、`PD_IMAGE`、`PD_ACCOUNT`、`PD_PARTITION`、`PD_RUNNER`、`PD_EVAL_CONCURRENCY`。`PD_OUT` 用新的本地实验目录；所有命令在同一 shell 或显式传入相同环境执行。以下是支持自动分配的 `atomesh-cicd` 双节点示例，远端实验 workflow 也须清空默认池。

```bash
export ATOMESH_SLURM_ACCOUNT="$PD_ACCOUNT"
export ATOMESH_SLURM_PARTITION="$PD_PARTITION"
export ATOMESH_SLURM_SUBMIT_RUNNER="$PD_RUNNER"
export ATOMESH_SINGLE_NODE=auto
export ATOMESH_1P1D_NODES=""
export ATOMESH_2P1D_NODES=""
export ATOMESH_NODE_POOL=""
export ATOMESH_MODEL_ROOT=/mnt/models
export ATOMESH_LOG_ROOT=/it-share/ATOMESH_LOG/
export ATOMESH_PD_RANK_MAPPING_POLICY=none
export PD_OUT
mkdir -p "$PD_OUT"
cd "$PD_HARNESS"
"$PD_PYTHON" .github/scripts/atomesh/pd_matrix.py \
  --suite vllm --case "$PD_CASE" --image "$PD_IMAGE" \
  --eval-concurrency "$PD_EVAL_CONCURRENCY" \
  --output "$PD_OUT/matrix.json"
```

模型/log 路径与 rank mapping 也需匹配目标 runner，以上是历史平台路径。性能实验另外传入 `--benchmark-concurrency` 并检查 YAML 的 duration。

对自动分配双节点各八卡的单 case，可执行以下 CPU 检查；其他拓扑按 contract 修改数量和 P/D 参数断言：

```bash
"$PD_PYTHON" - <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

out = Path(os.environ['PD_OUT'])
cells = json.loads((out / 'matrix.json').read_text())['include']
assert len(cells) == 1
env = dict(os.environ)
env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env.get('PATH', '')
for cell in cells:
    assert cell['nodes'] == []
    assert cell['num_nodes'] == 2
    assert cell['runner']['gpus_per_node'] == 8
    for role in ('prefill', 'decode'):
        assert cell['service'][role]['tp'] == 8
        assert cell['service'][role]['dcp'] == 8
    subprocess.run([
        'bash', '.github/scripts/atomesh/pd_submit.sh',
        '--cell-json', json.dumps(cell), '--result-dir', str(out / 'dry-run'),
        '--dry-run',
    ], env=env, check=True)
PY
```

部分版本的 `pd_submit.sh --dry-run` 在构造 `sbatch` 命令前就退出，因此它不能单独证明主机约束已移除；还须检查实际命令构造函数及正式 run 日志。检查 source SHA、完整镜像地址、spec/量化 JSON、graph mode、LMCache 开关以及 accuracy 字段。当前 harness 可能将输入镜像转换为 backend 专用镜像，输入文本不等于运行镜像。

## 派发并锁定 run

代码和 inputs 准备好后，记录远端任务分支 HEAD。以下使用已推送的 `PD_REF`、已核对的 `PD_HARNESS_SHA`，inputs 保存在 `$PD_OUT/inputs.json`：

```bash
gh run list -R ROCm/ATOM --workflow atomesh-benchmark.yaml \
  --branch "$PD_REF" --limit 20 \
  --json databaseId,headSha,status,conclusion,createdAt,url \
  > "$PD_OUT/runs-before.json"
date -u '+%Y-%m-%dT%H:%M:%SZ' > "$PD_OUT/dispatched-at.txt"
gh workflow run atomesh-benchmark.yaml -R ROCm/ATOM \
  --ref "$PD_REF" --json < "$PD_OUT/inputs.json"
gh run list -R ROCm/ATOM --workflow atomesh-benchmark.yaml \
  --branch "$PD_REF" --limit 20 \
  --json databaseId,headSha,status,conclusion,createdAt,url \
  > "$PD_OUT/runs-after.json"
```

列表可能延迟，稍后重新查询而不是再次派发。按前后新增 ID、创建时间和 `headSha == PD_HARNESS_SHA` 确认；有多个候选时继续查元信息，不猜测。记录 `PD_RUN_ID` 与 attempt；重跑同一个 Actions run 时 attempt 的证据分目录保存。

```bash
gh run view "$PD_RUN_ID" -R ROCm/ATOM \
  --json databaseId,headBranch,headSha,status,conclusion,jobs,url
gh api "repos/ROCm/ATOM/actions/runs/$PD_RUN_ID" \
  --jq '{id,run_attempt,head_sha,status,conclusion,html_url}' \
  > "$PD_OUT/run-attempt.json"
gh run download "$PD_RUN_ID" -R ROCm/ATOM \
  --name atomesh-benchmark-matrix --dir "$PD_OUT/actual-matrix"
```

matrix artifact 尚未生成时继续跟踪 load-config job。生成后按 JSON 内容比较本地 `matrix.json` 与远端 `atomesh-matrix.json`；若差异影响实验含义，在成本继续增长前处理。多个 case 的并行度、workflow timeout、Slurm time limit 都从该 revision 检查，排队和源码编译也消耗时间预算。

## 运行中只读监控

遵守 SKILL.md 的 CI 资源约束。使用现有 run 查询状态，不派发 inspection workflow：

```bash
gh run view "$PD_RUN_ID" -R ROCm/ATOM \
  --json databaseId,headSha,status,conclusion,jobs,url
gh run watch "$PD_RUN_ID" -R ROCm/ATOM --interval 60
```

用可恢复的本地进程运行长期查询，记录 PID/session 与输出路径。已有 artifact 可通过 `gh run download` 读取；需要实时 Slurm 日志时，仅使用已授权的直接集群访问或该 run 已暴露的日志。缺少实时日志时保留最后观察时间，等待现有 run 上传，不用 CI 弥补观测缺口。

历史 `watch_ci_snapshots.py` 会自动派发 inspection workflow，不能作为默认监控使用。启动旧脚本前检查是否调用 `gh workflow run`；即使 inspection 不分配 GPU，也会占用 CI runner。已有 inspection 未完成时更不能循环新增。

已提交 `sbatch` 但响应不明确时，查询已有 Actions 日志、Slurm job-name/run token 或已授权的集群接口后再判断。`QOSGrpNodeLimit` 属于排队状态，不重提、不切换账号/QoS；任何必要重试仍受批次与频率约束。

## 最终归档与取消

终态时保存完整 Actions 状态、日志和 artifact；失败的 run 同样需要归档：

```bash
gh run view "$PD_RUN_ID" -R ROCm/ATOM \
  --json databaseId,headBranch,headSha,status,conclusion,createdAt,updatedAt,jobs,url \
  > "$PD_OUT/run.json"
gh api --paginate "repos/ROCm/ATOM/actions/runs/$PD_RUN_ID/artifacts?per_page=100" \
  --jq '.artifacts[] | {id,name,expired,created_at} | tojson' \
  > "$PD_OUT/artifacts.jsonl"
gh run download "$PD_RUN_ID" -R ROCm/ATOM \
  --pattern 'atomesh-*' --dir "$PD_OUT/artifacts"
gh run view "$PD_RUN_ID" -R ROCm/ATOM --log > "$PD_OUT/actions.log"
```

artifact 名称先从 inventory 确认；单 P/D probe 常为 `k3-*`，使用相应模式。下载失败保留缺失列表，仅在日志及必要 artifact 都成功后标记归档完成。已有文件时复用/检查，或下载至新的 attempt 目录。

本工作区旧 `/app/test_scripts/dspark_pd/archive_remote.sh RUN_ID 'atomesh-*'` 可后台等待并归档到 `remote-RUN_ID`，但固定了 repo 和目录；使用前检查是否已有监控。它的 `archived-at.txt` 只代表收集完成，结果仍看 `run.json` 和 workload 证据。

需要停止本次已确认归属的作业时使用 `gh run cancel "$PD_RUN_ID" -R ROCm/ATOM`，随后从已有退出/清理 artifact 或已授权的直接集群查询核对离队与容器退出。GitHub cancel 不是 GPU 资源已经释放的证明；证据缺失时明确标为未核实，不另开 inspection CI。
