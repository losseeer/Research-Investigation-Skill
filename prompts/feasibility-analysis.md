# Stage 5b — Feasibility Analysis

## 输入

`state.claims` 的裁决 + `state.prior_art` + `evidence.jsonl`。

## 目标

填 `state.analysis` 的三块：**Motivation** / **Bottlenecks** / **Novelty**。

最终 Recommendation（Stage 6）只基于这三块与 Claim 裁决产出，不再回头看原始材料。

---

## 1. Motivation

| 字段 | 填什么 |
|---|---|
| `problem` | 要解决的具体问题，不是领域名 |
| `who_cares` | 谁有这个问题，规模或频次有什么证据 |
| `value` | 解决了有什么价值 |
| `assessment` | `strong` / `moderate` / `weak` / `unclear` |

`assessment` 必须由对应的 Claim 裁决推出：

- `user_problem` 与 `market` 类 Claim 被 `supported` → `strong` 或 `moderate`
- 只有间接证据（比如只有行业报告没有用户数据）→ 最多 `moderate`
- 相关 Claim 是 `insufficient_evidence` → `unclear`

**不要**因为「技术可行」就给 motivation 打高分——这两件事没有因果关系。

---

## 2. Bottlenecks

每条瓶颈：

| 字段 | 说明 |
|---|---|
| `id` | `B1`、`B2` … |
| `description` | 具体卡在哪一步 |
| `bottleneck_type` | 见下 |
| `severity` | `high` / `medium` / `low` |
| `evidence_ids` | 有证据就填；**推断出来的留空** |

`bottleneck_type` 决定了「这个 Idea 主要是工程问题还是研究问题」，是报告 §9 的核心结论：

| 类型 | 判据 | 意味着 |
|---|---|---|
| `engineering` | 方法已知，难点在工程量、系统集成、数据获取、延迟成本 | 能做，代价是时间和人力 |
| `research` | 方法未定，需要实验验证效果，结果不确定 | 有失败风险，需要预研 |
| `fundamental` | 受既有理论或模型能力边界限制（上下文长度、推理可靠性、可证最优性等） | 短期无解，需要绕开或换问题 |

判错类型的代价很高：`research` 当成 `engineering` 会严重低估工期。
拿不准就标 `research` 并在 description 里写清不确定性来源。

---

## 3. Novelty

| 字段 | 说明 |
|---|---|
| `level` | `none` / `incremental` / `moderate` / `significant` / `breakthrough` |
| `because` | **只能引用 `prior_art.difference` 与 Evidence**，禁止抽象断言 |
| `based_on_prior_art_ids` | 支撑该判定的 prior art 编号 |

### 与 prior art 的对应关系

| 最强 prior art 的 similarity | Novelty 上限 |
|---|---|
| `identical` | `none` |
| `highly_similar` | `incremental` |
| `partially_overlapping` | `moderate` |
| `adjacent` | `significant` |
| 无相关 prior art | 才可能 `breakthrough` |

**上限不等于实际取值**：`adjacent` 只说明「有可能 significant」，
是否真的到得了，还要看核心 Claim 是否被 `supported`——
如果 Idea 的核心假设本身是 `contradicted`，Novelty 再高也没意义。

### 关于 `breakthrough`

需要极强证据：确实没有相近工作，且核心 Claim 有独立的高强度证据支持。
默认不要给这档，给了要在 `because` 里写清「检索覆盖了哪些通道、为什么认为没有遗漏」，
并在报告 §11 说明覆盖缺口。

### because 反例

- ❌ 「本 Idea 具有显著创新性，结合了 LLM 与实时数据」
- ✅ 「P1/P2 均止于行前静态规划（见其 difference），无一接入实时事件源；
  C7（LLM 与实时状态闭环）为 `insufficient_evidence`，故只给 `moderate` 而非 `significant`」

---

## 写回

```bash
python3 scripts/validate_state.py merge <state-dir> --data '{
  "analysis": {
    "motivation": {"problem":"…","who_cares":"…","value":"…","assessment":"moderate"},
    "bottlenecks": [
      {"id":"B1","description":"实时事件源（天气/营业时间）接入与可靠性",
       "bottleneck_type":"engineering","severity":"high","evidence_ids":[]},
      {"id":"B2","description":"LLM 在长行程多约束下的规划成功率未有定论",
       "bottleneck_type":"research","severity":"high","evidence_ids":["E1"]}
    ],
    "novelty": {"level":"moderate","because":"…","based_on_prior_art_ids":["P1","P2"]}
  }
}'
```

## 自检

- [ ] `motivation.assessment` 是由 Claim 裁决推出来的，而不是凭感觉？
- [ ] 每条 bottleneck 都分清了 `engineering` / `research` / `fundamental`？
- [ ] Novelty 有没有超过 prior art 相似度允许的上限？
- [ ] `because` 引用了具体的 prior art 或 Evidence？
- [ ] 有没有心软给了 `breakthrough`？

## 出口

```bash
python3 scripts/validate_state.py check <state-dir> --stage 5
```
