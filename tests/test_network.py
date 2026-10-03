#!/usr/bin/env python3
"""网络层回归测试：Fetch 限制（字节上限 / 条数上限）+ 重试退避 + 磁盘缓存。

全部离线：`_common._opener` 与 `_common._sleep` 在测试里替换掉，不真出网、不真睡。

运行： python3 tests/test_network.py
"""

import json
import sys
import tempfile
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import _common as net  # noqa: E402


class FakeResponse:
    """够用的响应桩：支持 with、headers.get、read(n)。"""

    def __init__(self, body=b"", headers=None):
        self._body = body
        self.headers = headers or {}
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        self.reads += 1
        return self._body[:n] if n and n > 0 else self._body


class FakeOpener:
    def __init__(self, script, log):
        self.script = script          # 每次 open 取一个：FakeResponse 或 Exception
        self.log = log

    def open(self, req, timeout=None):
        self.log.append(("open", getattr(req, "full_url", str(req)), timeout))
        item = self.script.pop(0) if self.script else FakeResponse(b"{}")
        if isinstance(item, Exception):
            raise item
        return item


class NetworkTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = []
        self.slept = []
        self._opener, self._sleep = net._opener, net._sleep

    def tearDown(self):
        net._opener, net._sleep = self._opener, self._sleep
        self.tmp.cleanup()

    def _install(self, *responses):
        """把后续 open() 的返回值排好队（Exception 会被抛出）。"""
        net._opener = lambda proxy=None, _r=list(responses), _log=self.log: FakeOpener(_r, _log)
        net._sleep = lambda s: self.slept.append(s)

    def _opens(self):
        return [x for x in self.log if x[0] == "open"]


class TestFetchLimits(NetworkTestCase):
    """TODO：单次抓取的字节上限与条数上限。"""

    def test_response_over_limit_is_discarded_not_truncated(self):
        """超限整体丢弃：截断后当正常结果用是静默降级，宁可显式失败。"""
        self._install(FakeResponse(b"x" * 5000))
        body, err = net.http_get("https://example.org/big", max_bytes=100, retries=0)
        self.assertIsNone(body)
        self.assertIn("响应体过大", err)

    def test_content_length_over_limit_short_circuits(self):
        """声明了 Content-Length 就别读了，直接判过大。"""
        resp = FakeResponse(b"x" * 10, headers={"Content-Length": "999999"})
        self._install(resp)
        body, err = net.http_get("https://example.org/big", max_bytes=1000, retries=0)
        self.assertIsNone(body)
        self.assertIn("响应体过大", err)
        self.assertEqual(resp.reads, 0, "声明过大就不该再去读 body")

    def test_within_limit_passes(self):
        self._install(FakeResponse(b'{"ok":1}'))
        body, err = net.http_get("https://example.org/ok", max_bytes=1000, retries=0)
        self.assertEqual(body, '{"ok":1}')
        self.assertIsNone(err)

    def test_clamp_results(self):
        self.assertEqual(net.clamp_results(100), net.MAX_RESULTS_PER_QUERY)
        self.assertEqual(net.clamp_results(5), 5)
        self.assertEqual(net.clamp_results(0), 1, "至少要取 1 条")


class TestRetryAndFallback(NetworkTestCase):
    def test_retries_on_429_then_succeeds(self):
        self._install(urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None),
                      FakeResponse(b"{}"))
        stats = {}
        body, err = net.http_get("https://example.org/r", retries=2, stats=stats)
        self.assertEqual(body, "{}")
        self.assertIsNone(err)
        self.assertEqual(stats["attempts"], 2)
        self.assertEqual(len(self.slept), 1, "退避一次")

    def test_exhausted_retries_report_attempt_count(self):
        err_429 = lambda: urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)  # noqa: E731
        self._install(err_429(), err_429(), err_429(), err_429(), err_429(), err_429())
        stats = {}
        body, err = net.http_get("https://example.org/r", retries=2, stats=stats)
        self.assertIsNone(body)
        self.assertIn("HTTP 429", err)
        self.assertIn("共 6 次尝试", err)   # 2 个出口 × (2 次重试 + 1)
        self.assertEqual(stats["attempts"], 6)
        self.assertEqual(self.slept, [2.0, 4.0, 2.0, 4.0], "指数退避，换出口后重新计数")

    def test_404_is_fatal_no_proxy_switch(self):
        self._install(urllib.error.HTTPError("u", 404, "Not Found", {}, None))
        body, err = net.http_get("https://example.org/x", retries=2)
        self.assertIsNone(body)
        self.assertIn("HTTP 404", err)
        self.assertEqual(len(self._opens()), 1, "请求本身的问题，换出口也没用")

    def test_403_switches_proxy(self):
        """403 可能是代理层拒绝（沙箱代理是域名白名单），换出口要能救回来。"""
        self._install(urllib.error.HTTPError("u", 403, "Forbidden", {}, None),
                      FakeResponse(b"{}"))
        body, err = net.http_get("https://example.org/x", retries=2)
        self.assertEqual(body, "{}")
        self.assertEqual(len(self._opens()), 2)

    def test_network_error_switches_proxy(self):
        self._install(urllib.error.URLError("connection refused"), FakeResponse(b"{}"))
        body, _err = net.http_get("https://example.org/x", retries=1)
        self.assertEqual(body, "{}")
        self.assertEqual(len(self._opens()), 2)

    def test_json_parse_error_is_reported(self):
        self._install(FakeResponse(b"not json"))
        data, err = net.http_get_json("https://example.org/x", retries=0)
        self.assertIsNone(data)
        self.assertIn("JSON 解析失败", err)


class TestCache(NetworkTestCase):
    def test_second_call_hits_cache(self):
        self._install(FakeResponse(b'{"a":1}'))
        first = {}
        net.http_get_json("https://example.org/x", cache_dir=str(self.dir), stats=first, retries=0)
        second = {}
        body, err = net.http_get("https://example.org/x", cache_dir=str(self.dir),
                                 stats=second, retries=0)
        self.assertEqual(body, '{"a":1}')
        self.assertIsNone(err)
        self.assertEqual(first["source"], "network")
        self.assertEqual(second["source"], "cache")
        self.assertEqual(second["attempts"], 0)
        self.assertEqual(len(self._opens()), 1, "缓存命中就不该再出网")

    def test_cache_keeps_original_fetched_at(self):
        """缓存命中时 fetched_at 必须是**当初抓取**的时间。

        写成「本次运行时间」的话，evidence.retrieved_at 永远显示刚刚，
        旧快照检测（STALE_SNAPSHOT_DAYS）就成了摆设。
        """
        self._install(FakeResponse(b'{"a":1}'))
        first = {}
        net.http_get("https://example.org/x", cache_dir=str(self.dir), stats=first, retries=0)
        cached_at = first["fetched_at"]

        path = net._cache_path(str(self.dir), "https://example.org/x")
        rec = json.loads(path.read_text(encoding="utf-8"))
        rec["fetched_at"] = "2020-01-01T00:00:00Z"
        path.write_text(json.dumps(rec), encoding="utf-8")

        second = {}
        net.http_get("https://example.org/x", cache_dir=str(self.dir), stats=second, retries=0)
        self.assertEqual(second["fetched_at"], "2020-01-01T00:00:00Z")
        self.assertNotEqual(second["fetched_at"], cached_at)

    def test_expired_cache_refetches(self):
        self._install(FakeResponse(b'{"a":1}'), FakeResponse(b'{"a":2}'))
        net.http_get("https://example.org/x", cache_dir=str(self.dir), ttl_hours=24, retries=0)
        body, _err = net.http_get("https://example.org/x", cache_dir=str(self.dir),
                                  ttl_hours=0, retries=0)   # ttl=0 → 立即过期
        self.assertEqual(body, '{"a":2}')
        self.assertEqual(len(self._opens()), 2)

    def test_corrupt_cache_falls_back_to_network(self):
        path = net._cache_path(str(self.dir), "https://example.org/x")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")
        self._install(FakeResponse(b'{"a":1}'))
        body, err = net.http_get("https://example.org/x", cache_dir=str(self.dir), retries=0)
        self.assertEqual(body, '{"a":1}')
        self.assertIsNone(err)

    def test_cache_disabled_by_default_without_dir(self):
        self._install(FakeResponse(b'{"a":1}'), FakeResponse(b'{"a":1}'))
        net.http_get_json("https://example.org/x", retries=0)
        net.http_get_json("https://example.org/x", retries=0)
        self.assertEqual(len(self._opens()), 2, "没给 cache_dir 就不缓存")


if __name__ == "__main__":
    unittest.main(verbosity=2)
