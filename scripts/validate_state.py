#!/usr/bin/env python3
"""validate_state.py — Schema 校验 + budget 记账 + Evidence Saturation 统计。

stdlib only，零依赖。所有额度从 state 自身读取，脚本内不内置通道常量。

用法:
    validate_state.py init --idea "<idea 文本>" [--root research]
    validate_state.py check <state-dir> [--stage N] [--json]
    validate_state.py budget <state-dir>
    validate_state.py saturation <state-dir>
    validate_state.py consume <state-dir> --channel academic [--queries 1] [--results 12]
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from _common import now_iso

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = SKILL_ROOT / "schemas"
TEMPLATE = SKILL_ROOT / "assets" / "research-state.template.json"
CHANNELS = ("academic", "github", "web", "product")


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


def consume_budget(state_dir, channel: str, queries: int = 0, results: int = 0) -> dict:
    """累加某通道消耗。超上限抛 ValueError，调用方负责转成通道不可用或中止。"""
    state, path = load_state(Path(state_dir))
    b = state.setdefault("search_budget", {}).setdefault("by_channel", {})
    cur = b.setdefault(channel, {"max_queries": 0, "max_results": 0, "queries": 0, "results": 0})
    nq, nr = cur.get("queries", 0) + queries, cur.get("results", 0) + results
    if nq > cur.get("max_queries", 0):
        raise ValueError(f"{channel}: queries {nq} 超过上限 {cur.get('max_queries')}")
    if nr > cur.get("max_results", 0):
        raise ValueError(f"{channel}: results {nr} 超过上限 {cur.get('max_results')}")
    cur["queries"], cur["results"] = nq, nr
    used = state["search_budget"].setdefault("used", {"queries": 0, "results": 0})
    used["queries"] = sum(c.get("queries", 0) for c in b.values())
    used["results"] = sum(c.get("results", 0) for c in b.values())
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


def append_evidence(state_dir, items: list, channel: str, queries: int = 0):
    """去重后追加到 evidence.jsonl，分配 E 编号并记账。

    去重键 = 归一化 URL ∪ 归一化标题（命中任一即丢弃）。
    返回 (added, skipped_urls)。不传 channel 则不记账。
    """
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
        consume_budget(state_dir, channel, queries=queries, results=len(added))
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
def saturation_rows(state: dict, evidence: list):
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
        flags = []
        if independent >= 3:
            flags.append("independence>=3")
        if rounds >= 2:
            flags.append("no_change>=2")
        if dup_rate > 0.6:
            flags.append("dup>0.6")
        if stopped:
            flags.append("marked_stopped")
        rows.append({
            "claim_id": cid,
            "evidence": n,
            "independent": independent,
            "changes_judgment": sum(1 for e in evs if e.get("changes_judgment")),
            "duplicate_rate": dup_rate,
            "rounds_without_change": rounds,
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
    state["idea"] = {"title": title, "raw": args.idea, "slug": slug, "domain": args.domain or "",
                     "constraints": []}
    state["created_at"] = now_iso()
    save_state(state_dir / "research-state.json", state)
    (state_dir / "evidence.jsonl").touch()
    print(str(state_dir))


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
    rows = saturation_rows(state, evidence)
    print(f"{'claim':<8}{'ev':>4}{'indep':>7}{'chg':>5}{'dup':>7}{'rounds':>8}  flags")
    for r in rows:
        print(f"{r['claim_id']:<8}{r['evidence']:>4}{r['independent']:>7}{r['changes_judgment']:>5}"
              f"{r['duplicate_rate']:>7}{r['rounds_without_change']:>8}  "
              f"{'SATURATED ' if r['saturated'] else '-'}{','.join(r['flags'])}")
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
    pi.set_defaults(func=cmd_init)

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

    pu = sub.add_parser("consume", help="记账：累加某通道的 query / result 消耗")
    pu.add_argument("dir")
    pu.add_argument("--channel", required=True, choices=CHANNELS)
    pu.add_argument("--queries", type=int, default=0)
    pu.add_argument("--results", type=int, default=0)
    pu.add_argument("--iterations", type=int, default=0, help="主循环迭代计数（不指定 channel 语义时用）")
    pu.set_defaults(func=cmd_consume)

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

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
