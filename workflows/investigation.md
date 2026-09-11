# Investigation Workflow

SKILL.md 给阶段索引，这份文件给**循环规则**：每一轮做什么、什么时候停、预算怎么花。

## Action Space

每一轮从下面选一个动作执行。动作本身由 Agent 判断，但**每个动作前后都要过一次 `validate_state.py`**。

| Action | 做什么 | 前置 | 后置 |
|---|---|---|---|
| `search` | 取一条 `status == pending` 的 query 执行 | 该通道还有额度 | `check` + `budget` |
| `normalize` | 校准刚取回的证据（`relevance` / `strength` / `claim_ids`） | 有新证据 | `check` |
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
        - 有 pending query 且该 Claim 未饱和 → search
        - 有未归一化的新证据                 → normalize
        - 某 Claim 证据已够裁决              → verify
        - 某 Claim 连续 2 轮无新增           → skip
    consume --iterations 1
    check
finalize → analyze → report
```

每轮结束执行：

```bash
python3 scripts/validate_state.py consume <dir> --channel academic --iterations 1 --queries 0 --results 0
python3 scripts/validate_state.py check <dir>
```

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
# claim     ev  indep  chg    dup  rounds  flags
# C3         9      8    1    0.0       0  SATURATED independence>=3
```

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
