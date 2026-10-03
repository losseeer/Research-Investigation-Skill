# Investigation Workflow

SKILL.md 给阶段索引，这份文件给**循环规则**：每一轮做什么、什么时候停、预算怎么花。

## Budget Profile

Stage 0 的 `init` 由 `--profile`（默认 `standard`）把三档之一固化进 state：额度 + **饱和判据阈值**
（`independent` / `rounds_without_change` / `duplicate_rate`）一并写入 `search_budget.saturation`，
之后所有停止判断只读 state，不再查配置文件。

用户说「快速看下」「只要结论」「深挖一下」「写论文用」分别对应 `quick` / `standard` / `deep`；
未明示时用 `standard`。换档要重新 init——进行中的调查不会因为改了配置文件而变额度。

## Timeliness

时效基准来自 `state.time_policy`：`as_of`（init 写入当天，缺省按今天）+ `recency_window_years`（默认 2 年）。
慢变领域可在 init 时放宽：

```bash
python3 scripts/validate_state.py init --idea "<idea>" --recency-window 5
```

`evolving` Claim 才是被约束的对象；`timeless` Claim 用多旧的证据都不拦。
逐条判定在 Stage 1 完成（见 `prompts/decompose.md`），判定不了取 `evolving`——
错标 evolving 只多查一轮，错标 timeless 会让过时结论直接进最终建议。

判定读的是 `publication_year`，它的语义是「这条证据反映的现状时点」：论文取发表年，
**GitHub 取最后一次 push 的年**（不是创建年，否则会把活跃老仓库误判为过时、白补一轮检索）。

另一类是**旧快照**：`retrieved_at` 最早一条距 `as_of` 超过 180 天时 `check` 给 warning
（`saturation` 首行也打印 `retrieved=…~…`）。续跑的调查最容易踩——内容时点和抓取时点都新才算可靠。

## Action Space

每一轮从下面选一个动作执行。动作本身由 Agent 判断，但**每个动作前后都要过一次 `validate_state.py`**。

| Action | 做什么 | 前置 | 后置 |
|---|---|---|---|
| `search` | 取一条 `status == pending` 的 query 执行 | 该通道还有额度 | `mark-query`（done/failed + result_count）→ `check` + `budget` |
| `cite` | 对 `relevance >= 0.8` 的学术证据做引文展开（`cites:` / `referenced_works:`） | 有高相关 seed | `mark-query` → `check` |
| `normalize` | 校准刚取回的证据（`relevance` / `strength` / `claim_ids` / `query_id`） | 有新证据 | `check` |
| `verify` | 对某个 Claim 裁决 | 该 Claim 有 ≥1 条 `relevance >= 0.6` 的证据 | `check` |
| `analyze` | 补 prior art / 可行性 | 所有 high Claim 已裁决 | `check --stage 5` |
| `skip` | 主动放弃某 Claim（标 `insufficient_evidence`） | 预算不足或该方向明显无解 | `check` |
| `stop` | 结束循环 | — | `finalize` |

## 主循环

```text
init → decompose → search-planning
loop:
    verdict = stop-check                       # 先问机器要不要停
    if verdict == FINALIZE → break
    qid = next-query                           # 挑 pending 且通道还有额度的 Q
    execute(qid) → mark-query --status done    # 唯一计费入口，幂等
    consume --iterations 1
    check
finalize → analyze → report
```

每轮结束执行（先回写本次 query 状态与结果数，再校验）：

```bash
python3 scripts/validate_state.py mark-query <dir> --id Q5 --status done --result-count 6
python3 scripts/validate_state.py consume <dir> --channel academic --iterations 1
python3 scripts/validate_state.py check <dir>
```

**「一轮到底改了什么」必须能在 state 里读出来**，所以：

- query 计数只有 `mark-query` 一个入口（`executed_queries` 收据派生 `by_channel[*].queries`）；
  同一 Q 重复 mark 标注 `[already-charged]` 而不重复扣，`check` 会把手写计数判为 error。
- `consume` 只负责 results 与 iterations；传 `--queries` 会直接报错。
- 检索脚本必须带 `--query-id`，且**在取数前**就校验该 Q 存在、通道吻合；不存在的 Q 直接 FATAL，
  一条证据都不落盘（旧行为是先写证据再报错，留下 query_id 悬空的孤儿条目，只能手删）。

四个坑：① `check` 用 `not q.get("result_count")` 判定，所以 **0 条结果不能写 `done --result-count 0`**
（会被判 "status=done 但缺 result_count"）。查到 0 条时标 `skipped`，并把「该 query 过窄返回 0 条」
写进报告 §12 的覆盖缺口。② **`merge` 对 `search_plans` 是按 claim_id 覆盖整个 `queries` 数组**，
补新 query 时只传新增项会把旧 query 静默删掉。增量追加用 `add-queries`：

```bash
# ✅ 追加：按 Q id 合并，不动已有条目；不给 id 会自动分配 Qn
python3 scripts/validate_state.py add-queries <dir> \
  --data '{"claim_id":"C3","queries":[{"channel":"web","query":"..."}]}'

# ❌ merge：patch 里缺了已存在的 Q 会被判定为误删并拒绝写入（rc=1）
python3 scripts/validate_state.py merge <dir> --data '{"search_plans":[...]}'
```

确需精简计划（把条数压回通道额度内）只能直接改 `research-state.json`——`merge` 和 `add-queries` 都不会替你删。
③ `web` / `product` 由 agent 侧执行，落证据走 `add-evidence`，不要手拼 `evidence.jsonl`：

```bash
python3 scripts/validate_state.py add-evidence <dir> --channel web --query-id Q12 \
  --data '[{...}]'          # 或 --file items.json / 省略则读 stdin
```

它统一做 schema 校验 + E 编号 + 跨源去重 + 记 results 额度；**任何一条不合法就一条都不写**。
④ **时效缺口**：`evolving` Claim 用窗口外的旧证据下 `supported` / `partially_supported`，
`check` 会直接报 error（`idea-08` 这个 fixture 就是因此被卡在 stage 4）。三个出口，按优先级：

1. 补近年检索（关键词加年份下界 + 高相关 seed 引文展开）——默认走这条；
2. 确认是永真事实 → 改标 `time_sensitivity=timeless` 并在 `notes` 写理由；
3. 都不成立 → 下调为 `insufficient_evidence`，在 rationale 写明「结论只对到 X 年成立」。

**引文展开（`cite` action）**：任何一条归一化后 `relevance >= 0.8` 的学术证据，都要对它能做的引文展开。
这是关键词之外的必做入口，不受词表限制。直接以 seed 的 OpenAlex work id 构造 query：

```bash
python3 scripts/search_academic.py --query "cites:W123456789" --query-id Q6 \
    --state-dir <dir> --claim-ids C3
```

**低相关老文告警（即 query_recent_work）**：`saturation` 出现 `old_low_rel>=N` / `ADVISE:query_recent_work`
时，**不要逐条结案**。一批低相关老文说明该交叉方向历史悠久、通常有近作。先补一次覆盖近年窗口的检索——
给该方向的关键词 query 加年份下界（如 `from_publication_date:2018-…`），并对该方向的高相关 seed 做引文展开，
确认确实没有近作，再到 `skip`。这是防止「关键词只召回老文、漏掉近作」的主动动作。

## 停止条件

### 硬停止（budget）

- 任一通道 `queries >= max_queries` → 该通道停止，换别的通道继续。
- 所有通道都满，或 `iterations >= max_iterations`（默认 8）→ **全局停止**。

### 软停止（Evidence Saturation）

对**单个 Claim 方向**成立，不代表全局停止。满足任一即停该方向：

1. ≥3 条独立证据（不同 `source_type` 或不同作者 / 组织）支持或反驳。
2. 连续 2 轮 `changes_judgment == true` 的新增证据为 0。
3. 新增结果与已有结果归一化（URL ∪ 标题）后重复率 > 60%。
4. 主要 prior art 与技术路线已覆盖。

用 `saturation` 子命令看实时状态：

```bash
python3 scripts/validate_state.py saturation <dir>
# as_of=2026-09-09  recent_window=2y
# claim     ev  indep  chg    dup  oldLR  recent  rounds  flags
# C3         9      8    1    0.0      2     0/2024      0  old_low_rel>=2,ADVISE:query_recent_work
```

- `oldLR` = 该方向 `relevance<0.6` 且 `publication_year` 较早（≥8 年前）的证据数；
  出现 `ADVISE:query_recent_work` 表示应先补近年检索，见上文「低相关老文告警」。
- `recent` = 窗口内证据数 / 该 Claim 的 cutoff 年；`timeless` Claim 显示 `n/a`。
  `evolving` Claim 的 `recent` 为 0 时不计饱和（flags 里带 `ADVISE:query_recent_work`），
  `stop-check` 会判 `CONTINUE` 而不是拿旧结论收口——除非额度已耗尽。

### 收口

所有 `importance == high` 的 Claim 都有 Judgment → 进入分析阶段。

## 预算耗尽怎么办

**不是硬凑结论，而是强制收口**：

```bash
python3 scripts/validate_state.py finalize <dir> --reason "预算耗尽："
```

它把所有还没裁决的 Claim 一律补成 `insufficient_evidence`（`confidence` 强制 0.0），
并把 state 推到 `verified`。幂等：已裁决的 Claim 不会被覆盖，但会把 Judgment 状态回写
`claim.status`（避免两处状态长期不一致）。

这是红线之一：**没查到 ≠ 不存在**。收口时补的 rationale 会写明是「未执行/未完成检索」，
报告 §12 还要把 `unavailable_channels`、未覆盖方向和时效缺口一起列出来。

## 上下文控制

- Evidence 全文只写 `evidence.jsonl`，不进上下文。
- 单轮最多 10 条证据摘要进上下文，按 `relevance` 降序取。
- `research-state.json` 用 `merge` 增量更新，不做全量回灌。
- 报告阶段只载入 `relevance >= 0.6` 的条目。

## 通道不可用

脚本失败会自动写 `unavailable_channels[]`（`mark_unavailable`）。循环里看到某通道
unavailable 后，不要再对它发起请求，改走替代路径（见 `references/sources.md`）。

限流（429 / 5xx）与代理层拒绝（403）由网络层自己处理：指数退避 → 换回退出口。
**重试不是免费的**：它吃的是墙钟而不是 query 额度，一轮里若多个源都在退避，
先换通道（`--source crossref`）比干等更划算——OpenAlex 出现过持续数十秒的 503 窗口，退避无效。

## 网络代价

- 同一 URL 24 小时内不重复抓（`<state-dir>/.cache/`）。重跑同一条 query、或跨轮续跑时直接命中，
  但**命中的证据 `retrieved_at` 是当初抓取的时间**，别把它当刚抓的。
- 单次响应体 > 2MB 直接判失败，不会截断；单 query 最多取回 30 条（`--max-results` 更大也没用）。
- 缓存只是省网络，不是数据源：过期或损坏都退回真实抓取。

## 每轮必看

```bash
python3 scripts/validate_state.py budget <dir>      # 还剩多少额度
python3 scripts/validate_state.py saturation <dir>  # 哪些方向已经饱和
python3 scripts/validate_state.py check <dir>       # 结构是否还合法
```
