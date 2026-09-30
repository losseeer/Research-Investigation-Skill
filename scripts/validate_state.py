#!/usr/bin/env python3
"""validate_state.py — Schema 校验 + budget 记账 + Evidence Saturation 统计。

stdlib only，零依赖。所有额度从 state 自身读取，脚本内不内置通道常量。

用法:
    validate_state.py profiles
    validate_state.py init --idea "<idea 文本>" [--root research] [--profile quick|standard|deep]
    validate_state.py check <state-dir> [--stage N] [--json]
    validate_state.py budget <state-dir>
    validate_state.py saturation <state-dir>
    validate_state.py consume <state-dir> --channel academic [--queries 1] [--results 12]
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from _common import now_iso

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = SKILL_ROOT / "schemas"
TEMPLATE = SKILL_ROOT / "assets" / "research-state.template.json"
PROFILES = SKILL_ROOT / "assets" / "budget-profiles.json"
CHANNELS = ("academic", "github", "web", "product")
PROFILE_NAMES = ("quick", "standard", "deep")
# 老 state（profile 字段写入之前建的）没有 saturation 阈值时的兜底值，
# 与 standard 档一致。用到时必须显式提示，不允许静默降级。
SATURATION_DEFAULTS = {"min_independent": 3, "max_rounds_without_change": 2, "duplicate_rate": 0.6}


def load_profiles():
    """读取三档预算定义。文件缺失或结构不对一律显式报错，不做静默回退。"""
    if not PROFILES.exists():
        sys.exit(f"FATAL: 预算档位定义缺失 {PROFILES}")
    with open(PROFILES, encoding="utf-8") as f:
        cfg = json.load(f)
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        sys.exit(f"FATAL: {PROFILES} 缺少有效的 profiles 字段")
    missing = [n for n in PROFILE_NAMES if n not in profiles]
    if missing:
        sys.exit(f"FATAL: {PROFILES} 缺少 profile: {', '.join(missing)}")
    return cfg


def apply_profile(state: dict, name: str):
    """把某档位拷贝进 state.search_budget。额度以 state 为准，不再外部查找。"""
    cfg = load_profiles()
    if name not in cfg["profiles"]:
        sys.exit(f"FATAL: 未知档位 {name}，可选: {', '.join(sorted(cfg['profiles']))}")
    prof = cfg["profiles"][name]
    b = state["search_budget"]
    b["profile"] = name
    b["max_iterations"] = prof["max_iterations"]
    b["max_queries"] = prof["max_queries"]
    b["saturation"] = dict(prof["saturation"])
    for ch in CHANNELS:
        b["by_channel"].setdefault(ch, {"max_queries": 0, "max_results": 0,
                                        "queries": 0, "results": 0})
        b["by_channel"][ch]["max_queries"] = prof["by_channel"][ch]["max_queries"]
        b["by_channel"][ch]["max_results"] = prof["by_channel"][ch]["max_results"]


def saturation_thresholds(state: dict):
    """返回 (thresholds, from_profile)。老 state 没有该字段时给出兜底并标记来源。"""
    st = state.get("search_budget", {}).get("saturation")
    if isinstance(st, dict) and st:
        return {**SATURATION_DEFAULTS, **st}, True
    return dict(SATURATION_DEFAULTS), False


# --------------------------------------------------------------------------
# 迷你 JSON Schema 校验器（仅支持本 Skill 用到的子集）
# --------------------------------------------------------------------------
class Validator:
    def __init__(self, schema_dir: Path):
        self.schema_dir = schema_dir
        self._cache = {}

    def load(self, name: str) -> dict:
        if name not in self._cache:
            with open(self.schema_dir / name, encoding="utf-8") as f:
                self._cache[name] = json.load(f)
        return self._cache[name]

    def validate(self, inst, schema, path="$", errors=None):
        if errors is None:
            errors = []
        if "$ref" in schema:
            self.validate(inst, self.load(schema["$ref"]), path, errors)
            return errors

        types = schema.get("type")
        if types is not None:
            expected = types if isinstance(types, list) else [types]
            if not self._type_ok(inst, expected):
                errors.append(f"{path}: 类型应为 {'/'.join(expected)}，实际为 {type(inst).__name__}")
                return errors

        if "enum" in schema and inst not in schema["enum"]:
            errors.append(f"{path}: 取值 {inst!r} 不在枚举 {schema['enum']} 内")
            return errors

        if isinstance(inst, str):
            if "minLength" in schema and len(inst) < schema["minLength"]:
                errors.append(f"{path}: 字符串长度需 >= {schema['minLength']}")
            if "pattern" in schema and not re.search(schema["pattern"], inst):
                errors.append(f"{path}: 不匹配 pattern {schema['pattern']}")
        elif isinstance(inst, (int, float)) and not isinstance(inst, bool):
            if "minimum" in schema and inst < schema["minimum"]:
                errors.append(f"{path}: 需 >= {schema['minimum']}，实际 {inst}")
            if "maximum" in schema and inst > schema["maximum"]:
                errors.append(f"{path}: 需 <= {schema['maximum']}，实际 {inst}")
        elif isinstance(inst, list):
            if "minItems" in schema and len(inst) < schema["minItems"]:
                errors.append(f"{path}: 数组长度需 >= {schema['minItems']}")
            item_schema = schema.get("items")
            if item_schema:
                for i, item in enumerate(inst):
                    self.validate(item, item_schema, f"{path}[{i}]", errors)
        elif isinstance(inst, dict):
            for key in schema.get("required", []):
                if key not in inst:
                    errors.append(f"{path}: 缺少必填字段 {key}")
            props = schema.get("properties", {})
            for key, value in inst.items():
                if key in props:
                    self.validate(value, props[key], f"{path}.{key}", errors)
                elif schema.get("additionalProperties") is False:
                    errors.append(f"{path}: 出现未定义字段 {key}")
                elif isinstance(schema.get("additionalProperties"), dict):
                    self.validate(value, schema["additionalProperties"], f"{path}.{key}", errors)
        return errors

    @staticmethod
    def _type_ok(inst, expected):
        for t in expected:
            if t == "object" and isinstance(inst, dict):
                return True
            if t == "array" and isinstance(inst, list):
                return True
            if t == "string" and isinstance(inst, str):
                return True
            if t == "boolean" and isinstance(inst, bool):
                return True
            if t == "integer" and isinstance(inst, int) and not isinstance(inst, bool):
                return True
            if t == "number" and isinstance(inst, (int, float)) and not isinstance(inst, bool):
                return True
            if t == "null" and inst is None:
                return True
        return False


# --------------------------------------------------------------------------
# state / evidence 读写
# --------------------------------------------------------------------------
def load_state(state_dir: Path):
    path = state_dir / "research-state.json"
    if not path.exists():
        sys.exit(f"FATAL: 找不到 {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f), path


def load_evidence(state_dir: Path):
    path = state_dir / "evidence.jsonl"
    if not path.exists():
        return [], []
    items, bad = [], []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as e:
            bad.append(f"evidence.jsonl:{i}: 非法 JSON ({e.msg})")
    return items, bad


def save_state(path: Path, state: dict):
    state["updated_at"] = now_iso()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_url(url: str) -> str:
    """URL 归一化，用于去重：去 scheme / www / 末尾斜杠 / fragment / utm 参数。"""
    if not url:
        return ""
    try:
        u = urlparse(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (u.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    query = "&".join(
        p for p in (u.query or "").split("&") if p and not p.lower().startswith("utm_")
    )
    path = (u.path or "").rstrip("/")
    return f"{host}{path}" + (f"?{query}" if query else "")


def _query_channel(state: dict, qid: str):
    """某 Q id 在 search_plans 中归属的通道；找不到返回 None。"""
    for p in state.get("search_plans", []):
        for q in p.get("queries", []):
            if q.get("id") == qid:
                return q.get("channel")
    return None


def derived_query_counts(state: dict) -> dict:
    """从 executed_queries 收据派生每通道的 query 计数。"""
    counts = {ch: 0 for ch in CHANNELS}
    for qid in state.get("search_budget", {}).get("executed_queries", []):
        ch = _query_channel(state, qid)
        if ch in counts:
            counts[ch] += 1
        else:
            counts[ch] = counts.get(ch, 0) + 1
    return counts


def sync_budget(state: dict):
    """把 by_channel[*].queries 与 used.queries 重算为 executed_queries 的派生值。

    query 计数的唯一真源是收据数组；任何手写/PDB 改出来的计数都会在落盘前被覆盖，
    不可能出现「计数器与执行记录不一致」。
    """
    b = state.setdefault("search_budget", {})
    by_ch = b.setdefault("by_channel", {})
    counts = derived_query_counts(state)
    for ch in CHANNELS:
        by_ch.setdefault(ch, {"max_queries": 0, "max_results": 0, "queries": 0, "results": 0})
    for ch, cur in by_ch.items():
        cur["queries"] = counts.get(ch, 0)
    used = b.setdefault("used", {"queries": 0, "results": 0})
    used["queries"] = sum(c.get("queries", 0) for c in by_ch.values())
    used["results"] = sum(c.get("results", 0) for c in by_ch.values())
    return b


def charge_query(state: dict, qid: str) -> bool:
    """把一条 query 计一次费。同一 Q 重复调用不重复计费（幂等）。

    超出该通道 query 上限时抛 ValueError。返回 True 表示本次真的计了费。
    """
    receipts = state.setdefault("search_budget", {}).setdefault("executed_queries", [])
    if qid in receipts:
        return False
    ch = _query_channel(state, qid)
    if ch is None:
        raise ValueError(f"{qid}: search_plans 中不存在，拒绝计费")
    if ch not in CHANNELS:
        raise ValueError(f"{qid}: channel {ch} 非法")
    # 先用「计费后」的值判超限，避免先把收据写进去再回滚
    would_be = derived_query_counts(state).get(ch, 0) + 1
    cap = state["search_budget"].get("by_channel", {}).get(ch, {}).get("max_queries", 0)
    if would_be > cap:
        raise ValueError(f"{ch}: queries {would_be} 超过上限 {cap}（query {qid}）")
    receipts.append(qid)
    sync_budget(state)
    return True


def finish_query(state_dir, qid: str, status: str, result_count: int = None, charge: bool = True):
    """结束一条 query：回写 status / result_count，并按通道计费一次。

    status ∈ done|failed 时才计费；skipped / pending 不退不收。
    返回 (channel, charged)。
    """
    state_dir = Path(state_dir)
    state, path = load_state(state_dir)
    found = None
    for p in state.get("search_plans", []):
        for q in p.get("queries", []):
            if q.get("id") == qid:
                found = q
    if found is None:
        sys.exit(f"FATAL: search_plans 中不存在 query {qid}")
    found["status"] = status
    if result_count is not None:
        found["result_count"] = int(result_count)
    charged = False
    if charge and status in ("done", "failed"):
        if found.get("result_count") is None:
            sys.exit(f"FATAL: {qid} status={status} 必须同时给 result_count")
        charged = charge_query(state, qid)
    sync_budget(state)
    save_state(path, state)
    return found.get("channel"), charged


def executable_queries(state: dict):
    """还能执行的 query：status pending 且所属通道仍有 query 额度。"""
    counts = derived_query_counts(state)
    by_ch = state.get("search_budget", {}).get("by_channel", {})
    out = []
    for p in state.get("search_plans", []):
        for q in p.get("queries", []):
            if (q.get("status") or "pending") != "pending":
                continue
            ch = q.get("channel")
            cap = by_ch.get(ch, {}).get("max_queries", 0)
            if counts.get(ch, 0) < cap:
                out.append((p.get("claim_id"), q))
    return out


def consume_budget(state_dir, channel: str, queries: int = 0, results: int = 0) -> dict:
    """累加某通道消耗。results 走这里；**queries 只能由 charge_query 计费**。

    超上限抛 ValueError，调用方负责转成通道不可用或中止。
    """
    state, path = load_state(Path(state_dir))
    b = state.setdefault("search_budget", {}).setdefault("by_channel", {})
    cur = b.setdefault(channel, {"max_queries": 0, "max_results": 0, "queries": 0, "results": 0})
    if queries:
        raise ValueError("query 计数已改为按 executed_queries 收据派生，请改用 charge_query / mark-query")
    nq, nr = cur.get("queries", 0) + queries, cur.get("results", 0) + results
    if nq > cur.get("max_queries", 0):
        raise ValueError(f"{channel}: queries {nq} 超过上限 {cur.get('max_queries')}")
    if nr > cur.get("max_results", 0):
        raise ValueError(f"{channel}: results {nr} 超过上限 {cur.get('max_results')}")
    cur["results"] = nr
    sync_budget(state)
    save_state(path, state)
    return dict(cur)


def mark_unavailable(state_dir, channel: str, reason: str):
    """通道失败 → 写入 unavailable_channels。禁止把它推导为「无相关工作」。"""
    state, path = load_state(Path(state_dir))
    state.setdefault("unavailable_channels", []).append({
        "channel": channel, "reason": reason, "attempted_at": now_iso(),
    })
    save_state(path, state)


def title_key(title: str) -> str:
    """标题归一化，用于跨源去重（同一篇论文在 arXiv / OpenAlex 的 URL 不同但标题相同）。"""
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (title or "").lower())[:80]


def append_evidence(state_dir, items: list, channel: str, query_id: str = None):
    """去重后追加到 evidence.jsonl，分配 E 编号并记 results 消耗。

    去重键 = 归一化 URL ∪ 归一化标题（命中任一即丢弃）。
    **query 计数不由本函数负责**——调用方必须用 finish_query / mark-query 计费。
    返回 (added, skipped)。
    """
    if query_id:
        for it in items:
            it.setdefault("query_id", query_id)
    state_dir = Path(state_dir)
    existing, _ = load_evidence(state_dir)
    seen_url, seen_title = set(), set()
    for e in existing:
        u = normalize_url(e.get("url", ""))
        t = title_key(e.get("title", ""))
        if u:
            seen_url.add(u)
        if t:
            seen_title.add(t)
    nums = [int(m.group(1)) for e in existing
            if (m := re.match(r"^E(\d+)$", str(e.get("id", ""))))]
    next_n = (max(nums) + 1) if nums else 1

    added, skipped = [], []
    for it in items:
        u = normalize_url(it.get("url", ""))
        t = title_key(it.get("title", ""))
        if (not u and not t) or (u and u in seen_url) or (t and t in seen_title):
            skipped.append(it.get("url", "") or it.get("title", ""))
            continue
        if u:
            seen_url.add(u)
        if t:
            seen_title.add(t)
        it = dict(it)
        it["id"] = f"E{next_n}"
        next_n += 1
        it.setdefault("retrieved_at", now_iso())
        it.setdefault("changes_judgment", False)
        added.append(it)

    if channel:
        # 先记账再落盘：额度不足时一条都不写，避免「有证据但没记消耗」
        consume_budget(state_dir, channel, results=len(added))
    if added:
        with open(state_dir / "evidence.jsonl", "a", encoding="utf-8") as f:
            for it in added:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
    return added, skipped


# --------------------------------------------------------------------------
# 语义交叉校验
# --------------------------------------------------------------------------
def cross_check(state: dict, evidence: list, errors: list, warnings: list):
    claim_ids = [c.get("id") for c in state.get("claims", [])]
    ev_ids = [e.get("id") for e in evidence]
    judgment_claims = [j.get("claim_id") for j in state.get("judgments", [])]

    for name, ids in (("claim", claim_ids), ("evidence", ev_ids), ("judgment", judgment_claims),
                      ("prior_art", [p.get("id") for p in state.get("prior_art", [])])):
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            errors.append(f"$.{name}s: id 重复 {sorted(dup)}")

    for e in evidence:
        for cid in e.get("claim_ids", []):
            if cid not in claim_ids:
                errors.append(f"{e.get('id')}: claim_ids 引用了不存在的 {cid}")

    # evidence.query_id 必须指向 search_plans 中真实存在且已执行的 Q（回写机制的可回溯性）
    plan_q_ids = {q.get("id") for p in state.get("search_plans", []) for q in p.get("queries", [])}
    for e in evidence:
        qid = e.get("query_id")
        if qid and qid not in plan_q_ids:
            errors.append(f"{e.get('id')}: query_id {qid} 在 search_plans 中不存在")
    for p in state.get("search_plans", []):
        for q in p.get("queries", []):
            if q.get("status") in ("done", "failed") and not q.get("result_count"):
                errors.append(f"{q.get('id')}: status={q.get('status')} 但缺 result_count")
    # query 记账：收据 → 派生计数，双向一致
    plan_map = {q.get("id"): q for p in state.get("search_plans", []) for q in p.get("queries", [])}
    for qid in state.get("search_budget", {}).get("executed_queries", []):
        if qid not in plan_map:
            errors.append(f"budget.executed_queries: {qid} 在 search_plans 中不存在")
    derived = derived_query_counts(state)
    for ch, expect in derived.items():
        got = state.get("search_budget", {}).get("by_channel", {}).get(ch, {}).get("queries")
        if got is not None and got != expect:
            errors.append(f"budget.{ch}: queries={got} 与收据派生值 {expect} 不一致（禁止手写计数）")
    for qid, q in plan_map.items():
        if q.get("status") in ("done", "failed") and \
                qid not in state.get("search_budget", {}).get("executed_queries", []):
            warnings.append(f"{qid}: status={q.get('status')} 但未计费（走 mark-query 才会记账）")
    for c in state.get("claims", []):
        for eid in c.get("evidence_ids", []):
            if eid not in ev_ids:
                errors.append(f"{c.get('id')}: evidence_ids 引用了不存在的 {eid}")
        if c.get("confidence", 0) > 0 and not c.get("evidence_ids"):
            errors.append(f"{c.get('id')}: confidence > 0 但无关联 Evidence")

    for j in state.get("judgments", []):
        if j.get("claim_id") not in claim_ids:
            errors.append(f"judgment: claim_id {j.get('claim_id')} 不存在")
        if j.get("status") != "insufficient_evidence" and not (
            j.get("supporting_evidence_ids") or j.get("contradicting_evidence_ids")
        ):
            errors.append(f"judgment[{j.get('claim_id')}]: status={j.get('status')} 但无任何 evidence_ids")
        for eid in j.get("supporting_evidence_ids", []) + j.get("contradicting_evidence_ids", []):
            if eid not in ev_ids:
                errors.append(f"judgment[{j.get('claim_id')}]: evidence id {eid} 不存在")

    # budget
    budget = state.get("search_budget", {})
    total_q = total_r = 0
    for ch, b in budget.get("by_channel", {}).items():
        total_q += b.get("queries", 0)
        total_r += b.get("results", 0)
        if b.get("queries", 0) > b.get("max_queries", 0):
            errors.append(f"budget.{ch}: queries {b['queries']} 超过上限 {b['max_queries']}")
        if b.get("results", 0) > b.get("max_results", 0):
            errors.append(f"budget.{ch}: results {b['results']} 超过上限 {b['max_results']}")
    used = budget.get("used", {})
    if used.get("queries", 0) != total_q:
        warnings.append(f"budget.used.queries={used.get('queries', 0)} 与分通道合计 {total_q} 不一致")
    if used.get("results", 0) != total_r:
        warnings.append(f"budget.used.results={used.get('results', 0)} 与分通道合计 {total_r} 不一致")
    if total_q > budget.get("max_queries", 0):
        errors.append(f"budget: 全局 queries {total_q} 超过上限 {budget.get('max_queries')}")
    if budget.get("iterations", 0) > budget.get("max_iterations", 0):
        errors.append(f"budget: iterations 超过上限 {budget.get('max_iterations')}")

    # 引文展开缺失告警：存在高相关学术证据却从未用 seed 论文反向追踪其引用/被引。
    # 这是「关键词召回唯一入口」失败的典型信号——一个方向摸到高相关 seed 后须补 cites: 检索。
    cit_forms = ("cites:", "referenced_works:", "cited_by:")
    has_cit_query = any(
        str(q.get("query", "")).startswith(cit_forms)
        for p in state.get("search_plans", []) for q in p.get("queries", [])
    )
    has_hot_academic = any(
        e.get("channel") == "academic" and e.get("relevance", 0) >= 0.8
        for e in evidence
    )
    if has_hot_academic and not has_cit_query:
        warnings.append("存在 relevance>=0.8 的学术证据但 search_plans 无引文展开(cites:)检索 —— "
                        "建议对高相关 seed 补一次 citations / referenced_works 反向追踪")

    # 未裁决的 high claim 只提示，不阻断
    if state.get("status") in ("analyzed", "reported"):
        undecided = [c["id"] for c in state.get("claims", [])
                     if c.get("importance") == "high" and c["id"] not in judgment_claims]
        if undecided:
            warnings.append(f"进入 {state['status']} 阶段但 high Claim 未裁决: {undecided}")


def check_stage(state: dict, stage: int, errors: list):
    claims = state.get("claims", [])
    if stage >= 1:
        if len(claims) < 5:
            errors.append(f"stage 1 出口: Claim 数量 {len(claims)} < 5")
        types = {c.get("type") for c in claims}
        if len(types) < 3:
            errors.append(f"stage 1 出口: type 覆盖 {len(types)} 种 < 3（{sorted(types)}）")
        if sum(1 for c in claims if c.get("importance") == "high") < 2:
            errors.append("stage 1 出口: importance=high 的 Claim 少于 2 条")
    if stage >= 2:
        planned = {}
        for p in state.get("search_plans", []):
            for q in p.get("queries", []):
                planned[q.get("channel")] = planned.get(q.get("channel"), 0) + 1
        caps = state.get("search_budget", {}).get("by_channel", {})
        for ch, n in planned.items():
            cap = caps.get(ch, {}).get("max_queries", 0)
            if n > cap:
                errors.append(f"stage 2 出口: {ch} 计划 query {n} 条超过额度 {cap}")
        ids = [q.get("id") for p in state.get("search_plans", []) for q in p.get("queries", [])]
        if len(ids) != len(set(ids)):
            errors.append("stage 2 出口: query id 重复")
        for c in claims:
            if c.get("importance") == "high":
                qs = []
                for p in state.get("search_plans", []):
                    if p.get("claim_id") == c["id"]:
                        qs = p.get("queries", [])
                channels = {q.get("channel") for q in qs}
                if len(qs) < 3:
                    errors.append(f"stage 2 出口: {c['id']} 只有 {len(qs)} 条 query (<3)")
                elif len(channels) < 2:
                    errors.append(f"stage 2 出口: {c['id']} 的 query 未跨通道")
    if stage >= 4:
        judged = {j.get("claim_id") for j in state.get("judgments", [])}
        for c in claims:
            if c.get("importance") == "high" and c["id"] not in judged:
                errors.append(f"stage 4 出口: high Claim {c['id']} 未裁决")
    if stage >= 5:
        if not state.get("prior_art"):
            errors.append("stage 5 出口: prior_art 为空")
        novelty = state.get("analysis", {}).get("novelty", {})
        if novelty and not novelty.get("because"):
            errors.append("stage 5 出口: novelty 缺少 because")
    if stage >= 6:
        rec = state.get("recommendation", {})
        if not rec.get("based_on_claim_ids"):
            errors.append("stage 6 出口: recommendation 缺少 based_on_claim_ids")


# --------------------------------------------------------------------------
# saturation
# --------------------------------------------------------------------------
def saturation_rows(state: dict, evidence: list, th=None):
    th = th or dict(SATURATION_DEFAULTS)
    min_ind = th["min_independent"]
    max_rounds = th["max_rounds_without_change"]
    dup_th = th["duplicate_rate"]
    rows = []
    for c in state.get("claims", []):
        cid = c["id"]
        evs = [e for e in evidence if cid in e.get("claim_ids", [])]
        urls = [e.get("url", "") for e in evs]
        n = len(evs)
        independent = len({
            (e.get("source") or urlparse(e.get("url", "")).netloc, e.get("source_type"))
            for e in evs
        })
        dup_rate = 0.0 if n == 0 else round(1 - len(set(urls)) / n, 3)
        rounds = state.get("saturation", {}).get(cid, {}).get("rounds_without_change", 0)
        stopped = state.get("saturation", {}).get(cid, {}).get("stopped", False)
        # 低相关老文告警：某个方向出现一批 relevance 低、年份老的工作本身是信号——
        # 说明该交叉方向历史悠久，通常会有近作，逐条结案(<0.6 排除)前应追问一次近年检索。
        this_year = datetime.now().year
        old_low = [
            e for e in evs
            if e.get("relevance", 1.0) < 0.6 and (e.get("publication_year") or 0) <= this_year - 8
        ]
        old_low_cnt = len(old_low)
        flags = []
        if independent >= min_ind:
            flags.append(f"independence>={min_ind}")
        if rounds >= max_rounds:
            flags.append(f"no_change>={max_rounds}")
        if dup_rate > dup_th:
            flags.append(f"dup>{dup_th}")
        if old_low_cnt >= 2:
            flags.append(f"old_low_rel>={old_low_cnt}")
        if stopped:
            flags.append("marked_stopped")
        if old_low_cnt >= 2 and not stopped:
            flags.append("ADVISE:query_recent_work")
        rows.append({
            "claim_id": cid,
            "evidence": n,
            "independent": independent,
            "changes_judgment": sum(1 for e in evs if e.get("changes_judgment")),
            "duplicate_rate": dup_rate,
            "rounds_without_change": rounds,
            "old_low_rel": old_low_cnt,
            "saturated": bool(flags),
            "flags": flags,
        })
    return rows


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------
def cmd_init(args):
    title = args.idea.strip().splitlines()[0][:80] if args.idea else "untitled-idea"
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", title.lower()).strip("-") or "idea"
    slug = slug[:60]
    state_dir = Path(args.root) / slug
    state_dir.mkdir(parents=True, exist_ok=True)
    with open(TEMPLATE, encoding="utf-8") as f:
        state = json.load(f)
    name = args.profile or load_profiles().get("default", "standard")
    apply_profile(state, name)
    state["idea"] = {"title": title, "raw": args.idea, "slug": slug, "domain": args.domain or "",
                     "constraints": []}
    state["created_at"] = now_iso()
    save_state(state_dir / "research-state.json", state)
    (state_dir / "evidence.jsonl").touch()
    print(str(state_dir))


def cmd_profiles(args):
    cfg = load_profiles()
    default = cfg.get("default", "standard")
    print(f"{'profile':<10}{'iter':>5}{'queries':>8}  by_channel (q/r)"
          f"{'':>4}saturation (indep/rounds/dup)")
    for name in PROFILE_NAMES:
        p = cfg["profiles"][name]
        chans = "  ".join(f"{ch[:4]}{p['by_channel'][ch]['max_queries']}/"
                          f"{p['by_channel'][ch]['max_results']}" for ch in CHANNELS)
        s = p["saturation"]
        mark = "*" if name == default else " "
        print(f"{name + mark:<10}{p['max_iterations']:>5}{p['max_queries']:>8}  {chans}  "
              f"{s['min_independent']}/{s['max_rounds_without_change']}/{s['duplicate_rate']}")
    print(f"\n* = default（init 不带 --profile 时使用）")
    for name in PROFILE_NAMES:
        print(f"  {name}: {cfg['profiles'][name]['description']}")
    return 0


def cmd_check(args):
    state_dir = Path(args.dir)
    state, state_path = load_state(state_dir)
    evidence, bad_lines = load_evidence(state_dir)

    v = Validator(SCHEMA_DIR)
    errors = list(bad_lines)
    errors += v.validate(state, v.load("research-state.json"))
    for e in evidence:
        errors += v.validate(e, v.load("evidence.json"), path=f"$.evidence[{e.get('id', '?')}]")

    warnings = []
    cross_check(state, evidence, errors, warnings)
    if args.stage is not None:
        check_stage(state, args.stage, errors)

    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors, "warnings": warnings},
                         ensure_ascii=False, indent=2))
    else:
        for w in warnings:
            print(f"WARN : {w}")
        for e in errors:
            print(f"ERROR: {e}")
        print(f"--- check {'PASS' if not errors else 'FAIL'} "
              f"({len(errors)} error, {len(warnings)} warning, {len(evidence)} evidence) ---")
    return 0 if not errors else 1


def cmd_budget(args):
    state, _ = load_state(Path(args.dir))
    b = state.get("search_budget", {})
    print(f"iterations  {b.get('iterations', 0)}/{b.get('max_iterations')}")
    print(f"queries     {b.get('used', {}).get('queries', 0)}/{b.get('max_queries')}")
    print(f"{'channel':<10}{'queries':>12}{'results':>14}")
    for ch in CHANNELS:
        c = b.get("by_channel", {}).get(ch, {})
        print(f"{ch:<10}{str(c.get('queries', 0)) + '/' + str(c.get('max_queries', 0)):>12}"
              f"{str(c.get('results', 0)) + '/' + str(c.get('max_results', 0)):>14}")
    if state.get("unavailable_channels"):
        print("unavailable:")
        for u in state["unavailable_channels"]:
            print(f"  - {u.get('channel')}: {u.get('reason')}")
    return 0


def cmd_saturation(args):
    state, _ = load_state(Path(args.dir))
    evidence, _bad = load_evidence(Path(args.dir))
    th, from_profile = saturation_thresholds(state)
    if not from_profile:
        print(f"NOTE: state 未记录 saturation 阈值（profile 字段缺失），"
              f"按默认判据判定: independent>={th['min_independent']} "
              f"no_change>={th['max_rounds_without_change']} dup>{th['duplicate_rate']}")
    rows = saturation_rows(state, evidence, th)
    print(f"{'claim':<8}{'ev':>4}{'indep':>7}{'chg':>5}{'dup':>7}{'oldLR':>7}{'rounds':>8}  flags")
    for r in rows:
        print(f"{r['claim_id']:<8}{r['evidence']:>4}{r['independent']:>7}{r['changes_judgment']:>5}"
              f"{r['duplicate_rate']:>7}{r['old_low_rel']:>7}{r['rounds_without_change']:>8}  "
              f"{'SATURATED ' if r['saturated'] else '-'}{','.join(r['flags'])}")
    return 0


def cmd_mark_query(args):
    """执行后回写某条 query 的状态，并按所属通道计费一次。

    这是 query 计数的**唯一入口**：同一 Q 重复 mark 不重复计费（幂等），
    执行失败同样留下收据——「配额花在哪条 query 上」全程可回溯。
    诊断复盘发现过这类故障：query 全部停在 `pending`，无法证明到底跑没跑。
    """
    try:
        ch, charged = finish_query(args.dir, args.id, args.status, args.result_count)
    except ValueError as e:
        sys.exit(f"FATAL: {e}")
    print(f"{args.id} -> {args.status} channel={ch} "
          f"{'[charged]' if charged else '[already-charged]'}"
          + (f" result_count={args.result_count}" if args.result_count is not None else ""))
    return 0


def cmd_next_query(args):
    """挑下一条可执行的 query：pending 且所属通道还有 query 额度。"""
    state, _path = load_state(Path(args.dir))
    pend = executable_queries(state)
    if args.channel:
        pend = [(cid, q) for cid, q in pend if q.get("channel") == args.channel]
    if not pend:
        print("NO_EXECUTABLE_QUERY: 没有 pending query，或涉及通道的 query 额度已耗尽")
        return 1
    cid, q = pend[0]
    counts = derived_query_counts(state)
    cap = state.get("search_budget", {}).get("by_channel", {}).get(q["channel"], {}).get("max_queries", 0)
    print(f"{q['id']}  claim={cid}  channel={q['channel']}  "
          f"budget={counts.get(q['channel'], 0)}/{cap}")
    if args.json:
        print(json.dumps({"claim_id": cid, **q}, ensure_ascii=False))
    else:
        print(q["query"])
    return 0


def _upsert_key(item) -> str:
    """upsert 键：`id`，没有则用 `claim_id`（judgment 没有独立 id，按 claim 唯一）。"""
    if isinstance(item, dict):
        return item.get("id") or item.get("claim_id") or ""
    return ""


def _upsert_list(cur: list, incoming: list) -> list:
    """按 upsert 键合并：已存在则合并字段，否则追加。无键的项一律追加。"""
    out = list(cur)
    index = {_upsert_key(it): i for i, it in enumerate(out) if _upsert_key(it)}
    for it in incoming:
        key = _upsert_key(it)
        if key and key in index:
            i = index[key]
            out[i] = {**out[i], **it}
        else:
            out.append(it)
    return out


def merge_state(state: dict, patch: dict) -> dict:
    """合并局部状态。语义：dict 深合并；list 按 id upsert；其余覆盖。

    数组型字段（如 evidence_ids）整体替换，不做元素级合并——调用方传全量。
    """
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(state.get(k), dict):
            merge_state(state[k], v)
        elif isinstance(v, list) and isinstance(state.get(k), list):
            state[k] = _upsert_list(state[k], v)
        else:
            state[k] = v
    return state


def cmd_merge(args):
    """Stage 4/5/6 的通用写回：合并局部 state 后整体校验，不通过不落盘。"""
    state_dir = Path(args.dir)
    state, path = load_state(state_dir)
    try:
        patch = json.loads(args.data)
    except json.JSONDecodeError as e:
        sys.exit(f"FATAL: --data 不是合法 JSON: {e.msg}")
    if not isinstance(patch, dict):
        sys.exit("FATAL: --data 必须是 JSON 对象")

    errs = Validator(SCHEMA_DIR).validate(merge_state(state, patch),
                                          Validator(SCHEMA_DIR).load("research-state.json"))
    if errs:
        for e in errs:
            print(f"ERROR: {e}")
        return 1
    sync_budget(state)  # merge 可能带入 search_plans，重算派生计数防漂移
    save_state(path, state)
    print(f"merged: {sorted(patch)}")
    return 0


def cmd_set_evidence(args):
    """归一化阶段用：就地更新某条 Evidence 的字段（去重后仍需校准 relevance / strength 等）。

    先合并再整体校验，校验不过不落盘。
    """
    state_dir = Path(args.dir)
    load_state(state_dir)  # 确认 state 存在
    items, bad = load_evidence(state_dir)
    if bad:
        sys.exit("FATAL: evidence.jsonl 存在非法行，先手动修: " + "; ".join(bad))
    try:
        patch = json.loads(args.data)
    except json.JSONDecodeError as e:
        sys.exit(f"FATAL: --data 不是合法 JSON: {e.msg}")

    hit = 0
    for it in items:
        if it.get("id") == args.id:
            it.update(patch)
            hit += 1
    if not hit:
        sys.exit(f"FATAL: 未找到 {args.id}")

    v = Validator(SCHEMA_DIR)
    errs = []
    for it in items:
        errs += v.validate(it, v.load("evidence.json"), path=f"$.{it.get('id')}")
    if errs:
        for e in errs:
            print(f"ERROR: {e}")
        return 1

    with open(state_dir / "evidence.jsonl", "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"{args.id} 已更新: {sorted(patch)}")
    return 0


def cmd_finalize(args):
    """循环结束（预算耗尽或已达停止条件）时强制收口。

    未裁决的 Claim 一律补 `insufficient_evidence` 而非留空——禁止把「没查到」推导为「不存在」。
    幂等：已全部裁决时只把 status 推到 verified。
    """
    state_dir = Path(args.dir)
    state, path = load_state(state_dir)
    judged = {j.get("claim_id") for j in state.get("judgments", [])}

    filled = 0
    for c in state.get("claims", []):
        if c.get("id") in judged:
            continue
        state.setdefault("judgments", []).append({
            "claim_id": c["id"],
            "status": "insufficient_evidence",
            "confidence": 0.0,
            "rationale": f"{args.reason} 该 Claim 未获得可裁决的证据。",
            "supporting_evidence_ids": [],
            "contradicting_evidence_ids": [],
            "evidence_gaps": "该方向的检索未执行或未完成",
        })
        c["status"] = "insufficient_evidence"
        c["confidence"] = 0.0
        filled += 1

    state["status"] = "verified"
    errs = Validator(SCHEMA_DIR).validate(state, Validator(SCHEMA_DIR).load("research-state.json"))
    if errs:
        for e in errs:
            print(f"ERROR: {e}")
        return 1
    save_state(path, state)
    print(f"finalize: 补齐 {filled} 条未裁决 Claim（status -> verified）")
    return 0


MAX_CONTEXT_EVIDENCE = 10  # SKILL.md Hard Rules：单轮迭代最多 10 条证据摘要进上下文


def cmd_stop_check(args):
    """自动 Evidence Saturation：把已达饱和判据的 Claim 落盘为 stopped，并给出循环判决。

    判决优先级：
      1. 所有 importance=high 的 Claim 已裁决              → FINALIZE
      2. 所有 high Claim 均已饱和（stopped）                → FINALIZE
      3. 无可执行的 query（额度耗尽或没有 pending）          → FINALIZE
      4. iterations >= max_iterations                       → FINALIZE
      否则 CONTINUE，并给出下一步建议。
    """
    state_dir = Path(args.dir)
    state, path = load_state(state_dir)
    evidence, _bad = load_evidence(state_dir)
    th, from_profile = saturation_thresholds(state)
    rows = saturation_rows(state, evidence, th)

    by_id = {r["claim_id"]: r for r in rows}
    sat = state.setdefault("saturation", {})
    newly = []
    for c in state.get("claims", []):
        cid = c["id"]
        r = by_id.get(cid)
        if r and r["saturated"] and not sat.get(cid, {}).get("stopped"):
            entry = sat.setdefault(cid, {"rounds_without_change": 0})
            entry["stopped"] = True
            entry["reason"] = ",".join(r["flags"])
            newly.append(cid)

    high = [c for c in state.get("claims", []) if c.get("importance") == "high"]
    judged = {j.get("claim_id") for j in state.get("judgments", [])}
    need = [c["id"] for c in high if c["id"] not in judged]
    pend = executable_queries(state)
    iters = state.get("search_budget", {}).get("iterations", 0)
    max_iters = state.get("search_budget", {}).get("max_iterations", 0)

    if high and not need:
        verdict, reason = "FINALIZE", "所有 high Claim 已裁决"
    elif high and all(sat.get(c["id"], {}).get("stopped") for c in high):
        verdict, reason = "FINALIZE", "所有 high Claim 已达证据饱和"
    elif not pend:
        verdict, reason = "FINALIZE", "无可执行的 query（额度耗尽或无 pending）"
    elif max_iters and iters >= max_iters:
        verdict, reason = "FINALIZE", f"iterations {iters} 已达上限 {max_iters}"
    else:
        verdict = "CONTINUE"
        if newly:
            reason = f"本次新饱和 {', '.join(newly)}；仍有 {len(pend)} 条可执行 query"
        else:
            reason = f"仍有 {len(pend)} 条可执行 query，未裁决 high Claim: {', '.join(need) or '无'}"

    save_state(path, state)

    if args.json:
        print(json.dumps({"verdict": verdict, "reason": reason, "newly_stopped": newly,
                          "executable_queries": [q["id"] for _c, q in pend],
                          "rows": rows}, ensure_ascii=False, indent=2))
    else:
        if not from_profile:
            print(f"NOTE: state 未记录 saturation 阈值，按默认判据判定 "
                  f"(indep>={th['min_independent']} rounds>={th['max_rounds_without_change']} "
                  f"dup>{th['duplicate_rate']})")
        for r in rows:
            print(f"{r['claim_id']:<8}{'ev':>0}={r['evidence']:<3} "
                  f"{'STOPPED' if sat.get(r['claim_id'], {}).get('stopped') else '-':<8}"
                  f"{','.join(r['flags']) or '(未饱和)'}")
        print(f"\n{verdict}: {reason}")
    return 0


def cmd_topk(args):
    """Evidence top-k 裁剪：按 relevance 取前 k 条，供本轮进上下文（受 ≤10 条约束）。"""
    if args.k > MAX_CONTEXT_EVIDENCE:
        sys.exit(f"FATAL: k={args.k} 超过单轮上下文上限 {MAX_CONTEXT_EVIDENCE}")
    state, _path = load_state(Path(args.dir))
    evidence, _bad = load_evidence(Path(args.dir))
    rows = [e for e in evidence
            if not args.claim or args.claim in e.get("claim_ids", [])]
    rows = [e for e in rows if e.get("relevance", 0) >= args.min_relevance]
    rows.sort(key=lambda e: (-e.get("relevance", 0), -int(e.get("publication_year") or 0)))
    picked = rows[:args.k]
    print(f"# {len(picked)}/{len(rows)} selected"
          + (f"  (claim={args.claim})" if args.claim else "")
          + f"  relevance>={args.min_relevance}  k={args.k}")
    for e in picked:
        print(f"{e['id']}  rel={e.get('relevance')}  {e.get('strength','-')}/"
              f"{e.get('implementation_level','-')}  {e.get('source_type','-')}  "
              f"{str(e.get('title',''))[:56]}")
    dropped = len(rows) - len(picked)
    if dropped:
        print(f"# {dropped} 条被裁剪（未进上下文，仍在 evidence.jsonl 中可回溯）")
    return 0


def cmd_consume(args):
    try:
        cur = consume_budget(Path(args.dir), args.channel, args.queries, args.results)
    except ValueError as e:
        sys.exit(f"FATAL: {e}")
    if args.iterations:
        state, path = load_state(Path(args.dir))
        b = state["search_budget"]
        n = b.get("iterations", 0) + args.iterations
        if n > b.get("max_iterations", 0):
            sys.exit(f"FATAL: iterations {n} 超过上限 {b.get('max_iterations')}")
        b["iterations"] = n
        save_state(path, state)
        print(f"iterations -> {n}/{b.get('max_iterations')}")
        return 0
    print(f"{args.channel}: queries={cur['queries']}/{cur['max_queries']} "
          f"results={cur['results']}/{cur['max_results']}")
    return 0


def main():
    p = argparse.ArgumentParser(description="research state 校验与记账")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="从模板初始化一次调查")
    pi.add_argument("--idea", required=True)
    pi.add_argument("--domain", default="")
    pi.add_argument("--root", default="research")
    pi.add_argument("--profile", default=None,
                    help=f"预算档位，可选 {', '.join(PROFILE_NAMES)}；"
                         f"不指定则用 budget-profiles.json 的 default")
    pi.set_defaults(func=cmd_init)

    pp = sub.add_parser("profiles", help="列出可用预算档位及其额度")
    pp.set_defaults(func=cmd_profiles)

    pc = sub.add_parser("check", help="schema + 交叉引用 + budget 校验")
    pc.add_argument("dir")
    pc.add_argument("--stage", type=int, default=None)
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(func=cmd_check)

    pb = sub.add_parser("budget", help="打印预算使用")
    pb.add_argument("dir")
    pb.set_defaults(func=cmd_budget)

    ps = sub.add_parser("saturation", help="Evidence Saturation 统计")
    ps.add_argument("dir")
    ps.set_defaults(func=cmd_saturation)

    pu = sub.add_parser("consume", help="记账：累加某通道的 results 消耗（query 计数请用 mark-query）")
    pu.add_argument("dir")
    pu.add_argument("--channel", required=True, choices=CHANNELS)
    pu.add_argument("--results", type=int, default=0)
    pu.add_argument("--iterations", type=int, default=0, help="主循环迭代计数（不指定 channel 语义时用）")
    pu.set_defaults(func=cmd_consume)

    pn = sub.add_parser("next-query", help="挑下一条 pending 且所在通道仍有额度的 query")
    pn.add_argument("dir")
    pn.add_argument("--channel", choices=CHANNELS, default=None)
    pn.add_argument("--json", action="store_true")
    pn.set_defaults(func=cmd_next_query)

    pk = sub.add_parser("stop-check", help="自动 Evidence Saturation：写回 stopped 并给出循环判决")
    pk.add_argument("dir")
    pk.add_argument("--json", action="store_true")
    pk.set_defaults(func=cmd_stop_check)

    pt = sub.add_parser("topk", help="Evidence top-k 裁剪（取 relevance 最高的 k 条进上下文）")
    pt.add_argument("dir")
    pt.add_argument("--claim", default=None, help="只看落在某个 Claim 上的证据")
    pt.add_argument("--k", type=int, default=10)
    pt.add_argument("--min-relevance", type=float, default=0.6)
    pt.set_defaults(func=cmd_topk)

    pf = sub.add_parser("finalize", help="循环结束：未裁决 Claim 一律补 insufficient_evidence")
    pf.add_argument("dir")
    pf.add_argument("--reason", default="预算耗尽 / 已达停止条件：",
                    help="写入 rationale 的前缀，说明为什么没查到")
    pf.set_defaults(func=cmd_finalize)

    pe = sub.add_parser("set-evidence", help="归一化：就地更新一条 Evidence 的字段")
    pe.add_argument("dir")
    pe.add_argument("id")
    pe.add_argument("--data", required=True, help='JSON，如 \'{"relevance":0.8,"strength":"high"}\'')
    pe.set_defaults(func=cmd_set_evidence)

    pm = sub.add_parser("merge", help="合并局部 state（dict 深合并 / list 按 id upsert），校验后落盘")
    pm.add_argument("dir")
    pm.add_argument("--data", required=True, help="JSON 对象，如 '{\"judgments\":[{...}]}'")
    pm.set_defaults(func=cmd_merge)

    pmq = sub.add_parser("mark-query", help="执行后回写某 query 的 status / result_count")
    pmq.add_argument("dir")
    pmq.add_argument("--id", required=True, help="search_plans 中的 Q id")
    pmq.add_argument("--status", required=True, choices=["pending", "done", "failed", "skipped"])
    pmq.add_argument("--result-count", type=int, default=None)
    pmq.set_defaults(func=cmd_mark_query)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
