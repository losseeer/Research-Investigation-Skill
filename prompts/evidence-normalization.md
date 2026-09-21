# Stage 3b — Evidence Normalization

## 输入

`evidence.jsonl` 中新增的候选条目（由 `search_academic.py` / `search_github.py` / WebSearch 产出）。

## 为什么必须有这一步

脚本只做字段映射，不做语义判断：`relevance` 一律填 `0.5`，`strength` 按被引/星数用启发式给。
**报告阶段只载入 `relevance >= 0.6` 的条目**——不归一化的话，要么全部条目被丢弃，要么全靠
默认值蒙混过关，两种都会让结论失去可追溯性。

去重已由脚本按「归一化 URL ∪ 归一化标题」做过一轮；这一步处理的是**质量校准**。

## 逐条校准

对每条 Evidence 依次判断：

### `relevance`（0.0–1.0）

| 档 | 判据 |
|---|---|
| 0.8–1.0 | 直接命中 Claim 的核心概念，且提供了可引用的结论或数据 |
| 0.6–0.8 | 高度相关，但只是部分命中（同方法不同场景 / 同场景不同方法） |
| 0.3–0.5 | 只沾边（仅背景提及、只在 related work 里出现） |
| 0.0–0.2 | 噪声，考虑直接删除而不是留在库里 |

不要把所有条目都打成 0.9——那等于没有排序，报告阶段会一次塞进全部内容。

### `strength`

- **high**：一手数据源且**直接**验证 Claim（论文给出的实测结果、可运行且活跃的仓库、官方产品文档）。
- **medium**：二手或间接（综述、新闻报道、文档描述、无实测的预印本）。
- **low**：单一来源、无佐证的观点（博客、营销页、未标注来源的榜单）。

### `implementation_level`

脚本给的默认值（`paper` / `code`）是**下限**。要升级必须有额外证据：

| 级别 | 需要看到什么 |
|---|---|
| `idea` → `paper` | 有正式发表或预印本 |
| `paper` → `code` | 有可访问的仓库链接，且不是空壳（有提交、有 README） |
| `code` → `prototype` | README / 文档说明可运行，有 demo 或使用示例 |
| `prototype` → `production` | 有真实部署证据（官网、备案、企业 case、SLA 文档） |
| `production` → `commercial_product` | 有明确的商业售卖证据（定价页、付费计划、营收数据） |

**禁止反向推断**：GitHub 星数高不代表是产品，论文引用高不代表有代码。
看到什么级别的证据就填什么级别，没有证据就停在脚本默认值。

### `claim_ids`

- 允许多条（一条论文可以同时支持 C3、反驳 C4）。
- 不相关就移除，**不要为了凑数挂靠**——挂错了会污染 Claim 裁决与 saturation 计数。

### `query_id`

- 记录该证据是由 `search_plans` 中哪条 query 取回的（`Q…`）。用于复盘时回溯「这条证据从哪个 query
  进入候选池」。
- 高相关 evidence 的来源 query 一定要记准——这是判断「为什么命中/为什么漏掉」的基础。
- 若该方向同时出现了引文展开（`cites:` / `referenced_works:`）取回的证据，`query_id` 要指向那条 cite query。

## 低相关老文告警（不要逐条结案）

归一化时若发现：某 Claim 方向出现 **≥2 条 `relevance` 偏低（0.3–0.55）且 `publication_year` 较早
（≥8 年前）** 的证据，**不要**直接以「这条不够相关」逐条结案。一批低相关老文是信号——说明该交叉方向历史悠久，
而历史悠久的交叉方向通常有近作（本次事故的 GENTIANS 就是近作：同族老文 E25/E30 被评 0.55 排除时，
2025 年的近作因引用量低被取量截断，从未进候选池）。此时应：

1. 把这个信号记下来（对应 `saturation` 的 `ADVISE:query_recent_work`）；
2. 给该方向补一次**覆盖近年窗口**的检索（关键词加 `from_publication_date` 下界）；
3. 对能确认的高相关 seed 做引文展开（`cite` action）；
4. 确认确实没有近作，再落 `insufficient_evidence`。

### `changes_judgment`

这条证据是否改变了对应 Claim 的判断（从 unknown 变 supported、从 supported 变 contradicted 等）。
它是 Evidence Saturation 的计数依据：**连续 2 轮没有任何 `changes_judgment == true` 的新增证据就停止该方向**。
随手全填 `true` 会让停止条件永远不触发。

### `summary` / `evidence`

- `evidence`：直接支持或反驳 Claim 的**原文摘录或数据点**，不能是概括。
- `summary`：进上下文的摘要（作者 / 来源 / 年份 + 核心结论），控制在一两段。
- 两者都不得写原文里没有的内容。

## 写回

```bash
python3 scripts/validate_state.py set-evidence <state-dir> E3 \
  --data '{"relevance":0.8,"strength":"high","claim_ids":["C3","C4"],"changes_judgment":true,"query_id":"Q2"}'
```

先合并再整体校验，校验不过不落盘。批量校准建议一条一条改，改完跑一次 `check`。

## 自检

- [ ] 每条都校准过 `relevance`？有没有全填同一个值？
- [ ] `implementation_level` 的每次升级都有对应证据？
- [ ] `evidence` 字段是原文摘录而不是概括？
- [ ] 有没有把 academic 条目标成 `code`（除非确实带仓库链接）？
- [ ] `claim_ids` 里有没有凑数挂靠？
- [ ] 每条证据都回填了 `query_id`？若某方向出现 ≥2 条低相关老文，是否记录了信号并补了近年检索？

## 出口

```bash
python3 scripts/validate_state.py check <state-dir> --stage 3
python3 scripts/validate_state.py saturation <state-dir>
```
