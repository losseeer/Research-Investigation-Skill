#!/usr/bin/env python3
"""search_github.py — github_search 通道：GitHub Search API → 候选 Evidence。

用法:
    search_github.py --query "llm agent itinerary planning" [--max-results 10]
                     [--min-stars 0] [--state-dir research/<slug>] [--claim-ids C3]

未认证限额 10 req/min、core 60/hr；设置 GITHUB_TOKEN 可提额，
此时脚本会把 state 里 github 通道的 max_queries 提到 20。

仓库只能证明「有代码」，因此 implementation_level 一律为 code —— 升级到
prototype / production / commercial_product 需要额外证据，由归一化阶段判定。
"""

import argparse
import json
import os
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_state as vs  # noqa: E402
from _common import http_get_json, now_iso  # noqa: E402

API = "https://api.github.com/search/repositories"
TOKEN_CAP = 20


def from_repo(r: dict, claim_ids) -> dict:
    stars = r.get("stargazers_count") or 0
    desc = (r.get("description") or "").strip()
    topics = ", ".join((r.get("topics") or [])[:6])
    pushed = (r.get("pushed_at") or "")[:10]
    lang = r.get("language") or ""
    return {
        "channel": "github",
        "source_type": "github",
        "title": r.get("full_name") or "",
        "url": r.get("html_url") or "",
        "source": (r.get("owner") or {}).get("login") or "",
        "publication_year": int(r.get("created_at", "0000")[:4]) if r.get("created_at") else None,
        "summary": (f"★{stars} · {lang} · pushed {pushed}"
                    + (f" · topics: {topics}" if topics else "")
                    + (f". {desc}" if desc else ""))[:600],
        "evidence": desc,
        "claim_ids": claim_ids,
        "relevance": 0.5,
        "strength": "high" if stars >= 500 else "medium",
        "implementation_level": "code",
        "changes_judgment": False,
        "retrieved_at": now_iso(),
    }


def main():
    p = argparse.ArgumentParser(description="GitHub 检索 → 候选 Evidence")
    p.add_argument("--query", required=True)
    p.add_argument("--max-results", type=int, default=10)
    p.add_argument("--min-stars", type=int, default=0)
    p.add_argument("--state-dir", default="")
    p.add_argument("--claim-ids", default="")
    p.add_argument("--query-id", default="",
                   help="search_plans 中对应的 Q id；传了 --state-dir 就必须传，用于 query 级记账")
    args = p.parse_args()

    if args.state_dir and not args.query_id:
        print("FATAL: 传了 --state-dir 就必须传 --query-id（配额按 planned query 记账）",
              file=sys.stderr)
        return 1

    claim_ids = [c.strip() for c in args.claim_ids.split(",") if c.strip()]

    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        if args.state_dir:
            state, path = vs.load_state(Path(args.state_dir))
            cap = state["search_budget"]["by_channel"]["github"]
            if cap.get("max_queries", 0) < TOKEN_CAP:
                cap["max_queries"] = TOKEN_CAP
                vs.save_state(path, state)
                print(f"GITHUB_TOKEN detected: github max_queries -> {TOKEN_CAP}")

    q = args.query + (f" stars:>={args.min_stars}" if args.min_stars else "")
    url = API + "?" + urllib.parse.urlencode({
        "q": q, "per_page": min(args.max_results, 30), "sort": "stars", "order": "desc",
    })

    data, err = http_get_json(url, headers=headers)
    if data is None:
        if args.state_dir:
            vs.mark_unavailable(args.state_dir, "github", str(err))
        print(f"FATAL: github 检索失败 -> {err}", file=sys.stderr)
        return 1

    candidates = [from_repo(r, claim_ids) for r in (data.get("items") or [])]

    if not args.state_dir:
        print(json.dumps(candidates, ensure_ascii=False, indent=2))
        return 0

    try:
        added, skipped = vs.append_evidence(args.state_dir, candidates, "github",
                                            query_id=args.query_id)
    except ValueError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        _finish(args.state_dir, args.query_id, "failed", 0)
        return 1
    charged = _finish(args.state_dir, args.query_id, "done", len(added))
    print(f"query {args.query_id}: added {len(added)} / skipped {len(skipped)} (dup)"
          f"  [{'charged' if charged else 'already-charged'}]"
          + (f" -> {[a['id'] for a in added]}" if added else ""))
    return 0


def _finish(state_dir, qid, status, result_count):
    """统一收口：回写 query 状态并按所属通道计费一次（同一 Q 幂等）。"""
    try:
        _ch, charged = vs.finish_query(state_dir, qid, status, result_count)
        return charged
    except ValueError as e:  # 该通道 query 额度已耗尽
        print(f"FATAL: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    sys.exit(main())
