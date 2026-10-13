#!/usr/bin/env python3
"""迭代记账与收口记录：P0 consume 回归 / P1 closure / P2 单通道 / P3 主通道门禁。

这些用例全部来自真实调研复盘，每条都对应一个已发生的故障：
- `consume` 读了一个已被删除的参数，调用必崩 → iterations 恒为 0，迭代上限这道门从未生效；
- finalize 时 saturation 为空 → 事后无法区分「找够了」和「没预算了」；
- independence 按来源去重 → 16 条同通道证据能凑出 independence=8 并判饱和。

运行： python3 tests/test_iteration_closure.py
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import validate_state as vs  # noqa: E402

SCRIPT = ROOT / "scripts" / "validate_state.py"


def run_cli(*args):
    p = subprocess.run([sys.executable, str(SCRIPT), *args],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def budget(maxi=4, iters=0, caps=None):
    caps = caps or {ch: 6 for ch in vs.CHANNELS}
    return {"max_iterations": maxi, "max_queries": 30, "iterations": iters,
            "used": {"queries": 0, "results": 0},
            "by_channel": {ch: {"max_queries": n, "max_results": 40,
                                "queries": 0, "results": 0}
                           for ch, n in caps.items()}}


def claim(cid, typ="scientific", importance="high", status="unknown"):
    return {"id": cid, "statement": "s", "type": typ, "importance": importance,
            "status": status, "confidence": 0.0, "evidence_ids": [],
            "time_sensitivity": "timeless"}


def plan(cid, *channels, start=1):
    return {"claim_id": cid, "queries": [
        {"id": f"Q{start + i}", "channel": ch, "query": f"q{start + i}", "status": "pending"}
        for i, ch in enumerate(channels)]}


def state_with(**kw):
    st = {"schema_version": "1.0", "idea": {"title": "t", "raw": "t", "slug": "t"},
          "status": "decomposed", "stage": 3,
          "claims": [claim("C1")], "search_plans": [], "judgments": [],
          "search_budget": budget()}
    st.update(kw)
    return st


def ev(eid, cid, channel="academic", relevance=0.8, **kw):
    base = {"id": eid, "channel": channel, "source_type": "paper",
            "title": f"t-{eid}", "url": f"https://example.org/{eid}", "summary": "s",
            "relevance": relevance, "strength": "medium", "implementation_level": "paper",
            "claim_ids": [cid], "changes_judgment": False}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# P0：consume 回归 + iterations 自动推进
# --------------------------------------------------------------------------
class TestConsumeRegression(unittest.TestCase):
    """`cmd_consume` 曾读 `args.queries`，而该参数已在 query 记账改造中被删除，
    导致任何 consume 调用都 AttributeError。这是「迭代预算从未生效」的直接原因。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name) / "s"
        self.d.mkdir()
        st = state_with()
        (self.d / "research-state.json").write_text(
            json.dumps(st, ensure_ascii=False), encoding="utf-8")
        (self.d / "evidence.jsonl").touch()

    def tearDown(self):
        self.tmp.cleanup()

    def test_consume_iterations_does_not_crash(self):
        rc, out = run_cli("consume", str(self.d), "--iterations", "1")
        self.assertEqual(rc, 0, out)
        self.assertIn("iterations -> 1/4", out)
        self.assertNotIn("AttributeError", out)

    def test_consume_results_needs_channel(self):
        rc, out = run_cli("consume", str(self.d), "--results", "3")
        self.assertEqual(rc, 1)
        self.assertIn("--channel", out)

    def test_consume_results_records_channel_budget(self):
        rc, out = run_cli("consume", str(self.d), "--channel", "academic", "--results", "3")
        self.assertEqual(rc, 0, out)
        self.assertIn("results=3/40", out)

    def test_consume_iterations_over_cap_rejected(self):
        rc, out = run_cli("consume", str(self.d), "--iterations", "99")
        self.assertEqual(rc, 1)
        self.assertIn("超过上限", out)


class TestIterationAdvance(unittest.TestCase):
    """iterations 由 stop-check 自动推进，不依赖 agent 记得手动调用。"""

    def test_stop_check_advances_one_iteration(self):
        st = state_with(search_plans=[plan("C1", "academic", "github", "web")])
        vs.evaluate_stop(st, [], advance=True)
        self.assertEqual(st["search_budget"]["iterations"], 1)

    def test_no_advance_keeps_iteration(self):
        st = state_with(search_plans=[plan("C1", "academic", "github", "web")])
        vs.evaluate_stop(st, [], advance=False)
        self.assertEqual(st["search_budget"]["iterations"], 0)

    def test_advance_clamps_at_max(self):
        """到上限后继续推进不得越过 max——否则 check 会报「iterations 超过上限」把流程卡死。"""
        st = state_with(search_budget=budget(maxi=4, iters=4),
                        search_plans=[plan("C1", "academic", "github", "web")])
        vs.evaluate_stop(st, [], advance=True)
        self.assertEqual(st["search_budget"]["iterations"], 4)

    def test_advance_iterations_raises_without_clamp(self):
        st = state_with(search_budget=budget(maxi=4, iters=4))
        with self.assertRaises(ValueError):
            vs.advance_iterations(st, 1, clamp=False)


# --------------------------------------------------------------------------
# P1：closure —— 区分「找够了」和「没预算了」
# --------------------------------------------------------------------------
class TestClosure(unittest.TestCase):

    def _stop(self, **kw):
        st = state_with(**kw)
        res = vs.evaluate_stop(st, kw.get("_evidence", []), advance=kw.get("_advance", False))
        return st, res

    def test_budget_exhausted_when_no_pending_query(self):
        """实测 6/6 次调研都停在这里——必须写明是额度耗尽，不是查全了。"""
        st, res = self._stop(search_plans=[])
        self.assertEqual(res["verdict"], "FINALIZE")
        self.assertEqual(st["closure"]["kind"], "budget_exhausted")

    def test_iteration_cap(self):
        st, res = self._stop(search_budget=budget(maxi=4, iters=4),
                             search_plans=[plan("C1", "academic", "github", "web")])
        self.assertEqual(st["closure"]["kind"], "iteration_cap")
        self.assertIn("已达上限", st["closure"]["reason"])

    def test_saturated_when_all_high_stopped(self):
        st = state_with(search_plans=[plan("C1", "academic", "github", "web")],
                        saturation={"C1": {"stopped": True, "rounds_without_change": 0}})
        vs.evaluate_stop(st, [], advance=False)
        self.assertEqual(st["closure"]["kind"], "saturated")

    def test_all_high_judged(self):
        st = state_with(search_plans=[plan("C1", "academic", "github", "web")],
                        judgments=[{"claim_id": "C1", "status": "supported", "confidence": 0.8,
                                    "rationale": "r", "supporting_evidence_ids": [],
                                    "contradicting_evidence_ids": []}])
        vs.evaluate_stop(st, [], advance=False)
        self.assertEqual(st["closure"]["kind"], "all_high_judged")

    def test_continue_clears_stale_closure(self):
        """续跑时上一轮的 closure 必须清掉，否则报告会读到一个过期的收口原因。"""
        st = state_with(search_plans=[plan("C1", "academic", "github", "web")],
                        closure={"kind": "budget_exhausted", "verdict": "FINALIZE",
                                 "reason": "old"})
        vs.evaluate_stop(st, [], advance=False)
        self.assertNotIn("closure", st)

    def test_closure_records_unresolved_high_claims(self):
        st, _ = self._stop(search_plans=[])
        self.assertEqual(st["closure"]["unresolved_high_claims"], ["C1"])

    def test_closure_schema_accepted(self):
        v = vs.Validator(ROOT / "schemas")
        st, _ = self._stop(search_plans=[])
        self.assertEqual(v.validate(st, v.load("research-state.json")), [])


# --------------------------------------------------------------------------
# P2：单通道薄弱告警
# --------------------------------------------------------------------------
class TestSingleChannel(unittest.TestCase):

    def _warns(self, claims, evidence, **kw):
        st = state_with(claims=claims, **kw)
        errs, warns = [], []
        vs.cross_check(st, evidence, errs, warns)
        return warns

    def _judged(self, cid="C1", status="supported"):
        return [{"claim_id": cid, "status": status, "confidence": 0.8, "rationale": "r",
                 "supporting_evidence_ids": ["E1", "E2"], "contradicting_evidence_ids": []}]

    def test_single_channel_positive_verdict_warns(self):
        cl = claim("C1", "scientific", status="supported")
        warns = self._warns([cl], [ev("E1", "C1"), ev("E2", "C1")], judgments=self._judged())
        self.assertTrue(any("全部来自 academic" in w for w in warns), warns)

    def test_multi_channel_no_warning(self):
        cl = claim("C1", "scientific", status="supported")
        warns = self._warns([cl], [ev("E1", "C1", "academic"),
                                   ev("E2", "C1", "github", source_type="code")],
                            judgments=self._judged())
        self.assertFalse(any("全部来自" in w for w in warns), warns)

    def test_no_warning_without_positive_verdict(self):
        """unknown / contradicted 不需要通道多样性背书——只拦正向裁决。"""
        cl = claim("C1", "scientific", status="unknown")
        warns = self._warns([cl], [ev("E1", "C1"), ev("E2", "C1")], judgments=[])
        self.assertFalse(any("全部来自" in w for w in warns), warns)

    def test_low_relevance_evidence_not_counted(self):
        """relevance < 0.6 不进报告，不该把「只有一条能用」说成多通道覆盖。"""
        cl = claim("C1", "scientific", status="supported")
        warns = self._warns([cl], [ev("E1", "C1", "academic", 0.9),
                                   ev("E2", "C1", "academic", 0.8),
                                   ev("E3", "C1", "github", 0.3, source_type="code")],
                            judgments=self._judged())
        self.assertTrue(any("全部来自 academic" in w for w in warns), warns)

    def test_saturation_row_exposes_channels(self):
        st = state_with(claims=[claim("C1", "scientific", status="supported")],
                        judgments=self._judged())
        rows = vs.saturation_rows(st, [ev("E1", "C1"), ev("E2", "C1")])
        self.assertEqual(rows[0]["channels"], ["academic"])
        self.assertTrue(rows[0]["single_channel"])


# --------------------------------------------------------------------------
# P3：Stage 2 主通道覆盖 + 有额度没排
# --------------------------------------------------------------------------
class TestPrimaryChannelGate(unittest.TestCase):

    def _errs(self, typ, channels, stage=2):
        st = state_with(claims=[claim("C1", typ)], search_plans=[plan("C1", *channels)])
        errs = []
        vs.check_stage(st, stage, errs)
        return [e for e in errs if "主通道" in e]

    def test_scientific_claim_without_academic_blocked(self):
        errs = self._errs("scientific", ("github", "web"))
        self.assertTrue(errs, "scientific Claim 缺 academic 必须拦住")
        self.assertIn("academic", errs[0])

    def test_technical_claim_without_github_blocked(self):
        self.assertTrue(self._errs("technical", ("academic", "web")))

    def test_market_claim_without_web_blocked(self):
        self.assertTrue(self._errs("market", ("academic", "github")))

    def test_primary_channel_present_passes(self):
        self.assertEqual(self._errs("scientific", ("academic", "github", "web")), [])

    def test_idle_channel_warns(self):
        """实测多份调研里 product 有额度却 0 条 query——根因是没排，不是分配错。"""
        st = state_with(claims=[claim("C1")],
                        search_plans=[plan("C1", "academic", "github", "web")])
        errs, warns = [], []
        vs.cross_check(st, [], errs, warns)
        self.assertTrue(any("有额度但 search_plans 里 0 条 query" in w for w in warns), warns)
        self.assertIn("product", next(w for w in warns if "0 条 query" in w))

    def test_idle_channel_not_checked_before_stage_2(self):
        st = state_with(stage=1, search_plans=[plan("C1", "academic")])
        errs, warns = [], []
        vs.cross_check(st, [], errs, warns)
        self.assertFalse(any("0 条 query" in w for w in warns), warns)


# --------------------------------------------------------------------------
# P4：next-query 排序
# --------------------------------------------------------------------------
class TestNextQueryOrder(unittest.TestCase):

    def _first(self, claims, plans, **kw):
        st = state_with(claims=claims, search_plans=plans, **kw)
        return vs.executable_queries(st)[0]

    def test_high_claim_first(self):
        cid, q = self._first(
            [claim("C1", "scientific", "low"), claim("C2", "scientific", "high")],
            [plan("C1", "academic", start=1), plan("C2", "academic", start=4)])
        self.assertEqual(cid, "C2")

    def test_primary_channel_first_within_same_claim(self):
        """额度随时可能耗尽，同一 Claim 内先跑它的主通道。"""
        cid, q = self._first([claim("C1", "scientific")],
                             [plan("C1", "github", "academic", start=1)])
        self.assertEqual(q["channel"], "academic")

    def test_unjudged_claim_before_judged(self):
        cid, _ = self._first(
            [claim("C1", "scientific"), claim("C2", "scientific")],
            [plan("C1", "academic", start=1), plan("C2", "academic", start=4)],
            judgments=[{"claim_id": "C1", "status": "supported", "confidence": 0.8,
                        "rationale": "r", "supporting_evidence_ids": [],
                        "contradicting_evidence_ids": []}])
        self.assertEqual(cid, "C2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
