#!/usr/bin/env python3
"""_common.py — 检索脚本共用的网络层。stdlib only，零依赖。

只做一件事：把「出网」这件事封装成带回退的 http_get。
沙箱代理端口每次会话都变（只能从 env 读），因此回退链固定为：
    env 代理 → 127.0.0.1:7897（本机 Clash）→ 返回错误由调用方判定通道不可用
"""

import gzip
import json
import time
import urllib.error
import urllib.request

FALLBACK_PROXY = "http://127.0.0.1:7897"
USER_AGENT = "research-investigation/0.1"
RETRY_STATUS = (429, 503)  # 限流 / 临时不可用：退避后重试，arXiv 尤其常见


def _opener(proxy=None):
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener(urllib.request.ProxyHandler())


def http_get(url, headers=None, timeout=25, accept="application/json", retries=2):
    """返回 (body_text, err)。成功时 err 为 None。

    4xx（除 429）视为请求本身有问题，不再换代理重试；429/503 与网络错误退避重试。
    """
    hdrs = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "identity"}
    hdrs.update(headers or {})
    last_err = "unknown"
    for proxy in (None, FALLBACK_PROXY):
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, headers=hdrs)
                with _opener(proxy).open(req, timeout=timeout) as resp:
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    return raw.decode("utf-8", "replace"), None
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}"
                if e.code in RETRY_STATUS and attempt < retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                if 400 <= e.code < 500:
                    break
            except Exception as e:  # noqa: BLE001 - 网络层需要吞掉所有异常并换通道
                last_err = f"{type(e).__name__}: {e}"
                if attempt < retries:
                    time.sleep(1)
                    continue
            break
    return None, last_err


def http_get_json(url, **kw):
    text, err = http_get(url, **kw)
    if text is None:
        return None, err
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败: {e.msg}"


def now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
