---
name: research-investigation
description: "Investigate an academic, technical or product idea: decompose it into Claims, gather academic / code / web / product Evidence, verify each Claim, analyse Prior Art and Novelty, then issue a DO / MODIFY / PIVOT / DON'T_DO / INSUFFICIENT_EVIDENCE recommendation in a fully source-traceable report. Use when the user asks 这个 idea 有没有人做过 / 值得做吗 / 创新点在哪 / 帮我调研一下这个方向, or otherwise wants a novelty, prior-art or feasibility judgement. Do NOT use for plain topic summarisation or literature digests — that is web-research-summarizer."
agent_created: true
---

# Research Investigation

## Overview

```text
Idea → Claims → Search → Evidence → Claim Verification
     → Prior Art → Novelty / Feasibility → Recommendation
```

判断只能由 Claim 的裁决结果聚合而来。**不允许对 Idea 直接下结论**，也不允许「搜索 → 摘要」式输出。

## When To Use

- 用户要判断一个 idea 是否值得做、是否已有类似工作、创新点在哪。
- 需要 Novelty / Prior Art / 可行性判断，且结论要能回溯到来源。
- 用户主动要求「按 Claim + Evidence 的方式调研」。

**Do NOT use：**

- 只是要某个主题的资料汇总 / 文献摘要 → `web-research-summarizer`。
- 单个已知 URL 的阅读 → 直接 WebFetch。
- 用户已决定要做，只要实现方案 → 直接给方案。

## Input / Output

**Input**：Idea 文本（一句话到一段落）。可选：领域、必须排除的方向、时间范围、预算覆盖。

**Output**（全部落在当前项目目录，不依赖平台状态机制）：

```text
research/<idea-slug>/
├── research-state.json     # claims / judgments / prior_art / analysis / budget / unavailable_channels
├── evidence.jsonl          # append-only，一行一条 Evidence
└── report.md               # 14 节报告，见 assets/report-template.md
```

## Stage Index

| Stage | 做什么 | 读 | 退出校验 |
|---|---|---|---|
| 0 Init | 初始化 state、派生 `idea-slug` | `assets/research-state.template.json` | state 可创建 |
| 1 Decompose | Idea → 原子 Claim | `prompts/decompose.md` | ≥5 条 Claim，覆盖 ≥3 种 type |
| 2 Search Planning | 每 Claim 生成多通道 query | `prompts/search-planning.md` | 每条 high Claim ≥3 条跨通道 query |
| 3 Search | 取回结果 → 归一化 Evidence | `scripts/search_academic.py`、`scripts/search_github.py`、内置 WebSearch / WebFetch；`prompts/evidence-normalization.md` | 无非法 Evidence；URL 已去重 |
| 4 Verification | Claim → Evidence → Judgment | `prompts/claim-verification.md` | 每条 Claim 有 status；无证据者 `insufficient_evidence` |
| 5 Analysis | Prior Art + Bottleneck + Novelty | `prompts/prior-art-analysis.md`、`prompts/feasibility-analysis.md` | 有比较矩阵、bottleneck 分类、Novelty 档位 + because |
| 6 Report | 仅基于 state 生成报告 | `prompts/report-synthesis.md`、`assets/report-template.md` | 每条结论带 Claim ID / Evidence ID |

每个 Stage 出口执行：

```bash
python3 scripts/validate_state.py check --stage <N> research/<idea-slug>
```

校验不通过则停在当前 Stage（不进入下一 Stage）。

## CLI 速查（argparse 子命令在前，路径在后）

`<dir>` 是位置参数，**必须写在子命令之后**——写成 `<dir> <子命令>` 会直接报
`invalid choice`。各子命令签名：

```bash
init --idea '...' [--domain D] [--root R]     # dir 由 --root + slug 推导
check [--stage N] [--json] <dir>
budget <dir>
saturation <dir>
consume <dir> --channel <ch> --queries N --results N --iterations N
finalize <dir> --reason "..."
merge <dir> --data '{...}'
set-evidence <dir> <E-id> --data '{...}'      # 注意：E-id 在 dir 之后，不是之前
```

`consume` 两个坑：① 累加会**溢出即 FATAL 并拒绝落盘**（如 github 已 5/6 再 `--queries 5` 直接失败），
单次调用请勿超过剩余额度；② `--iterations` 每次调用都会累加，一批 consume 只应有一个带 `--iterations`。

## Search Capabilities

只暴露四个抽象能力名，具体端点收在 `references/sources.md`：

```text
academic_search   # OpenAlex / Crossref / arXiv
github_search     # GitHub Search API
web_search        # 内置 WebSearch + WebFetch
product_search    # WebSearch (Product-Lite) + agent-browser 兜底
```

网络：脚本内建回退链 `env proxy → 127.0.0.1:7897 → 标记该通道 unavailable`，不得假定默认代理可用。

环境变量：`RESEARCH_MAILTO`（**OpenAlex 必填**，否则稳定 429）、`GITHUB_TOKEN`（可选，自动把 github 通道额度提到 20 query）。

脚本产出的 `relevance` 一律是 `0.5`，必须经 Stage 3b 归一化校准，否则报告阶段会因
`relevance < 0.6` 丢弃全部条目。写回：

```bash
python3 scripts/validate_state.py set-evidence <state-dir> E1 --data '{"relevance":0.9}'
```

## Budget

| 通道 | max_queries | max_results |
|---|---|---|
| `academic_search` (OpenAlex + Crossref) | 8 | 50 |
| `academic_search` (arXiv) | 4 | 30 |
| `github_search` | 6（有 `GITHUB_TOKEN` 时 20） | 30 |
| `web_search` | 8 | 30 |
| `product_search` | 4 | 20 |

全局：`max_iterations: 8`、`max_queries: 30`。

## Stop Rules

**硬停止**：任一通道 query 达上限，或 `max_iterations` 达 8。

**Evidence Saturation**（满足任一即停该 Claim 方向）：

1. 已有 ≥3 条独立证据（不同 `source_type` 或不同作者 / 组织）。
2. 连续 2 轮 `changes_judgment == true` 的新增 Evidence 为 0。
3. 新增结果与已有结果归一化后重复率 > 60%。
4. 主要 prior art 与技术路线已覆盖。

**收口**：所有 `importance == high` 的 Claim 均已裁决 → 进入 Stage 5。

完整循环与 Action 记法见 `workflows/investigation.md`。

## Hard Rules

1. 每个结论必须可回溯 `Claim → Evidence → Source`。
2. 证据不足一律 `insufficient_evidence`，**禁止推导「没搜到 ⇒ 不存在」**。
3. 通道失败写入 `unavailable_channels[]`，并在报告 §11 Risks 声明覆盖缺口。
4. `implementation_level` 逐级举证：`idea → paper → code → prototype → production → commercial_product`。论文存在 ≠ 有代码，有代码 ≠ 有产品，有产品 ≠ 已验证市场价值。
5. Report 只由 `research-state.json` + `evidence.jsonl` 生成，不引入上下文中的临时信息。
6. Evidence 全文不进上下文，只写 `evidence.jsonl`；单轮迭代最多 10 条摘要进入上下文。

## Resources

### prompts/
- `decompose.md` — Idea → 原子 Claim
- `search-planning.md` — 多通道 query 生成
- `evidence-normalization.md` — 结果 → Evidence（含 strength / implementation_level 判定口径）
- `claim-verification.md` — Claim → Judgment
- `prior-art-analysis.md` — 比较矩阵 + 相似度五档
- `feasibility-analysis.md` — Motivation + Bottleneck + Novelty
- `report-synthesis.md` — 仅基于 state 生成报告

### workflows/
- `investigation.md` — Action 记法 + 主循环 + 停止条件

### references/
- `sources.md` — 通道配置：抽象能力名 ↔ 端点 / 限额 / 回退链

### assets/
- `research-state.template.json` — state 初始模板
- `report-template.md` — 14 节报告骨架

### scripts/
- `search_academic.py` — OpenAlex + Crossref（+arXiv）
- `search_github.py` — GitHub Search API
- `validate_state.py` — state 唯一读写入口：init / check（stage 门禁）/ budget / saturation / consume / set-evidence / **merge（Stage 4–6 写回）**
- `_common.py` — 网络层（代理回退 + 429 退避），被上面三个脚本共用

### schemas/
- `claim.json` / `evidence.json` / `judgment.json` / `prior-art.json` / `research-state.json`
