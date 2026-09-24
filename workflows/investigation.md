# Investigation Workflow

SKILL.md 给阶段索引，这份文件给**循环规则**：每一轮做什么、什么时候停、预算怎么花。

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
    if 所有 high Claim 已裁决 → break
    if 任一通道额度耗尽 或 iterations >= max_iterations → break
    pick action:
        - saturation 有 ADVISE:query_recent_work → 补一次近年检索（见下）
        - 有 `relevance >= 0.8` 的学术证据未做过引文展开 → cite
        - 有 pending query 且该 Claim 未饱和 → search
        - 有未归一化的新证据                 → normalize
        - 某 Claim 证据已够裁决              → verify
        - 某 Claim 连续 2 轮无新增           → skip
    consume --iterations 1
    check
finalize → analyze → report
```

每轮结束执行（先回写本次 query 状态，再记账校验）：

```bash
python3 scripts/validate_state.py mark-query <dir> --id Q5 --status done --result-count 6
python3 scripts/validate_state.py consume <dir> --channel academic --iterations 1 --queries 0 --results 0
python3 scripts/validate_state.py check <dir>
```

两个坑：① `check` 用 `not q.get("result_count")` 判定，所以 **0 条结果不能写 `done --result-count 0`**
（会被判 "status=done 但缺 result_count"）。查到 0 条时标 `skipped`，并把「该 query 过窄返回 0 条」
写进报告 §11 的覆盖缺口。② `merge` 对 `search_plans` 是按 id upsert，**删不掉条目**——
要把计划压回通道额度以内，只能直接改 `research-state.json`（脚本过滤后 `save_state`）。

**引文展开（`cite` action）**：任何一条归一化后 `relevance >= 0.8` 的学术证据，都要对它能做的引文展开。
这是关键词之外的必做入口，不受词表限制。直接以 seed 的 OpenAlex work id 构造 query：

```bash
python3 scripts/search_academic.py --query "cites:W123456789" --state-dir <dir> --claim-ids C3
python3 scripts/validate_state.py mark-query <dir> --id Q6 --status done --result-count 4
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
# claim     ev  indep  chg    dup  oldLR  rounds  flags
# C3         9      8    1    0.0      2       0  old_low_rel>=2,ADVISE:query_recent_work
```

`oldLR` = 该方向 `relevance<0.6` 且 `publication_year` 较早（≥8 年前）的证据数；
出现 `ADVISE:query_recent_work` 表示应先补近年检索，见上文「低相关老文告警」。

### 收口

所有 `importance == high` 的 Claim 都有 Judgment → 进入分析阶段。

## 预算耗尽怎么办

**不是硬凑结论，而是强制收口**：

```bash
python3 scripts/validate_state.py finalize <dir> --reason "预算耗尽："
```

它把所有还没裁决的 Claim 一律补成 `insufficient_evidence`（`confidence` 强制 0.0），
并把 state 推到 `verified`。幂等：已裁决的 Claim 不会被覆盖。

这是红线之一：**没查到 ≠ 不存在**。收口时补的 rationale 会写明是「未执行/未完成检索」，
报告 §11 还要把 `unavailable_channels` 和未覆盖方向一起列出来。

## 上下文控制

- Evidence 全文只写 `evidence.jsonl`，不进上下文。
- 单轮最多 10 条证据摘要进上下文，按 `relevance` 降序取。
- `research-state.json` 用 `merge` 增量更新，不做全量回灌。
- 报告阶段只载入 `relevance >= 0.6` 的条目。

## 通道不可用

脚本失败会自动写 `unavailable_channels[]`（`mark_unavailable`）。循环里看到某通道
unavailable 后，不要再对它发起请求，改走替代路径（见 `references/sources.md`）。

## 每轮必看

```bash
python3 scripts/validate_state.py budget <dir>      # 还剩多少额度
python3 scripts/validate_state.py saturation <dir>  # 哪些方向已经饱和
python3 scripts/validate_state.py check <dir>       # 结构是否还合法
```
