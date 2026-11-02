---
name: infx-agentic-chart
description: Plot agentic token-throughput-per-chip vs. interactivity charts in the InferenceX dashboard style. Use when overlaying performance points on a model's official InferenceX agentic chart, or drawing an InferenceX-style agentic chart from several series of the user's own data.
---

# InferenceX 风格 agentic 图

把一组或几组“并发 → (吞吐, 交互性)”数据画成 InferenceX dashboard 的 agentic 图（浅色主题、Best per SKU 关闭）。配色、帕累托前沿、曲线插值和标签避让都从 InferenceX-app 前端源码移植到 `scripts/agentic_chart.py`；本流程负责整理数据、挑选系列和验图。

spec 里有没有 `official` 决定模式：

- **叠加官方图**：从 InferenceX 公开 view API 取指定模型的官方 agentic 系列，官方线的配色和样式与 dashboard 相同；用户数据画成加粗虚线叠在上面。
- **独立图**：只画用户的几组数据，实线，按硬件厂商套 InferenceX 配色。

需要装有 matplotlib 的 Python；叠加模式还要能访问 `inferencex.semianalysis.com`。

## 1. 整理 spec

每个点三项：`conc`（并发，图上标成 `C{conc}`）、`tput`（tok/s/chip）、`interactivity`（tok/s/user）。用户直接给出的数值原样使用；要从 benchmark 原始结果计算，或几份数据的口径可能不同时，先读[指标口径](references/metrics.md)。

```json
{
  "official": {"model": "Kimi-K3", "series": ["gb300_dynamo-vllm", "mi355x_atom"]},
  "sources": ["ROCm/ATOM atomesh-benchmark CI"],
  "notes": ["vllm optimized mooncake: 1P1D, 16 chips, best config per concurrency"],
  "series": [
    {"hw": "MI355X", "engine": "ATOM PD", "baseline": true,
     "points": [{"conc": 1, "tput": 912.0, "interactivity": 164.0}]},
    {"hw": "MI355X", "engine": "vllm optimized mooncake", "highlight": true,
     "points": [{"conc": 1, "tput": 985.84, "interactivity": 181.47}]}
  ]
}
```

完整的真实例子见 [examples/kimi-k3-mooncake.json](examples/kimi-k3-mooncake.json)。

- `official`：只在叠加模式写。`model` 可以是 InferenceX 模型名、页面 URL 里的 slug（`kimi-k3`）或 db key。`series` 是保留的官方系列 hwKey，用 `--list MODEL` 查；用户点名的硬件和引擎按 label 对应到 hwKey。用户没点名时只选与对比相关的系列（基线和直接竞品，一般不超过 6 条），全部画上会让标签互相重叠。官方配色只在保留的系列之间分配，和 dashboard 只勾选这些系列时一致。
- `series[]`：`hw` 和 `engine` 拼成标签 `HW (engine)`。`hw` 用 dashboard 的写法（`MI355X`、`GB300 NVL72`），独立模式据此套厂商配色。
  - `highlight`（至多一条）：要突出的系列，通常是“我们的优化”。菱形点，点标签优先摆放，其他标签避开它的线；叠加模式下默认红色。
  - `baseline`（至多一条）：对照系列。面板给出 highlight 相对它在相同并发下的吞吐和交互性比值范围；同并发的这一对点只在 highlight 上标一次。
  - 可选 `color`、`style`（`dashed` 或 `solid`；叠加模式默认 `dashed`，独立模式默认 `solid`）。
- 可选顶层字段：`title`、`subtitle`（默认由模型、硬件、精度和 `sources` 生成）、`notes`（右侧面板说明，每条一段，自动折行）、`precision`（独立模式的副标题用）、`percentile`（默认 `p90`）。

## 2. 出图

```bash
python scripts/agentic_chart.py --list            # InferenceX 模型
python scripts/agentic_chart.py --list kimi-k3    # 该模型官方系列的 hwKey、label、点数和日期
python scripts/agentic_chart.py spec.json -o out/kimi-k3-agentic
```

输出 `<out>.png`（2480×1440）和 `<out>.svg`。叠加模式首次运行会把 API 响应连同 URL 和抓取时间存为 `<out>.view.json`；之后重画、调布局都加 `--view <out>.view.json`，让官方数据固定在同一快照。用户要最新的官方数据时去掉 `--view` 重新抓取，并说明抓取时间变了。

脚本报错和警告的处理：

- `frontier mismatch`：InferenceX 的前沿算法和移植版不一致，画出的官方线会和 dashboard 不同。停下来报告。
- `line labels overlap`、`side panel text shrunk`：系列或说明太多。减少官方系列或精简 `notes` 后重画。
- `bad points`、`duplicate series`、`more than one highlight`：修 spec。

## 3. 看图

读 PNG，再把数据密集区和右侧面板裁剪放大，逐项检查：

- highlight 和 baseline 的每个点都有归属清楚的 `C` 标签。脚本打印的 `point labels shown a/b` 里，其他系列的标签因避让被隐藏是正常的。
- 线标签（pill）没有压住 highlight 的点。
- 面板文字在框内、互不重叠；比值范围与输入数据手算一致。

布局问题先通过 spec 解决（换官方系列、highlight/baseline、`notes`）。布局算法逐条对应 InferenceX 的 `line-label-layer.ts`，要改先确认 dashboard 的行为。

**完成条件**：脚本没有报错和警告，PNG 已查看，上面三项都满足。

## 4. 交付

告诉用户：PNG/SVG 路径；官方数据的 API URL、抓取时间和每条官方系列的 run（都在 `<out>.view.json` 和面板里）；每条用户系列的数据来源，以及没能核对的数据点。
