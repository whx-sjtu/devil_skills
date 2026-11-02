# 指标口径

InferenceX agentic 图的两个坐标，定义来自 InferenceX-app 的 `inferencex-api` skill（`references/agentic-interactivity.md`）和 view API 返回的 `xAxis`、`metric`：

| 轴 | 定义 |
|---|---|
| x：P90 interactivity（tok/s/user） | `1000 / P90(full_response_inter_token_latency, ms)` |
| y：Token Throughput per Chip（tok/s/chip） | (input + output) token 吞吐 ÷ 部署占用的全部芯片数 |

同一张图里的用户系列用同一种口径，并在 spec 的 `notes` 里写明。

## 交互性

- 先对每个请求的 full-response ITL 取 P90，再取倒数。median、P50、`p90_tpot`、每请求 `1/ITL` 的 P90 都不是这个量。
- aiperf 的 `inter_token_latency` 只按 content token 计时。vLLM 开 reasoning/tool parser 时，用它算出的交互性比 full-response 口径偏高（Kimi K3 C48–C88 实测约 1.5–3%）；ATOM 把所有 token 都作为 content 流出，两者相同。

从 aiperf 的 `profile_export.jsonl` 计算（只取无错误的 profiling 请求；字段值可能是 `{"value": ...}` 或数字）：

```python
import json

v = []
for line in open(path):
    r = json.loads(line)
    if r.get("error") or r["metadata"].get("benchmark_phase", "profiling") != "profiling":
        continue
    x = r["metrics"].get("full_response_inter_token_latency")
    if x is not None:
        v.append(x["value"] if isinstance(x, dict) else x)
v.sort()
k = (len(v) - 1) * 0.9  # numpy 默认的线性插值分位数
lo, hi = int(k), min(int(k) + 1, len(v) - 1)
interactivity = 1000 / (v[lo] + (v[hi] - v[lo]) * (k - lo))
```

## 吞吐

- 芯片数是 P 和 D 实例的全部 GPU，例如 1P1D、每侧 8 卡为 16。
- 分母有两种时间窗：
  - aiperf 官方的 `input_token_throughput + output_token_throughput` 以 benchmark 时钟为分母，包含结束时的 drain 尾巴。
  - 成功请求跨度：成功 profiling 请求的 (input + output) token 总数 ÷ (最晚的 `request_end_ns` − 最早的 `request_start_ns`)。
- ATOM summary 里的 “Total tok/s/GPU” 是跨度口径（K3 C72：跨度 16478.8，官方 15213.3），与 ATOM 数据对比时用跨度口径。
