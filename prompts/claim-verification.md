# Stage 4 — Claim Verification

## 输入

`state.claims` + `evidence.jsonl` 中挂在每条 Claim 下的 Evidence。

## 目标

逐条给出裁决（Judgment），写回 `state.judgments`，并回填 Claim 的 `status` / `confidence` / `evidence_ids`。

这是整个流程里唯一的「判断」环节。后面所有分析都只能引用这里的裁决结果，
不允许回到原始材料重新下结论。

## 参与裁决的证据

只看 `claim_ids` 包含当前 Claim、且 **`relevance >= 0.6`** 的证据。

- 全部低于 0.6 → 视为没有有效证据，`status = insufficient_evidence`。
- 不要为了凑证据把 0.3 的条目拉进来。

## status 判定

| status | 判据 |
|---|---|
| `supported` | ≥2 条**独立**证据支持（不同 `source_type` 或不同作者/组织），且无实质反证 |
| `partially_supported` | 只有 1 条独立支持证据；或支持证据成立但有明确边界条件（只在某场景/数据上成立）；或正反证据都有但支持方更强 |
| `contradicted` | ≥1 条 `high` 或 ≥2 条 `medium` 反证，且支持证据更弱 |
| `insufficient_evidence` | 没有有效证据，或证据全部间接/不相关。**必须同时填 `evidence_gaps`** |

**禁止**：

- 把「没搜到相关工作」当作 `contradicted`——那是 `insufficient_evidence`，
  而且要在最终报告 §11 声明覆盖缺口。
- 正反证据都有时各打五十大板写 `supported`。比较 `strength` 与独立性后取更强一方，
  犹豫不决就写 `partially_supported` 并说明分歧点。

## confidence 校准

| 区间 | 判据 |
|---|---|
| 0.8–1.0 | ≥3 条独立 `high` 证据，无反证 |
| 0.6–0.8 | ≥2 条独立证据，无强反证 |
| 0.4–0.6 | 1 条证据，或正反混合 |
| 0.0–0.3 | 只有间接证据 |
| **0.0** | `insufficient_evidence` 时**必须**为 0.0 |

confidence 是给后续排序和报告措辞用的，不是信心投票——同一档证据就该给同一档分数。

## rationale

必须引用具体的 Evidence 编号（`E1`、`E7`），不能写「有研究表明」这类无指向的陈述。
门禁会检查：裁决态非 `insufficient_evidence` 时 `supporting` / `contradicting` 至少有一个非空。

## 反向 Claim

`decompose` 阶段刻意留的「若成立则 Idea 不成立」的 Claim 要单独留意：
一旦它被 `supported`，最终 Recommendation 基本只能落在 `DON'T_DO` 或 `PIVOT`，
不要硬写成 `MODIFY`。

## 写回

```bash
python3 scripts/validate_state.py merge <state-dir> --data '{
  "claims": [{"id":"C3","status":"supported","confidence":0.8,"evidence_ids":["E1","E5"]}],
  "judgments": [{
    "claim_id":"C3","status":"supported","confidence":0.8,
    "rationale":"E1（Travel Route Planning Optimization based on LLM, 2024）直接给出 LLM 做带 POI 类型约束的行程规划；E5（github）提供可运行实现。",
    "supporting_evidence_ids":["E1","E5"],
    "contradicting_evidence_ids":[],
    "evidence_gaps":""
  }]
}'
```

数组字段（如 `evidence_ids`）是**整体替换**，传全量；对象字段深合并；
`judgments` 按 `claim_id` upsert，重新裁决会覆盖而不是追加。校验不过不落盘。

## 自检

- [ ] 每条 `importance == high` 的 Claim 都有 Judgment？（门禁会卡）
- [ ] 有没有把「没搜到」写成 `contradicted`？
- [ ] 每条 `rationale` 都引用了 E 编号？
- [ ] `insufficient_evidence` 的条目都写了 `evidence_gaps`？confidence 是不是 0.0？
- [ ] confidence 有没有拉开档次？

## 出口

```bash
python3 scripts/validate_state.py check <state-dir> --stage 4
```
