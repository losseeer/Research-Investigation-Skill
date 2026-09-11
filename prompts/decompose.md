# Stage 1 — Claim Decomposition

## 输入

`idea.raw`（用户原始描述）+ 可选 `idea.domain` / `idea.constraints`。

## 目标

把 Idea 拆成一组**能被外部证据支持或反驳**的原子断言（Claim）。

后续所有判断都由这些 Claim 的裁决聚合而来。这一步拆得不好，后面检索再多也是噪声——
一个无法证伪的 Claim 会让对应方向的检索预算 100% 浪费。

## 合格标准

一条合格的 Claim：

- 是陈述句，有真假。
- 不依赖 Idea 本身成立（不能用 Idea 的结论去证明它的前提）。
- 至少存在一个通道（`academic` / `github` / `web` / `product`）能找到支持或反驳它的证据。
- 一条只说一件事。

直接丢弃的写法：

| 反例 | 问题 |
|---|---|
| 「做一个基于 LLM 的旅游行程规划系统」 | Idea 复述，不是断言 |
| 「这个方向很有价值 / 用户体验会更好」 | 无法证伪 |
| 「突发事件会导致行程失效且用户需要重新规划」 | 两个断言，拆开 |
| 「因为现有产品不够智能，所以我们需要 Agent 方案」 | motivation 混入，motivation 留到 analysis |

## 覆盖要求

- 数量 **5–10 条**。
- `type` **至少覆盖 3 种**。
- `importance == high` **至少 2 条**。

### type 与典型证据通道

| type | 问的是什么 | 主通道 |
|---|---|---|
| `scientific` | 底层机制 / 效果是否有研究支持 | academic |
| `technical` | 技术上能否实现、是否已有人实现 | github / academic |
| `product` | 是否已有同类产品、做到什么程度 | product / web |
| `market` | 是否有人买单、规模如何 | web / product |
| `user_problem` | 用户是否真有这个痛点 | web |
| `application` | 落地场景是否成立 | web / github |
| `novelty` | 与已有工作的差别在哪 | academic / github |

### importance 怎么定

- **high**：直接决定最终 Recommendation。被反驳 → 整个 Idea 不成立。
- **medium**：影响可行性或差异化，但不决定成败。
- **low**：背景性、加分项。预算紧张时可跳过检索。

## 输出

严格按 `schemas/claim.json` 输出 JSON 数组，写入 `state.claims`：

- `id`：`C1`、`C2` … 连续编号。
- `status`：一律 `unknown`。
- `confidence`：一律 `0.0`。
- `evidence_ids`：空数组（Stage 3 之后才填）。
- `search_queries`：留空，由 Stage 2 生成。

不要在这一步预填任何证据或结论。

## 示例

Idea：**用 LLM Agent 自动做旅游行程动态规划**

```json
[
  {"id":"C1","statement":"旅行者在实际行程中确实会因天气、闭馆、交通延误等突发事件调整计划",
   "type":"user_problem","importance":"high","status":"unknown","confidence":0.0,
   "evidence_ids":[],"search_queries":[]},

  {"id":"C2","statement":"现有主流行程规划产品不支持行程开始后的动态重排",
   "type":"product","importance":"high","status":"unknown","confidence":0.0,
   "evidence_ids":[],"search_queries":[]},

  {"id":"C3","statement":"已有研究把 LLM Agent 用于带约束的行程规划（itinerary planning）",
   "type":"technical","importance":"high","status":"unknown","confidence":0.0,
   "evidence_ids":[],"search_queries":[]},

  {"id":"C4","statement":"约束满足或运筹方法已能解决行程规划问题，无需引入 LLM",
   "type":"scientific","importance":"high","status":"unknown","confidence":0.0,
   "evidence_ids":[],"search_queries":[]},

  {"id":"C5","statement":"存在面向 C 端、以动态行程调整为卖点的商业化产品",
   "type":"product","importance":"medium","status":"unknown","confidence":0.0,
   "evidence_ids":[],"search_queries":[]},

  {"id":"C6","statement":"用户愿意为自动行程规划付费",
   "type":"market","importance":"medium","status":"unknown","confidence":0.0,
   "evidence_ids":[],"search_queries":[]},

  {"id":"C7","statement":"已有工作把 LLM 规划能力与实时外部状态（天气/交通/营业时间）闭环结合",
   "type":"novelty","importance":"high","status":"unknown","confidence":0.0,
   "evidence_ids":[],"search_queries":[]}
]
```

注：C4 是刻意的反向 Claim——它若被支持，Idea 的技术前提就不成立。每个 Idea 至少要留一条这样的 Claim。

## 自检

- [ ] 每条都能被外部证据证伪？
- [ ] 数量 5–10、`type` ≥3 种、`high` ≥2 条？
- [ ] 有没有把 Idea 复述成一条 Claim？
- [ ] 有没有混入 motivation？
- [ ] 有没有至少一条「若成立则 Idea 不成立」的反向 Claim？

## 出口

```bash
python3 scripts/validate_state.py check <state-dir> --stage 1
```
