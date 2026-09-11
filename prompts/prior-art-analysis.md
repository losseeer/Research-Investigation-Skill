# Stage 5a — Prior Art Analysis

## 输入

`evidence.jsonl`（全部）+ `state.claims` 的裁决结果。

## 目标

列出真正相关的已有工作，逐条判定相似度，产出比较矩阵，写入 `state.prior_art`。

判断 Novelty 的唯一依据就在这里——没有这条目的支撑，Novelty 只能是抽象断言。

## 条目来源

每一条 prior art **必须有 `evidence_ids`**，不能凭印象写。
一个证据可以对应多条 prior art（同一篇论文在两个维度上分别与不同工作相似）。

`kind`：

- `academic` — 论文 / 预印本
- `implementation` — 开源实现、工具、框架
- `product` — 商业产品、在线服务

## similarity 五档

按四个维度分别看：**problem**（要解决什么问题）/ **method**（用什么方法）/
**system**（系统怎么搭）/ **evaluation**（怎么验证）。取最强的一档作为总体判定，
并把它发生的维度写进 `dimension`。

| 档 | 判据 | 对 Novelty 的含义 |
|---|---|---|
| `identical` | 问题 + 方法 + 系统/评估都基本一致 | Novelty 归零 → `DON'T_DO` |
| `highly_similar` | 问题与方法一致，只在场景、数据或实现细节上不同 | 最多 `incremental` |
| `partially_overlapping` | 只共享问题或只共享方法 | 可到 `moderate` |
| `adjacent` | 同领域，但问题与方法都不同 | 可到 `significant` |
| `distinct` | 只是关键词重合 | 不构成 prior art，别列进来 |

`distinct` 的条目不要列——列了会稀释矩阵，也会让 Novelty 看起来比实际高。

## difference

必填，写**具体差异**：哪个维度、差在哪、差异是否实质。

反例（禁止）：「我们的方法更好」「我们的系统更智能」「面向中国用户」。
正例：「E3 用固定 POI 序列 + 时间窗约束做优化，不含 LLM；本 Idea 用 LLM 解析自然语言约束，
且把实时事件（天气/闭馆）作为重排输入——差异在 method 与 system 两个维度。」

## 比较矩阵

写进报告 §5，行 = prior art 条目，列 = 四个维度：

| Prior Art | kind | problem | method | system | evaluation | 总体 |
|---|---|---|---|---|---|---|
| P1 TravelAgent (E5) | implementation | highly_similar | partially_overlapping | adjacent | adjacent | highly_similar |
| P2 ITINERA (E2) | academic | highly_similar | highly_similar | partially_overlapping | adjacent | highly_similar |

单元格从五档里取，总体取最强的一档。

## 写回

```bash
python3 scripts/validate_state.py merge <state-dir> --data '{
  "prior_art": [{
    "id":"P1","title":"TravelAgent: An AI Assistant for Personalized Travel Planning",
    "url":"https://...","kind":"academic",
    "similarity":"highly_similar","dimension":"problem",
    "difference":"E2 只做行前静态规划，不接入实时事件源，也不支持行程中重排。",
    "evidence_ids":["E2"]
  }]
}'
```

## 自检

- [ ] 每条都有 `evidence_ids`？
- [ ] 有没有把 `distinct` 的噪声条目列进来？
- [ ] `difference` 是具体差异而不是形容词？
- [ ] 每条都标了最强相似发生在哪个维度？
- [ ] 有没有出现 `identical`？如果有，后面 Novelty 和 Recommendation 必须跟着改。

## 出口

```bash
python3 scripts/validate_state.py check <state-dir> --stage 5
```
