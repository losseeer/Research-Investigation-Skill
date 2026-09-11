# Stage 6 — Report Synthesis

## 输入

只有两样：`research-state.json` 与 `evidence.jsonl`（`relevance >= 0.6` 的条目）。

**禁止**引入上下文里的临时信息、记忆中的印象、或者 state 之外任何来源。
报告里的每句话都要能在 state 或 evidence 里找到出处，否则就不该写。

## 第一步：定 Recommendation

先定结论再写报告——结论驱动取材，反过来会写成流水账。

| 条件 | Verdict |
|---|---|
| 存在 `identical` prior art，或核心 Claim 被 `contradicted` | `DON'T_DO` |
| 核心 Claim `supported`，Novelty ≥ `moderate`，瓶颈以 `engineering` 为主 | `DO` |
| 核心 Claim `supported`，但 Novelty 只有 `incremental` | `MODIFY` |
| 核心 Claim `contradicted`，但相邻方向的 Claim 被 `supported` | `PIVOT` |
| 多数 high Claim 是 `insufficient_evidence` | `INSUFFICIENT_EVIDENCE` |

「核心 Claim」= `importance == high` 且类型为 `technical` / `scientific` / `user_problem` 的那些。

判定优先级：**contradicted > insufficient_evidence > supported**。
只要有 high Claim 被 `contradicted`，就不能给 `DO`；
只要有 high Claim 是 `insufficient_evidence`，就不能给比 `MODIFY` 更强的结论。

`based_on_claim_ids` 必填，指向支撑该结论的 Claim（门禁会卡）。

```bash
python3 scripts/validate_state.py merge <dir> --data '{
  "recommendation": {
    "verdict": "INSUFFICIENT_EVIDENCE",
    "rationale": "C3（LLM 行程规划）supported，但 C1/C2/C4/C7 四条 high Claim 均为 insufficient_evidence，novelty 只能给到 incremental。",
    "based_on_claim_ids": ["C3","C1","C2","C4","C7"],
    "conditions": ["补 web 通道验证用户是否真有行程中重排需求", "补 product 通道核查现有产品的重排能力"]
  },
  "status": "reported"
}'
```

## 第二步：按模板填报告

模板：`assets/report-template.md`，14 节结构固定，不增删、不调序。

各节的取材：

| 节 | 从哪来 |
|---|---|
| 1 Executive Summary | recommendation + novelty + 核心 Claim 裁决 |
| 2 Idea Reconstruction | `idea.raw` / `idea.domain` / `idea.constraints` |
| 3 Core Claims | `claims` + `judgments`（含 `evidence_gaps`） |
| 4 Existing Academic Work | `source_type == academic` 的 Evidence |
| 5 Prior Art Analysis | `prior_art` + 四维度比较矩阵 |
| 6 Scientific Support | `type == scientific` 的 Claim 裁决 |
| 7 Existing Products | `source_type == product` / `github` 的 Evidence + `implementation_level` |
| 8 Motivation & Application Value | `analysis.motivation` |
| 9 Technical Bottlenecks | `analysis.bottlenecks` |
| 10 Novelty Analysis | `analysis.novelty` |
| 11 Risks | `unavailable_channels` + 低强度证据 + research/fundamental 瓶颈 |
| 12 Recommendation | `recommendation` |
| 13 Suggested Next Steps | 未裁决的 high Claim 的 `evidence_gaps` |
| 14 Evidence | `relevance >= 0.6` 的全部条目 |

## 写作约束

- **每条结论后面跟 Claim ID 或 Evidence ID**。写不出来的，说明它在 state 里没有依据——删掉。
- `implementation_level` 严格按 state 里的值陈述。`code` 就是「有代码」，
  不许写成「已有成熟产品」。
- §11 覆盖缺口**必填**：把 `unavailable_channels` 的通道、未执行的查询方向、
  以及因此可能遗漏的工作都写出来。这是「通道不可用 ≠ 没有 prior work」的落地位置。
- §9 的结论（工程问题 vs 研究问题）取 `severity == high` 的瓶颈中类型最严重的一档。
- 不要为了读起来顺畅而补 state 里没有的因果、规模数字或时间线。

## 输出

写到 `research/<idea-slug>/report.md`。

## 自检

- [ ] 报告里每句话都能在 state / evidence 里找到出处？
- [ ] §11 有没有写覆盖缺口？
- [ ] §3 里 `insufficient_evidence` 的 Claim 有没有说明「为什么没查到」？
- [ ] §7 有没有把 `code` 写成产品？
- [ ] Recommendation 的判定优先级用对了（contradicted 压过一切）？

## 出口

```bash
python3 scripts/validate_state.py check <dir> --stage 6
```
