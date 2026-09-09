# Idea Research Report

> Idea：{{ idea.title }}
> Domain：{{ idea.domain }} · 生成时间：{{ generated_at }}
> 状态：{{ status }} · 检索：{{ used_queries }}/{{ max_queries }} query · {{ evidence_count }} 条 Evidence

---

## 1. Executive Summary

3–5 句话说清：这个 Idea 想解决什么、有没有人做过、核心假设站不站得住、最终建议是什么。

**Recommendation：`{{ recommendation.verdict }}`**
（基于 Claim {{ recommendation.based_on_claim_ids }}）

---

## 2. Idea Reconstruction

把原始描述重述成结构化形式：要解决的问题、目标用户、 proposed approach、隐含前提。
明确指出哪些是用户说的、哪些是本报告补出来的假设。

---

## 3. Core Claims

| ID | Claim | Type | Importance | Status | Confidence | Evidence |
|---|---|---|---|---|---|---|
| C1 | … | user_problem | high | insufficient_evidence | 0.0 | — |
| C3 | … | technical | high | supported | 0.8 | E1, E2, E3, E5 |

未裁决即 `insufficient_evidence` 的 Claim 逐条说明**为什么没查到**（引 `evidence_gaps`），
不得写成「不存在此类工作」。

---

## 4. Existing Academic Work

按主题分组综述学术工作：已有方法、效果如何、近年趋势。
每条结论后附 `（E{n}）`。

---

## 5. Prior Art Analysis

比较矩阵（行 = prior art，列 = problem / method / system / evaluation）：

| ID | Prior Art | Kind | problem | method | system | evaluation | 总体 |
|---|---|---|---|---|---|---|---|
| P1 | … | academic | highly_similar | partially_overlapping | adjacent | adjacent | highly_similar |

每条 prior art 用一段说明它**与本 Idea 的具体差异**（引 `difference`）。

---

## 6. Scientific Support

核心假设有没有学术支持：支持它的研究是什么、效果量级如何、有没有相反结论。
区分「有论文」和「论文里验证了」——前者只是 `paper`，后者才是有效支持。

---

## 7. Existing Products

已有产品 / 开源实现做到什么程度。严格按 `implementation_level` 陈述：

| 名称 | implementation_level | 判断依据 |
|---|---|---|
| … | code | 有仓库，无部署证据（E5） |

`code` 不能写成「已有成熟产品」，`production` 与 `commercial_product` 需要额外证据。

---

## 8. Motivation & Application Value

- Problem：{{ analysis.motivation.problem }}
- Who cares：{{ analysis.motivation.who_cares }}
- Value：{{ analysis.motivation.value }}
- Assessment：**{{ analysis.motivation.assessment }}**

Assessment 必须来自对应 Claim 的裁决，不是来自「技术是否可行」。

---

## 9. Technical Bottlenecks

| ID | Bottleneck | Type | Severity | Evidence |
|---|---|---|---|---|
| B1 | … | engineering | high | — |
| B2 | … | research | high | E1 |

结论：**这个 Idea 主要是{{ engineering / research / fundamental }}问题**。
（取 `severity == high` 的瓶颈里类型最严重的一档：`fundamental > research > engineering`）

---

## 10. Novelty Analysis

Level：**{{ analysis.novelty.level }}**（基于 prior art {{ analysis.novelty.based_on_prior_art_ids }}）

Because：{{ analysis.novelty.because }}

---

## 11. Risks

1. **覆盖缺口**（必填）：列出 `unavailable_channels` 与未执行的检索方向。
   例如「arXiv 直连 API 返回 429，改用 OpenAlex 覆盖预印本；product 通道未调用」。
2. 证据风险：核心 Claim 只靠单一来源、证据强度偏低、有相反结论。
3. 执行风险：来自 §9 的 `research` / `fundamental` 类瓶颈。
4. 判断不确定处：哪些结论是推断而非证据直接支持。

---

## 12. Recommendation

**{{ recommendation.verdict }}**

Rationale：{{ recommendation.rationale }}
（基于 Claim {{ recommendation.based_on_claim_ids }}）

若 `MODIFY` / `PIVOT`，列出 `conditions`——改什么、或转向哪个相邻机会。

---

## 13. Suggested Next Steps

按「先补哪条证据」排序，每条写清：要验证哪个 Claim、走哪个通道、预期得到什么。
优先补 `importance == high` 且 `insufficient_evidence` 的 Claim。

---

## 14. Evidence

| ID | Source Type | Implementation Level | Strength | Relevance | Title / URL |
|---|---|---|---|---|---|
| E1 | academic | paper | high | 0.9 | […](…) |

只列 `relevance >= 0.6` 的条目。低于阈值的证据不进报告。
