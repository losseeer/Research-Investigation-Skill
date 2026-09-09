# Stage 2 — Search Planning

## 输入

`state.claims` + `state.search_budget.by_channel`（额度来自 state，不在此处写死）。

## 目标

为每个 Claim 生成**可记账、跨通道**的 query 列表，写进 `state.search_plans`。

这一阶段只产出 query，不执行检索。执行在 Stage 3，由 `scripts/search_academic.py` /
`search_github.py` 与内置 WebSearch / WebFetch 完成。

## 通道选择

| Claim type | 主通道 | 备选 |
|---|---|---|
| `scientific` | academic | web |
| `technical` | github, academic | web |
| `product` | product, web | github |
| `market` | web, product | — |
| `user_problem` | web | product |
| `application` | web, github | — |
| `novelty` | academic, github | product |

## query 写法（按通道）

| 通道 | 写法 | 例 |
|---|---|---|
| `academic` | **英文**、术语化、去修饰词；核心概念 + 同义/上下位词；不要整句 | `automated travel itinerary planning constraint` |
| `github` | 技术栈词（语言 / 框架 / 方法名），**不要问题描述** | `llm agent itinerary planning` |
| `web` | 自然语言问题式，可含中文 | `行程规划 App 支持行程中动态改行程吗` |
| `product` | 产品类别词 + 场景词 | `AI trip planner dynamic replanning app` |

同一 Claim 在不同通道的 query **必须是不同措辞**——同一个问题的学术叫法和工程叫法通常不一样，
照搬等于浪费一次 query 额度。

## 数量与额度

- `importance == high`：≥3 条，且**至少跨 2 个通道**（门禁会卡）。
- `importance == medium`：2–3 条。
- `importance == low`：0–1 条，预算紧张时跳过。
- 总量不超 `search_budget.by_channel` 中各通道的 `max_queries`。
- 分配顺序：先排满所有 high Claim，再排 medium。

## 禁止

- 单泛词：`AI`、`machine learning`、`recommendation`、`agent` 单独使用。
- 把 Idea 标题直接当 query。
- 同一通道内语义重复的 query。
- 没有 `claim_id` 归属的 query（无法判定它服务于哪个断言，也无法参与 saturation 计数）。

## 输出

写入 `state.search_plans`，结构见 `schemas/research-state.json`：

```json
[
  {"claim_id":"C3","queries":[
    {"id":"Q1","channel":"github","query":"llm agent itinerary planning","status":"pending"},
    {"id":"Q2","channel":"academic","query":"large language model travel itinerary planning","status":"pending"},
    {"id":"Q3","channel":"academic","query":"constraint-aware itinerary generation LLM","status":"pending"}
  ]}
]
```

- `id`：`Q1…Qn` **全局连续**，不重复（记账与去重按 id 追踪）。
- `status`：一律 `pending`，执行后再改。

## 示例

承接 `decompose.md` 的旅游行程 Idea，7 条 Claim 的一种分配：

| Claim | type | imp | 通道分配 |
|---|---|---|---|
| C1 突发事件导致改行程 | user_problem | high | web ×2, academic ×1 |
| C2 现有产品不支持动态重排 | product | high | product ×2, web ×1 |
| C3 已有 LLM 行程规划工作 | technical | high | github ×2, academic ×2 |
| C4 传统方法已能解决 | scientific | high | academic ×2, github ×1 |
| C5 已有商业化同类产品 | product | medium | product ×1, web ×1 |
| C6 用户愿付费 | market | medium | web ×1 |
| C7 LLM 与实时状态闭环 | novelty | high | github ×1, academic ×1, web ×1 |

合计 academic 6 / github 4 / web 6 / product 3 = 19 条，各通道均在额度内
（academic 12 / github 6 / web 8 / product 4；`check --stage 2` 会按通道校验计划条数）。

## 自检

- [ ] 每条 high Claim ≥3 条 query 且跨 ≥2 个通道？
- [ ] 各通道 query 数都没超 `max_queries`？
- [ ] 没有泛词、没有 Idea 标题原样照搬？
- [ ] 每个 query 都能说清它在验证哪条 Claim？
- [ ] `Q` 编号全局唯一且连续？

## 出口

```bash
python3 scripts/validate_state.py <state-dir> check --stage 2
```
