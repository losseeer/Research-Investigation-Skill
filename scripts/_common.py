#!/usr/bin/env python3
"""_common.py — 检索脚本共用的网络层。stdlib only，零依赖。

三件事：
  1. 出网封装成带回退的 http_get（沙箱代理端口每次会话都变，只能从 env 读）
  2. Fetch 限制：单次响应体字节上限 + 单 query 取回条数上限
  3. 磁盘缓存：同一 URL 在 TTL 内不重复抓取

回退链：env 代理 → 127.0.0.1:7897（本机 Clash）→ 返回错误由调用方判定通道不可用。
失败一律显式返回 err，不做「截断后当正常结果用」这类静默降级。
"""

import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FALLBACK_PROXY = "http://127.0.0.1:7897"
USER_AGENT = "research-investigation/0.1"

# 限流 / 临时不可用：退避后重试（arXiv、OpenAlex 尤其常见）
RETRY_STATUS = (429, 500, 502, 503, 504)
# 这几个状态码可能是**代理层**拒绝（沙箱代理是域名白名单），换个出口有可能就通了
PROXY_RETRY_STATUS = (403, 407, 408)

MAX_RESPONSE_BYTES = 2_000_000      # 单次响应体上限：超出整体丢弃，不截断后当正常结果用
MAX_RESULTS_PER_QUERY = 30          # 单条 query 取回条数硬上限（--max-results 会被夹到这里）
DEFAULT_CACHE_TTL_HOURS = 24        # 缓存有效期；过期静默重抓，缓存只是省一次网络

BACKOFF_BASE = 2.0                  # 退避：2s → 4s → 8s …
BACKOFF_MAX = 16.0


def _sleep(seconds):
    """退避等待。单独提出来，测试里替换掉，不真睡。"""
    time.sleep(seconds)


def _opener(proxy=None):
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener(urllib.request.ProxyHandler())


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def clamp_results(n) -> int:
    """单条 query 的取回条数硬上限。调大 --max-results 也不会真的去抓更多。"""
    return max(1, min(int(n), MAX_RESULTS_PER_QUERY))


def _backoff(attempt: int) -> float:
    return min(BACKOFF_BASE * (2 ** attempt), BACKOFF_MAX)


# --------------------------------------------------------------------------
# 缓存
# --------------------------------------------------------------------------
def _cache_path(cache_dir, url) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return Path(cache_dir) / f"{digest}.json"


def _cache_read(cache_dir, url, ttl_hours):
    """命中且未过期 → 返回 {"body", "fetched_at"}；否则 None（含缓存损坏的情况）。"""
    if not cache_dir:
        return None
    try:
        rec = json.loads(_cache_path(cache_dir, url).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if rec.get("url") != url:
        return None
    age_h = (time.time() - float(rec.get("fetched_epoch") or 0)) / 3600.0
    if age_h > ttl_hours:
        return None
    return {"body": rec.get("body") or "", "fetched_at": rec.get("fetched_at") or now_iso()}


def _cache_write(cache_dir, url, body):
    if not cache_dir:
        return
    try:
        p = _cache_path(cache_dir, url)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"url": url, "fetched_at": now_iso(), "fetched_epoch": time.time(),
                                 "body": body}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # 缓存写不进去不影响主流程，但不能因此把抓取判成失败


# --------------------------------------------------------------------------
# 抓取
# --------------------------------------------------------------------------
def _try_proxy(url, hdrs, timeout, proxy, retries, max_bytes):
    """在单个出口上试。返回 (body, err, attempts, fatal)。

    fatal=True 表示换出口也没用（请求本身的问题 / 响应体过大），不再走回退链。
    """
    err = "unknown"
    attempts = 0
    for attempt in range(retries + 1):
        attempts += 1
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with _opener(proxy).open(req, timeout=timeout) as resp:
                declared = resp.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    return None, f"响应体过大：Content-Length {declared} > {max_bytes} bytes", \
                        attempts, True
                # 多读 1 字节只为判断超限：超限就整体丢弃，绝不截断后当正常结果用
                raw = resp.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    return None, f"响应体过大：>{max_bytes} bytes（整体丢弃）", attempts, True
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace"), None, attempts, False
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if e.code in RETRY_STATUS and attempt < retries:
                _sleep(_backoff(attempt))
                continue
            if e.code in PROXY_RETRY_STATUS:
                return None, err, attempts, False      # 可能是代理层拒绝，换出口再试
            if 400 <= e.code < 500 and e.code not in RETRY_STATUS:
                return None, err, attempts, True       # 请求本身的问题，换出口也没用
            # 429 / 5xx 重试耗尽：换个出口还有可能通（限流常是出口 IP 级的）
            return None, err, attempts, False
        except Exception as e:  # noqa: BLE001 - 网络层需要吞掉所有异常并换通道
            err = f"{type(e).__name__}: {e}"
            if attempt < retries:
                _sleep(_backoff(attempt))
                continue
            return None, err, attempts, False
    return None, err, attempts, False


def http_get(url, headers=None, timeout=25, accept="application/json", retries=2,
             max_bytes=MAX_RESPONSE_BYTES, cache_dir=None, ttl_hours=DEFAULT_CACHE_TTL_HOURS,
             stats=None):
    """返回 (body_text, err)。成功时 err 为 None。

    - 4xx（除 429 / 403 / 407 / 408）视为请求本身有问题，不重试也不换代理。
    - 429/5xx 与网络错误：指数退避重试，再换回退代理。
    - `stats`（可选 dict）回填来源：`source`（network / cache）、`attempts`、`bytes`、
      `fetched_at`。**缓存命中时 `fetched_at` 是当初抓取的时间**，不是本次运行时间——
      否则 evidence.retrieved_at 会永远显示「刚刚」，旧快照检测就成了摆设。
    """
    if stats is None:
        stats = {}
    cached = _cache_read(cache_dir, url, ttl_hours)
    if cached is not None:
        stats.update({"source": "cache", "attempts": 0, "bytes": len(cached["body"]),
                      "fetched_at": cached["fetched_at"]})
        return cached["body"], None

    hdrs = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "identity"}
    hdrs.update(headers or {})

    last_err = "unknown"
    total_attempts = 0
    for proxy in (None, FALLBACK_PROXY):
        body, err, attempts, fatal = _try_proxy(url, hdrs, timeout, proxy, retries, max_bytes)
        total_attempts += attempts
        if body is not None:
            _cache_write(cache_dir, url, body)
            stats.update({"source": "network", "attempts": total_attempts,
                          "bytes": len(body), "fetched_at": now_iso()})
            return body, None
        last_err = err
        if fatal:
            break

    stats.update({"source": "network", "attempts": total_attempts, "bytes": 0, "fetched_at": None})
    if total_attempts > retries + 1:
        last_err = f"{last_err}（共 {total_attempts} 次尝试）"
    return None, last_err


def http_get_json(url, cache_dir=None, ttl_hours=DEFAULT_CACHE_TTL_HOURS, stats=None, **kw):
    text, err = http_get(url, cache_dir=cache_dir, ttl_hours=ttl_hours, stats=stats, **kw)
    if text is None:
        return None, err
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败: {e.msg}"
