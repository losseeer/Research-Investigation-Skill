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

| ID | Claim | Type | Importance | Status | Confidence | Time | Evidence |
|---|---|---|---|---|---|---|---|
| C1 | … | user_problem | high | insufficient_evidence | 0.0 | timeless | — |
| C3 | … | technical | high | supported | 0.8 | evolving | E1, E2, E3, E5 |

`Time` = Claim 的 `time_sensitivity`：`evolving` 的成立依赖时间，`timeless` 不依赖。详见 §11。

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

## 11. Time Coverage

> as_of：**{{ time_policy.as_of }}** · 近年窗口：**{{ time_policy.recency_window_years }} 年**（窗口内 = 出版年份 ≥ {{ cutoff_year }}）
> 证据取回区间：**{{ retrieved_span }}**（`retrieved_at` 最早 ~ 最新；距 as_of 超 180 天属旧快照，见下）

「旧证据支撑现状断言」是时效性最典型的静默失效，必须显式交代：

| Claim | Sensitivity | 窗口内证据 | 最新证据年份 | 说明 |
|---|---|---|---|---|
| C3 | evolving | 2 | 2025 | 由 2025 复评支撑，结论未过时 |
| C1 | timeless | n/a | 2019 | 机制性事实，不要求近年证据 |

写作约束：

- `evolving` 且裁决为 `supported` / `partially_supported` 的 Claim **必须有至少一条窗口内证据**。
  不满足时 `check` 直接报错（不会放行到下一阶段），提示补近年检索 / 改标 `timeless` / 下调裁决。
- 标 `timeless` 必须写出理由（理论性质、上下界、已确立的机制性事实），写在 Claim 的 `notes` 里。
  「懒得补检索」不是 `timeless`。
- 报告里出现「目前 / 现在 / 已能 / 仍是」这类现状措辞时，对应 Claim 必须是 `evolving` 且有窗口内证据。
- 取回区间偏旧（最早一条距 `as_of` > 180 天）时，在本节写明「结论基于 X 年的快照」，
  并在 §12 时效缺口里列出需要重核的 Claim。`publication_year` 说的是内容时点，`retrieved_at` 说的是抓取时点，
  两者都新才算可靠。

---

## 12. Risks

1. **覆盖缺口**（必填）：列出 `unavailable_channels` 与未执行的检索方向。
   例如「arXiv 直连 API 返回 429，改用 OpenAlex 覆盖预印本；product 通道未调用」。
2. **时效缺口**（必填）：`evolving` Claim 中缺窗口内证据的、以及因此只能给 `insufficient_evidence` 的，
   逐条写明「结论只对到哪一年成立」。
3. 证据风险：核心 Claim 只靠单一来源、证据强度偏低、有相反结论。
4. 执行风险：来自 §9 的 `research` / `fundamental` 类瓶颈。
5. 判断不确定处：哪些结论是推断而非证据直接支持。

---

## 13. Recommendation

**{{ recommendation.verdict }}**

Rationale：{{ recommendation.rationale }}
（基于 Claim {{ recommendation.based_on_claim_ids }}）

若 `MODIFY` / `PIVOT`，列出 `conditions`——改什么、或转向哪个相邻机会。

---

## 14. Suggested Next Steps

按「先补哪条证据」排序，每条写清：要验证哪个 Claim、走哪个通道、预期得到什么。
优先补 `importance == high` 且 `insufficient_evidence` 的 Claim。

---

## 15. Evidence

| ID | Year | Source Type | Implementation Level | Strength | Relevance | Title / URL |
|---|---|---|---|---|---|---|
| E1 | 2025 | academic | paper | high | 0.9 | […](…) |

只列 `relevance >= 0.6` 的条目。低于阈值的证据不进报告。
