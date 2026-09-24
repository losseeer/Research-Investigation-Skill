#!/usr/bin/env python3
"""search_academic.py — academic_search 通道：OpenAlex / Crossref / arXiv → 候选 Evidence。

用法:
    search_academic.py --query "travel itinerary planning constraint" [--source openalex]
                       [--max-results 10] [--state-dir research/<slug>] [--claim-ids C3,C4]

不传 --state-dir 时只把候选打到 stdout，不落盘、不记账（dry run）。
传了 --state-dir 时：URL 去重 → 追加 evidence.jsonl → 按通道记账 → 打印 added/skipped。

注意：OpenAlex 必须带 mailto，否则稳定 429。优先用环境变量 RESEARCH_MAILTO。
"""

import argparse
import html
import json
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_state as vs  # noqa: E402
from _common import http_get, http_get_json, now_iso  # noqa: E402

DEFAULT_MAILTO = os.environ.get("RESEARCH_MAILTO", "")
SOURCES = ("openalex", "crossref", "arxiv")
ATOM = "{http://www.w3.org/2005/Atom}"


# --------------------------------------------------------------------------
# 字段映射：各源 → 候选 Evidence
# --------------------------------------------------------------------------
def _abstract_from_inverted(inv: dict, limit=600):
    """OpenAlex 的 abstract_inverted_index 是 {词: [位置]}，需要还原语序。"""
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    text = " ".join(pos[k] for k in sorted(pos))
    return text[:limit]


def _authors(names, limit=4):
    if not names:
        return ""
    s = ", ".join(names[:limit])
    return s + (" et al." if len(names) > limit else "")


def _strip_tags(s: str) -> str:
    """去 JATS/HTML 标签 + 反转义实体（Crossref 的 abstract 常带 &amp; 之类）。"""
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip())


def from_openalex(w: dict, claim_ids) -> dict:
    inv = w.get("abstract_inverted_index") or {}
    abstract = _abstract_from_inverted(inv)
    venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    authors = _authors([(a.get("author") or {}).get("display_name", "")
                        for a in (w.get("authorships") or [])])
    cited = w.get("cited_by_count") or 0
    doi = w.get("doi") or ""
    url = doi if doi.startswith("http") else (w.get("id") or "")
    return {
        "channel": "academic",
        "source_type": "academic",
        "title": w.get("display_name") or "(untitled)",
        "url": url,
        "source": venue or "OpenAlex",
        "publication_year": w.get("publication_year"),
        "summary": (f"{authors} ({w.get('publication_year')}). {venue}. 被引 {cited}. " + abstract)[:600],
        "evidence": abstract,
        "claim_ids": claim_ids,
        "relevance": 0.5,
        "strength": "high" if cited >= 20 else "medium",
        "implementation_level": "paper",
        "changes_judgment": False,
        "retrieved_at": now_iso(),
    }


def from_crossref(it: dict, claim_ids) -> dict:
    title = _strip_tags((it.get("title") or ["(untitled)"])[0])
    venue = _strip_tags((it.get("container-title") or [""])[0])
    year = ((it.get("issued") or {}).get("date-parts") or [[None]])[0][0]
    authors = _authors([f"{a.get('given', '')} {a.get('family', '')}".strip()
                        for a in (it.get("author") or [])])
    abstract = _strip_tags(it.get("abstract") or "")
    doi = it.get("DOI") or ""
    return {
        "channel": "academic",
        "source_type": "academic",
        "title": title,
        "url": it.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
        "source": venue or "Crossref",
        "publication_year": year,
        "summary": (f"{authors} ({year}). {venue}. " + abstract)[:600],
        "evidence": abstract,
        "claim_ids": claim_ids,
        "relevance": 0.5,
        "strength": "medium",
        "implementation_level": "paper",
        "changes_judgment": False,
        "retrieved_at": now_iso(),
    }


def from_arxiv(entry, claim_ids) -> dict:
    def txt(tag, default=""):
        el = entry.find(ATOM + tag)
        return (el.text or default).strip() if el is not None else default

    abstract = _strip_tags(txt("summary"))
    authors = _authors([(a.find(ATOM + "name").text or "")
                        for a in entry.findall(ATOM + "author")
                        if a.find(ATOM + "name") is not None])
    published = txt("published")[:4]
    return {
        "channel": "academic",
        "source_type": "academic",
        "title": _strip_tags(txt("title")),
        "url": txt("id"),
        "source": "arXiv",
        "publication_year": int(published) if published.isdigit() else None,
        "summary": (f"{authors} ({published}). arXiv preprint. " + abstract)[:600],
        "evidence": abstract,
        "claim_ids": claim_ids,
        "relevance": 0.5,
        "strength": "medium",
        "implementation_level": "paper",
        "changes_judgment": False,
        "retrieved_at": now_iso(),
    }


# --------------------------------------------------------------------------
# 各源抓取
# --------------------------------------------------------------------------
def fetch_openalex(query, max_results, mailto):
    # 引文展开：query 以 cites: / referenced_works: 开头时走引文 filter，
    # 不能塞进 title_and_abstract.search（否则恒返回 0 条）。
    if query.startswith(("cites:", "referenced_works:")):
        filt = query
    else:
        # title_and_abstract.search 比 search= 精确得多：后者是全文本匹配，
        # 会混入只在参考文献里提过一次关键词的论文。
        filt = f"title_and_abstract.search:{query}"
    params = {
        "filter": filt,
        "per-page": min(max_results, 50),
        "select": "id,doi,display_name,publication_year,primary_location,cited_by_count,"
                  "authorships,abstract_inverted_index",
    }
    if mailto:
        params["mailto"] = mailto
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data, err = http_get_json(url)
    if data is None:
        return [], err
    return data.get("results", []), None


def fetch_crossref(query, max_results, mailto):
    params = {
        "query": query,
        "rows": min(max_results, 50),
        "select": "DOI,title,container-title,issued,author,abstract,URL",
    }
    if mailto:
        params["mailto"] = mailto
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    data, err = http_get_json(url)
    if data is None:
        return [], err
    return (data.get("message") or {}).get("items", []), None


def fetch_arxiv(query, max_results):
    params = {
        "search_query": f"all:{query}",
        "max_results": min(max_results, 30),
        "sortBy": "relevance",
    }
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    text, err = http_get(url, accept="application/atom+xml")
    if text is None:
        return [], err
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return [], f"arXiv XML 解析失败: {e}"
    return root.findall(ATOM + "entry"), None


def main():
    p = argparse.ArgumentParser(description="学术检索 → 候选 Evidence")
    p.add_argument("--query", required=True)
    p.add_argument("--source", default="openalex", choices=[*SOURCES, "all"])
    p.add_argument("--max-results", type=int, default=10)
    p.add_argument("--state-dir", default="")
    p.add_argument("--claim-ids", default="")
    p.add_argument("--mailto", default=DEFAULT_MAILTO)
    args = p.parse_args()

    if not args.mailto:
        print("WARN: 未提供 mailto，OpenAlex 很可能返回 429。"
              "建议设置环境变量 RESEARCH_MAILTO。", file=sys.stderr)

    claim_ids = [c.strip() for c in args.claim_ids.split(",") if c.strip()]
    sources = SOURCES if args.source == "all" else (args.source,)

    candidates, failures = [], []
    for src in sources:
        if src == "openalex":
            raw, err = fetch_openalex(args.query, args.max_results, args.mailto)
            items = [from_openalex(w, claim_ids) for w in raw]
        elif src == "crossref":
            raw, err = fetch_crossref(args.query, args.max_results, args.mailto)
            items = [from_crossref(w, claim_ids) for w in raw]
        else:
            raw, err = fetch_arxiv(args.query, args.max_results)
            items = [from_arxiv(e, claim_ids) for e in raw]

        if err:
            failures.append(f"{src}: {err}")
            print(f"WARN: {src} 失败 -> {err}", file=sys.stderr)
            continue
        candidates.extend(items)

    if args.state_dir and failures:
        vs.mark_unavailable(args.state_dir, "academic", "; ".join(failures))

    if not args.state_dir:
        print(json.dumps(candidates, ensure_ascii=False, indent=2))
        return 0

    try:
        added, skipped = vs.append_evidence(args.state_dir, candidates, "academic",
                                            queries=len(sources) - len(failures))
    except ValueError as e:  # 预算耗尽
        print(f"FATAL: {e}", file=sys.stderr)
        return 1
    print(f"added {len(added)} / skipped {len(skipped)} (dup)"
          + (f" -> {[a['id'] for a in added]}" if added else ""))
    if skipped:
        print("dup urls:", *skipped[:5], sep="\n  ", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
