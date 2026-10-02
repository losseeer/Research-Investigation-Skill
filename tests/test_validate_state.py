#!/usr/bin/env python3
"""P1 验收测试：Schema 冻结 + validate_state.py。stdlib unittest，无依赖。

运行： python3 tests/test_validate_state.py
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import validate_state as vs  # noqa: E402

SCHEMA_DIR = ROOT / "schemas"
TEMPLATE = ROOT / "assets" / "research-state.template.json"


def empty_state(**overrides):
    with open(TEMPLATE, encoding="utf-8") as f:
        state = json.load(f)
    state["idea"]["title"] = "test idea"
    state["idea"]["slug"] = "test-idea"
    state.update(overrides)
    return state


def write_state(d: Path, state, evidence=()):
    (d / "research-state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    (d / "evidence.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in evidence), encoding="utf-8"
    )


THIS_YEAR = datetime.now().year


def ev(eid, claim_ids, **kw):
    base = {
        "id": eid, "channel": "academic", "source_type": "academic",
        "title": "t", "url": f"https://example.org/{eid}", "summary": "s",
        "relevance": 0.8, "strength": "medium", "implementation_level": "paper",
        "claim_ids": claim_ids, "changes_judgment": False,
    }
    base.update(kw)
    return base


def claim(cid, **kw):
    """默认 timeless：饱和/门禁类测试只关心判据本身，时效行为由 TestTimeliness 覆盖。"""
    base = {"id": cid, "statement": "x", "type": "technical", "importance": "high",
            "status": "unknown", "confidence": 0.0, "evidence_ids": [],
            "time_sensitivity": "timeless"}
    base.update(kw)
    return base


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.v = vs.Validator(SCHEMA_DIR)

    def test_template_validates(self):
        state = empty_state()
        self.assertEqual(self.v.validate(state, self.v.load("research-state.json")), [])

    def test_rejects_unknown_field_and_bad_enum(self):
        state = empty_state(claims=[{"id": "C1", "statement": "x", "type": "technical",
                                     "importance": "high", "status": "unknown",
                                     "confidence": 0.0, "bogus": 1}])
        errs = self.v.validate(state, self.v.load("research-state.json"))
        self.assertTrue(any("bogus" in e for e in errs))

        bad = empty_state(status="half-done")
        errs = self.v.validate(bad, self.v.load("research-state.json"))
        self.assertTrue(any("枚举" in e for e in errs))

    def test_claim_confidence_bounds(self):
        c = {"id": "C1", "statement": "x", "type": "technical", "importance": "high",
             "status": "unknown", "confidence": 1.5}
        errs = self.v.validate(c, self.v.load("claim.json"))
        self.assertTrue(any("1.0" in e for e in errs))

    def test_judgment_has_no_unknown_status(self):
        j = {"claim_id": "C1", "status": "unknown", "confidence": 0.0, "rationale": "r",
             "supporting_evidence_ids": [], "contradicting_evidence_ids": []}
        errs = self.v.validate(j, self.v.load("judgment.json"))
        self.assertTrue(any("枚举" in e for e in errs))

    def test_evidence_requires_implementation_level(self):
        e = {"id": "E1", "channel": "github", "source_type": "github", "title": "t",
             "url": "https://github.com/a/b", "summary": "s", "relevance": 0.5,
             "strength": "medium"}
        errs = self.v.validate(e, self.v.load("evidence.json"))
        self.assertTrue(any("implementation_level" in e for e in errs))


class TestCrossCheck(unittest.TestCase):
    def _run(self, state, evidence):
        errs, warns = [], []
        vs.cross_check(state, evidence, errs, warns)
        return errs, warns

    def test_dangling_evidence_ref(self):
        state = empty_state(claims=[{"id": "C1", "statement": "x", "type": "technical",
                                     "importance": "high", "status": "unknown",
                                     "confidence": 0.0, "evidence_ids": ["E9"]}])
        errs, _ = self._run(state, [])
        self.assertTrue(any("E9" in e for e in errs))

    def test_confidence_without_evidence_rejected(self):
        state = empty_state(claims=[{"id": "C1", "statement": "x", "type": "technical",
                                     "importance": "high", "status": "supported",
                                     "confidence": 0.7, "evidence_ids": []}])
        errs, _ = self._run(state, [])
        self.assertTrue(any("confidence > 0" in e for e in errs))

    def test_judgment_without_evidence_rejected(self):
        state = empty_state(
            claims=[{"id": "C1", "statement": "x", "type": "technical", "importance": "high",
                     "status": "supported", "confidence": 0.0, "evidence_ids": ["E1"]}],
            judgments=[{"claim_id": "C1", "status": "supported", "confidence": 0.8,
                        "rationale": "r", "supporting_evidence_ids": [],
                        "contradicting_evidence_ids": []}],
        )
        errs, _ = self._run(state, [ev("E1", ["C1"])])
        self.assertTrue(any("无任何 evidence_ids" in e for e in errs))

    def test_valid_state_passes(self):
        state = empty_state(
            claims=[claim("C1", status="supported", confidence=0.8, evidence_ids=["E1"],
                          time_sensitivity="evolving")],
            judgments=[{"claim_id": "C1", "status": "supported", "confidence": 0.8,
                        "rationale": "E1", "supporting_evidence_ids": ["E1"],
                        "contradicting_evidence_ids": []}],
            search_plans=[{"claim_id": "C1", "queries": [
                {"id": "Q1", "channel": "academic", "query": "example academic query", "status": "done",
                 "result_count": 5},
                {"id": "Q2", "channel": "academic", "query": "cites:W123123", "status": "done",
                 "result_count": 2},
            ]}],
        )
        state["search_budget"]["executed_queries"] = ["Q1", "Q2"]
        vs.sync_budget(state)
        errs, warns = self._run(state, [ev("E1", ["C1"], publication_year=THIS_YEAR)])
        self.assertEqual(errs, [])
        self.assertEqual(warns, [])

    def test_hot_academic_without_citation_warns(self):
        state = empty_state(
            claims=[{"id": "C1", "statement": "x", "type": "technical", "importance": "high",
                     "status": "supported", "confidence": 0.8, "evidence_ids": ["E1"]}],
            search_plans=[{"claim_id": "C1", "queries": [
                {"id": "Q1", "channel": "academic", "query": "example academic query", "status": "done",
                 "result_count": 5},
            ]}],
        )
        _, warns = self._run(state, [ev("E1", ["C1"])])
        self.assertTrue(any("引文展开" in w for w in warns))

    def test_cross_check_requires_executed_status_results(self):
        state = empty_state(search_plans=[{"claim_id": "C1", "queries": [
            {"id": "Q1", "channel": "github", "query": "x", "status": "done"},
        ]}])
        errs, _ = self._run(state, [])
        self.assertTrue(any("result_count" in e for e in errs))


class TestFinalize(unittest.TestCase):
    """P5 判据：预算耗尽时强制出报告，未裁决 Claim 标 insufficient_evidence。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_undecided_claims_filled(self):
        write_state(self.dir, empty_state(claims=[
            {"id": "C1", "statement": "x", "type": "technical", "importance": "high",
             "status": "unknown", "confidence": 0.0},
            {"id": "C2", "statement": "y", "type": "market", "importance": "medium",
             "status": "unknown", "confidence": 0.0}]))
        rc = vs.cmd_finalize(type("A", (), {"dir": str(self.dir), "reason": "预算耗尽："}))
        self.assertEqual(rc, 0)
        state, _ = vs.load_state(self.dir)
        self.assertEqual(len(state["judgments"]), 2)
        self.assertTrue(all(j["status"] == "insufficient_evidence" for j in state["judgments"]))
        self.assertTrue(all(j["confidence"] == 0.0 for j in state["judgments"]))
        self.assertEqual(state["status"], "verified")
        # 补齐后不再有「未裁决」类错误（stage 1/2 的门禁与本用例无关）
        errs = []
        vs.check_stage(state, 4, errs)
        self.assertEqual([e for e in errs if "未裁决" in e], [])

    def test_finalize_is_idempotent(self):
        write_state(self.dir, empty_state(claims=[
            {"id": "C1", "statement": "x", "type": "technical", "importance": "high",
             "status": "supported", "confidence": 0.8, "evidence_ids": ["E1"]}],
            judgments=[{"claim_id": "C1", "status": "supported", "confidence": 0.8,
                        "rationale": "E1", "supporting_evidence_ids": ["E1"],
                        "contradicting_evidence_ids": []}]),
            evidence=[ev("E1", ["C1"])])
        vs.cmd_finalize(type("A", (), {"dir": str(self.dir), "reason": "r："}))
        state, _ = vs.load_state(self.dir)
        self.assertEqual(len(state["judgments"]), 1)  # 不重复追加
        self.assertEqual(state["judgments"][0]["status"], "supported")  # 不被覆盖


class TestMerge(unittest.TestCase):
    """Stage 4/5/6 的通用写回。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _merge(self, patch):
        return vs.cmd_merge(type("A", (), {"dir": str(self.dir), "data": json.dumps(patch)}))

    def test_upsert_judgment_by_claim_id(self):
        write_state(self.dir, empty_state(claims=[
            {"id": "C1", "statement": "x", "type": "technical", "importance": "high",
             "status": "unknown", "confidence": 0.0, "evidence_ids": ["E1"]}],
            judgments=[]), evidence=[ev("E1", ["C1"])])
        j = {"claim_id": "C1", "status": "supported", "confidence": 0.8, "rationale": "E1 表明…",
             "supporting_evidence_ids": ["E1"], "contradicting_evidence_ids": []}
        self.assertEqual(self._merge({"judgments": [j]}), 0)
        state, _ = vs.load_state(self.dir)
        self.assertEqual(len(state["judgments"]), 1)
        # 再次写入同一 claim_id：按 id upsert，而不是追加第二条
        self._merge({"judgments": [dict(j, confidence=0.6)]})
        state, _ = vs.load_state(self.dir)
        self.assertEqual(len(state["judgments"]), 1)
        self.assertEqual(state["judgments"][0]["confidence"], 0.6)

    def test_merge_updates_claim_status(self):
        write_state(self.dir, empty_state(claims=[
            {"id": "C1", "statement": "x", "type": "technical", "importance": "high",
             "status": "unknown", "confidence": 0.0, "evidence_ids": ["E1"]}]),
            evidence=[ev("E1", ["C1"])])
        self.assertEqual(self._merge({"claims": [
            {"id": "C1", "status": "supported", "confidence": 0.7}]}), 0)
        state, _ = vs.load_state(self.dir)
        self.assertEqual(state["claims"][0]["status"], "supported")
        self.assertEqual(state["claims"][0]["evidence_ids"], ["E1"])  # 未传则保留

    def test_merge_rejects_invalid_and_writes_nothing(self):
        write_state(self.dir, empty_state())
        self.assertEqual(self._merge({"status": "not-a-status"}), 1)
        state, _ = vs.load_state(self.dir)
        self.assertEqual(state["status"], "init")

    def test_merge_deep_merges_analysis(self):
        write_state(self.dir, empty_state())
        self._merge({"analysis": {"novelty": {"level": "moderate"}}})
        state, _ = vs.load_state(self.dir)
        self.assertEqual(state["analysis"]["novelty"]["level"], "moderate")
        self.assertEqual(state["analysis"]["novelty"]["because"], "")  # 同级字段保留


class TestBudgetAndSaturation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dedupe_by_title_across_sources(self):
        state = empty_state()
        first = {"id": "E1", "channel": "academic", "source_type": "academic", "title": "Itinera",
                 "url": "https://doi.org/10.1/x", "summary": "s", "relevance": 0.5,
                 "strength": "medium", "implementation_level": "paper"}
        same_paper_other_source = dict(first, url="https://arxiv.org/abs/2402.1")
        write_state(self.dir, state)
        added, skipped = vs.append_evidence(self.dir, [first], "academic")
        self.assertEqual(len(added), 1)
        added2, skipped2 = vs.append_evidence(self.dir, [same_paper_other_source], "academic")
        self.assertEqual(added2, [])
        self.assertEqual(len(skipped2), 1)

    def test_dedupe_by_url(self):
        write_state(self.dir, empty_state())
        item = {"id": None, "channel": "web", "source_type": "web", "title": "t1",
                "url": "https://WWW.Example.com/a/?utm_source=x", "summary": "s",
                "relevance": 0.5, "strength": "low", "implementation_level": "idea"}
        added, _ = vs.append_evidence(self.dir, [item], "web")
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["id"], "E1")
        dup = dict(item, url="http://example.com/a")
        added2, skipped2 = vs.append_evidence(self.dir, [dup], "web")
        self.assertEqual(added2, [])
        self.assertEqual(len(skipped2), 1)

    def test_cmd_saturation_reads_evidence_file(self):
        """回归：cmd_saturation 曾把 load_evidence 的 (items, bad) 解包反了，全部显示 0 条。"""
        import contextlib
        import io
        write_state(self.dir, empty_state(claims=[
            {"id": "C1", "statement": "x", "type": "technical", "importance": "high",
             "status": "unknown", "confidence": 0.0}]),
            evidence=[ev("E1", ["C1"]), ev("E2", ["C1"], source="IEEE")])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            vs.cmd_saturation(type("A", (), {"dir": str(self.dir)}))
        row = [l for l in buf.getvalue().splitlines() if l.startswith("C1")][0]
        self.assertIn("2", row.split()[1])  # ev 列

    def test_budget_exhausted_writes_nothing(self):
        """results 超上限时一条都不写，且 error 明确指向超预算（不是空结果）。"""
        state = empty_state()
        state["search_budget"]["by_channel"]["github"]["max_results"] = 2
        write_state(self.dir, state)
        items = [{"title": f"t{i}", "url": f"https://github.com/a/{i}", "channel": "github",
                  "source_type": "github", "summary": "s", "relevance": 0.5,
                  "strength": "medium", "implementation_level": "code"} for i in range(3)]
        with self.assertRaises(ValueError):
            vs.append_evidence(self.dir, items, "github")
        _, evidence = vs.load_evidence(self.dir)
        self.assertEqual(evidence, [])  # 超预算：一条都不写

    def test_query_is_charged_once_and_derived(self):
        """同一 Q 重复 finish 只计一次；by_channel 计数由收据派生，不能手写。"""
        state = empty_state(search_plans=[{"claim_id": "C1", "queries": [
            {"id": "Q1", "channel": "academic", "query": "a"},
            {"id": "Q2", "channel": "academic", "query": "b"}]}])
        write_state(self.dir, state)

        _ch, charged = vs.finish_query(self.dir, "Q1", "done", 5)
        self.assertTrue(charged)
        _ch2, charged2 = vs.finish_query(self.dir, "Q1", "done", 7)  # 重复回写
        self.assertFalse(charged2)

        st, _ = vs.load_state(self.dir)
        self.assertEqual(st["search_budget"]["by_channel"]["academic"]["queries"], 1)
        self.assertEqual(st["search_budget"]["executed_queries"], ["Q1"])
        self.assertEqual(st["search_budget"]["used"]["queries"], 1)

        # 手写计数会被派生值覆盖
        st["search_budget"]["by_channel"]["academic"]["queries"] = 99
        write_state(self.dir, st)
        st2, _ = vs.load_state(self.dir)
        vs.sync_budget(st2)
        self.assertEqual(st2["search_budget"]["by_channel"]["academic"]["queries"], 1)

    def test_query_cap_rejects_extra_execution(self):
        state = empty_state(search_plans=[{"claim_id": "C1", "queries": [
            {"id": f"Q{i}", "channel": "github", "query": f"q{i}"} for i in (1, 2, 3)]}])
        state["search_budget"]["by_channel"]["github"]["max_queries"] = 2
        write_state(self.dir, state)
        vs.finish_query(self.dir, "Q1", "done", 1)
        vs.finish_query(self.dir, "Q2", "failed", 0)
        with self.assertRaises(ValueError) as ctx:
            vs.finish_query(self.dir, "Q3", "done", 1)
        self.assertIn("超过上限", str(ctx.exception))

    def test_consume_no_longer_counts_queries(self):
        """query 计数已收敛到收据：consume 传 queries 必须报错而不是静默忽略。"""
        write_state(self.dir, empty_state())
        with self.assertRaises(ValueError) as ctx:
            vs.consume_budget(self.dir, "academic", queries=2, results=10)
        self.assertIn("charge_query", str(ctx.exception))

    def test_executable_queries_and_next_query(self):
        state = empty_state(search_plans=[{"claim_id": "C1", "queries": [
            {"id": "Q1", "channel": "academic", "query": "a", "status": "done",
             "result_count": 3},
            {"id": "Q2", "channel": "github", "query": "b"},
            {"id": "Q3", "channel": "github", "query": "c"}]}])
        state["search_budget"]["by_channel"]["github"]["max_queries"] = 1
        write_state(self.dir, state)
        vs.finish_query(self.dir, "Q1", "done", 3)
        st, _ = vs.load_state(self.dir)
        self.assertEqual([q["id"] for _c, q in vs.executable_queries(st)], ["Q2", "Q3"])
        vs.cmd_next_query(type("A", (), {"dir": str(self.dir), "channel": None, "json": False}))
        vs.finish_query(self.dir, "Q2", "done", 2)
        st2, _ = vs.load_state(self.dir)
        self.assertEqual(vs.executable_queries(st2), [])  # github 额度已耗尽

    def test_cross_check_flags_counter_drift(self):
        """手写 by_channel 计数与收据不一致 → 直接判为 error。"""
        state = empty_state(search_plans=[{"claim_id": "C1", "queries": [
            {"id": "Q1", "channel": "academic", "query": "a"}]}])
        write_state(self.dir, state)
        vs.finish_query(self.dir, "Q1", "done", 1)
        st, _ = vs.load_state(self.dir)
        st["search_budget"]["by_channel"]["academic"]["queries"] = 42
        errs = []
        vs.cross_check(st, [], errs, [])
        self.assertTrue(any("不一致" in e for e in errs))

    def test_saturation_detects_independence(self):
        state = empty_state(claims=[claim("C1")])
        evidence = [
            ev("E1", ["C1"], source="Nature"),
            ev("E2", ["C1"], source="IEEE", source_type="github", channel="github"),
            ev("E3", ["C1"], source="ACM"),
        ]
        rows = vs.saturation_rows(state, evidence)
        self.assertTrue(rows[0]["saturated"])
        self.assertEqual(rows[0]["independent"], 3)

    def test_saturation_detects_duplicates(self):
        state = empty_state(claims=[claim("C1")])
        evidence = [ev("E1", ["C1"], url="https://same"), ev("E2", ["C1"], url="https://same"),
                    ev("E3", ["C1"], url="https://same")]
        rows = vs.saturation_rows(state, evidence)
        self.assertGreater(rows[0]["duplicate_rate"], 0.6)
        self.assertTrue(rows[0]["saturated"])


class TestStageGates(unittest.TestCase):
    def test_stage1_requires_five_claims(self):
        state = empty_state(claims=[])
        errs = []
        vs.check_stage(state, 1, errs)
        self.assertTrue(any("< 5" in e for e in errs))

    def test_stage1_requires_type_coverage_and_high_claims(self):
        mk = lambda t, imp: {"id": f"C{t}{imp}", "statement": "x", "type": t,  # noqa: E731
                             "importance": imp, "status": "unknown", "confidence": 0.0}
        # 5 条但只有 1 种 type、0 条 high
        state = empty_state(claims=[mk("technical", "low") for _ in range(5)])
        errs = []
        vs.check_stage(state, 1, errs)
        self.assertTrue(any("type 覆盖" in e for e in errs))
        self.assertTrue(any("high 的 Claim" in e for e in errs))

        # 合格：5 条、3 种 type、2 条 high
        good = [mk("technical", "high"), mk("scientific", "high"), mk("product", "medium"),
                mk("market", "medium"), mk("user_problem", "low")]
        errs = []
        vs.check_stage(empty_state(claims=good), 1, errs)
        self.assertEqual(errs, [])

    def test_stage2_rejects_plan_over_channel_cap(self):
        state = empty_state(
            claims=[{"id": "C1", "statement": "x", "type": "technical", "importance": "high",
                     "status": "unknown", "confidence": 0.0}],
            search_plans=[{"claim_id": "C1", "queries": [
                {"id": f"Q{i}", "channel": "github", "query": "q", "status": "pending"}
                for i in range(1, 8)]}],
        )
        errs = []
        vs.check_stage(state, 2, errs)
        self.assertTrue(any("超过额度" in e for e in errs))

    def test_stage2_requires_cross_channel(self):
        state = empty_state(
            claims=[{"id": "C1", "statement": "x", "type": "technical", "importance": "high",
                     "status": "unknown", "confidence": 0.0}],
            search_plans=[{"claim_id": "C1", "queries": [
                {"id": "Q1", "channel": "academic", "query": "a"},
                {"id": "Q2", "channel": "academic", "query": "b"},
                {"id": "Q3", "channel": "academic", "query": "c"}]}],
        )
        errs = []
        vs.check_stage(state, 2, errs)
        self.assertTrue(any("未跨通道" in e for e in errs))

    def test_stage4_requires_high_claim_judged(self):
        state = empty_state(claims=[{"id": "C1", "statement": "x", "type": "technical",
                                     "importance": "high", "status": "unknown",
                                     "confidence": 0.0}])
        errs = []
        vs.check_stage(state, 4, errs)
        self.assertTrue(any("未裁决" in e for e in errs))


class TestBudgetProfiles(unittest.TestCase):
    """README TODO #3：quick / standard / deep 三档预算 profile。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _init(self, profile=None):
        args = SimpleNamespace(idea="profile test idea", domain="",
                               root=str(self.root), profile=profile)
        with redirect_stdout(io.StringIO()):
            vs.cmd_init(args)
        d = self.root / "profile-test-idea"
        state, _ = vs.load_state(d)
        return d, state

    def test_default_profile_is_from_config(self):
        cfg = vs.load_profiles()
        _d, state = self._init()
        self.assertEqual(state["search_budget"]["profile"], cfg["default"])
        self.assertEqual(state["search_budget"]["max_iterations"],
                         cfg["profiles"][cfg["default"]]["max_iterations"])

    def test_each_profile_applies_limits(self):
        expected = {"quick": (4, 14), "standard": (8, 30), "deep": (14, 55)}
        cfg = vs.load_profiles()["profiles"]
        for name, (iters, queries) in expected.items():
            _d, state = self._init(name)
            b = state["search_budget"]
            self.assertEqual(b["profile"], name)
            self.assertEqual(b["max_iterations"], iters)
            self.assertEqual(b["max_queries"], queries)
            self.assertEqual(b["by_channel"]["academic"]["max_queries"],
                             cfg[name]["by_channel"]["academic"]["max_queries"])
            self.assertEqual(b["iterations"], 0)
            self.assertEqual(b["used"], {"queries": 0, "results": 0})

    def test_profile_writes_saturation_thresholds(self):
        _d, state = self._init("quick")
        self.assertEqual(state["search_budget"]["saturation"],
                         {"min_independent": 2, "max_rounds_without_change": 1,
                          "duplicate_rate": 0.7})

    def test_init_passes_schema(self):
        v = vs.Validator(vs.SCHEMA_DIR)
        for name in vs.PROFILE_NAMES:
            d, _s = self._init(name)
            body = json.loads((d / "research-state.json").read_text(encoding="utf-8"))
            errs = v.validate(body, v.load("research-state.json"))
            self.assertEqual(errs, [], f"profile {name} 产出的 state 不合法: {errs}")

    def test_unknown_profile_exits(self):
        with self.assertRaises(SystemExit) as ctx:
            self._init("turbo")
        self.assertIn("未知档位", str(ctx.exception))

    def test_quick_is_tighter_than_deep(self):
        _d, q = self._init("quick")
        _d2, dp = self._init("deep")
        for ch in vs.CHANNELS:
            self.assertLess(q["search_budget"]["by_channel"][ch]["max_queries"],
                            dp["search_budget"]["by_channel"][ch]["max_queries"])

    def test_saturation_thresholds_come_from_profile(self):
        """quick 档判据更松：2 条独立证据即饱和，standard 需 3 条。"""
        evidence = [
            {"id": "E1", "url": "https://a.example/x", "source": "a",
             "source_type": "academic", "claim_ids": ["C1"], "title": "t1"},
            {"id": "E2", "url": "https://b.example/y", "source": "b",
             "source_type": "github", "claim_ids": ["C1"], "title": "t2"},
        ]
        claims = [claim("C1", statement="s", search_queries=[])]

        _d, st_quick = self._init("quick")
        st_quick["claims"] = claims
        _d2, st_std = self._init("standard")
        st_std["claims"] = claims

        row_quick = vs.saturation_rows(st_quick, evidence, vs.saturation_thresholds(st_quick)[0])
        row_std = vs.saturation_rows(st_std, evidence, vs.saturation_thresholds(st_std)[0])
        self.assertTrue(row_quick[0]["saturated"])
        self.assertFalse(row_std[0]["saturated"])

    def test_legacy_state_falls_back_with_flag(self):
        state = {"search_budget": {"max_iterations": 8, "max_queries": 30, "iterations": 0,
                                   "used": {}, "by_channel": {}}}
        th, from_profile = vs.saturation_thresholds(state)
        self.assertFalse(from_profile)
        self.assertEqual(th, vs.SATURATION_DEFAULTS)

    def test_profiles_command_lists_all(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            vs.cmd_profiles(SimpleNamespace())
        out = buf.getvalue()
        for name in vs.PROFILE_NAMES:
            self.assertIn(name, out)


class TestAutoSaturationAndTopK(unittest.TestCase):
    """README TODO #2：自动 Evidence Saturation（stop-check）+ Evidence top-k 裁剪（topk）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _state(self, **kw):
        st = empty_state(**kw)
        return st

    def test_stop_check_marks_stopped_and_finalizes(self):
        """3 条独立证据 + 独立证据达阈值 → 该 Claim 自动 stopped，循环判 FINALIZE。"""
        st = self._state(claims=[claim("C1")],
                         search_plans=[{"claim_id": "C1", "queries": [
                             {"id": "Q1", "channel": "pending_ch", "query": "q"}]}])
        st["search_plans"] = [{"claim_id": "C1", "queries": [
            {"id": "Q1", "channel": "web", "query": "q", "status": "pending"}]}]
        write_state(self.dir, st, evidence=[
            ev("E1", ["C1"], source="Nature"),
            ev("E2", ["C1"], source="IEEE", source_type="github", channel="github"),
            ev("E3", ["C1"], source="ACM"),
        ])
        buf = io.StringIO()
        with redirect_stdout(buf):
            vs.cmd_stop_check(SimpleNamespace(dir=str(self.dir), json=False))
        out = buf.getvalue()
        self.assertIn("STOPPED", out)
        self.assertIn("FINALIZE", out)
        st2, _ = vs.load_state(self.dir)
        self.assertTrue(st2["saturation"]["C1"]["stopped"])
        self.assertIn("independence", st2["saturation"]["C1"]["reason"])

    def test_stop_check_continues_when_pending_queries_exist(self):
        st = self._state(claims=[{"id": "C1", "statement": "x", "type": "technical",
                                  "importance": "high", "status": "unknown",
                                  "confidence": 0.0, "evidence_ids": []}],
                         search_plans=[{"claim_id": "C1", "queries": [
                             {"id": "Q1", "channel": "web", "query": "q", "status": "pending"}]}])
        write_state(self.dir, st, evidence=[ev("E1", ["C1"], source="Nature")])
        buf = io.StringIO()
        with redirect_stdout(buf):
            vs.cmd_stop_check(SimpleNamespace(dir=str(self.dir), json=False))
        out = buf.getvalue()
        self.assertIn("CONTINUE", out)
        st2, _ = vs.load_state(self.dir)
        self.assertFalse(st2.get("saturation", {}).get("C1", {}).get("stopped"))

    def test_stop_check_finalizes_when_no_executable_query(self):
        st = self._state(claims=[{"id": "C1", "statement": "x", "type": "technical",
                                  "importance": "high", "status": "unknown",
                                  "confidence": 0.0, "evidence_ids": []}])
        st["search_plans"] = []
        write_state(self.dir, st, evidence=[])
        buf = io.StringIO()
        with redirect_stdout(buf):
            vs.cmd_stop_check(SimpleNamespace(dir=str(self.dir), json=False))
        self.assertIn("FINALIZE", buf.getvalue())
        self.assertIn("无可执行的 query", buf.getvalue())

    def test_stop_check_honors_profile_threshold(self):
        """quick 档面对 2 条独立证据应判饱和并 FINALIZE。"""
        st = self._state(claims=[claim("C1")])
        st["search_plans"] = []
        st["search_budget"]["profile"] = "quick"
        st["search_budget"]["saturation"] = {"min_independent": 2,
                                             "max_rounds_without_change": 1,
                                             "duplicate_rate": 0.7}
        write_state(self.dir, st, evidence=[
            ev("E1", ["C1"], source="Nature"),
            ev("E2", ["C1"], source="IEEE", source_type="github", channel="github")])
        buf = io.StringIO()
        with redirect_stdout(buf):
            vs.cmd_stop_check(SimpleNamespace(dir=str(self.dir), json=False))
        self.assertIn("STOPPED", buf.getvalue())

    def test_topk_picks_highest_relevance_and_trims(self):
        write_state(self.dir, empty_state(), evidence=[
            ev("E1", ["C1"], relevance=0.5),   # 低于 min_relevance，直接排除
            ev("E2", ["C1"], relevance=0.9),
            ev("E3", ["C1"], relevance=0.7),
            ev("E4", ["C1"], relevance=0.8),   # 满足阈值但被 k=2 裁掉
        ])
        buf = io.StringIO()
        with redirect_stdout(buf):
            vs.cmd_topk(SimpleNamespace(dir=str(self.dir), claim="C1", k=2, min_relevance=0.6))
        out = buf.getvalue()
        self.assertIn("E2", out)
        self.assertNotIn("E1", out)          # 低于 min_relevance
        self.assertNotIn("E3", out)          # 被 k=2 裁掉，但仍在 evidence.jsonl
        self.assertIn("1 条被裁剪", out)
        self.assertLess(out.index("E2"), out.index("E4"))  # relevance 降序

    def test_topk_rejects_k_over_context_limit(self):
        write_state(self.dir, empty_state(), evidence=[])
        with self.assertRaises(SystemExit) as ctx:
            vs.cmd_topk(SimpleNamespace(dir=str(self.dir), claim=None, k=11, min_relevance=0.6))
        self.assertIn("10", str(ctx.exception))


class TestPlanSafetyAndEvidenceEntry(unittest.TestCase):
    """三处事故的结构性修复：plan 增量追加 / merge 不许静默删 / 脚本 lone evidence 入口。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _plan_state(self):
        st = empty_state(
            claims=[{"id": "C3", "statement": "x", "type": "technical", "importance": "high",
                     "status": "unknown", "confidence": 0.0, "evidence_ids": []}],
            search_plans=[{"claim_id": "C3", "queries": [
                {"id": "Q1", "channel": "academic", "query": "old a", "status": "pending"},
                {"id": "Q2", "channel": "web", "query": "old b", "status": "pending"}]}])
        write_state(self.dir, st)
        return st

    # --- 事故 1：merge 增量补 plan 会整条替换 queries ---------------------
    def test_merge_full_plan_is_still_allowed(self):
        """传全量时 merge 照旧可用——不能为了防误删把正常用法也堵死。"""
        self._plan_state()
        rc = vs.cmd_merge(SimpleNamespace(
            dir=str(self.dir),
            data=json.dumps({"search_plans": [{"claim_id": "C3", "queries": [
                {"id": "Q1", "channel": "academic", "query": "old a", "status": "pending"},
                {"id": "Q2", "channel": "web", "query": "old b", "status": "pending"},
                {"id": "Q3", "channel": "github", "query": "new c"}]}]})))
        self.assertEqual(rc, 0)
        st, _ = vs.load_state(self.dir)
        self.assertEqual([q["id"] for q in st["search_plans"][0]["queries"]], ["Q1", "Q2", "Q3"])

    def test_merge_refuses_partial_plan_that_drops_queries(self):
        """缺了已有 Q 就视为误删：拒绝写入，state 保持原样。"""
        self._plan_state()
        rc = vs.cmd_merge(SimpleNamespace(
            dir=str(self.dir),
            data=json.dumps({"search_plans": [{"claim_id": "C3", "queries": [
                {"id": "Q26", "channel": "github", "query": "brand new"}]}]})))
        self.assertEqual(rc, 1)
        st, _ = vs.load_state(self.dir)
        self.assertEqual([q["id"] for q in st["search_plans"][0]["queries"]], ["Q1", "Q2"])

    def test_add_queries_appends_without_touching_existing(self):
        self._plan_state()
        rc = vs.cmd_add_queries(SimpleNamespace(
            dir=str(self.dir),
            data=json.dumps({"claim_id": "C3", "queries": [
                {"channel": "github", "query": "new c"}]})))
        self.assertEqual(rc, 0)
        st, _ = vs.load_state(self.dir)
        self.assertEqual([q["id"] for q in st["search_plans"][0]["queries"]], ["Q1", "Q2", "Q3"])

    def test_add_queries_is_idempotent_by_qid(self):
        """同 id 再补一次是合并字段，不会挤出第二条。"""
        self._plan_state()
        patch = {"claim_id": "C3", "queries": [
            {"id": "Q2", "channel": "web", "query": "renamed"},
            {"id": "Q9", "channel": "github", "query": "another"}]}
        vs.cmd_add_queries(SimpleNamespace(dir=str(self.dir), data=json.dumps(patch)))
        vs.cmd_add_queries(SimpleNamespace(dir=str(self.dir), data=json.dumps(patch)))
        st, _ = vs.load_state(self.dir)
        qs = {q["id"]: q for q in st["search_plans"][0]["queries"]}
        self.assertEqual(sorted(qs), ["Q1", "Q2", "Q9"])
        self.assertEqual(qs["Q2"]["query"], "renamed")

    def test_add_queries_creates_plan_and_rejects_bad_channel(self):
        self._plan_state()
        vs.cmd_add_queries(SimpleNamespace(
            dir=str(self.dir),
            data=json.dumps({"claim_id": "C9", "queries": [{"channel": "web", "query": "x"}]})))
        st, _ = vs.load_state(self.dir)
        self.assertEqual(len(st["search_plans"]), 2)
        with self.assertRaises(SystemExit):
            vs.cmd_add_queries(SimpleNamespace(
                dir=str(self.dir),
                data=json.dumps({"claim_id": "C3", "queries": [{"channel": "bogus", "query": "x"}]})))

    # --- 事故 2：query_id 不存在 → 不许留下孤儿证据 ----------------------
    def test_append_evidence_refuses_unknown_query_id(self):
        self._plan_state()
        items = [{"title": "t", "url": "https://example.com/a", "source_type": "web",
                  "summary": "s", "relevance": 0.6, "strength": "medium",
                  "implementation_level": "production"}]
        with self.assertRaises(ValueError) as ctx:
            vs.append_evidence(self.dir, items, "web", query_id="Q99")
        self.assertIn("Q99", str(ctx.exception))
        evidence, _bad = vs.load_evidence(self.dir)
        self.assertEqual(evidence, [], "拒绝时必须一条都不写")

    def test_require_query_checks_existence_and_channel(self):
        self._plan_state()
        self.assertTrue(vs.require_query(self.dir, "Q1", "academic"))
        with self.assertRaises(ValueError):
            vs.require_query(self.dir, "Q1", "github")   # 规划通道不吻合
        with self.assertRaises(ValueError):
            vs.require_query(self.dir, "Q404")

    # --- 事故 3：web / product 通道没有脚本入口 --------------------------
    def _web_items(self):
        return [{"title": "某产品官网", "url": "https://example.com/p1", "source_type": "product",
                 "summary": "提供该功能", "evidence": "supports X", "claim_ids": ["C3"],
                 "relevance": 0.7, "strength": "medium",
                 "implementation_level": "commercial_product"}]

    def test_add_evidence_writes_validated_entries(self):
        self._plan_state()
        rc = vs.cmd_add_evidence(SimpleNamespace(
            dir=str(self.dir), channel="web", query_id="Q2", data=json.dumps(self._web_items())))
        self.assertEqual(rc, 0)
        evidence, _bad = vs.load_evidence(self.dir)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["id"], "E1")
        self.assertEqual(evidence[0]["channel"], "web")
        self.assertEqual(evidence[0]["query_id"], "Q2")
        st, _ = vs.load_state(self.dir)
        self.assertEqual(st["search_budget"]["by_channel"]["web"]["results"], 1)

    def test_add_evidence_dedupes_and_charges_only_new(self):
        self._plan_state()
        args = SimpleNamespace(dir=str(self.dir), channel="web", query_id="Q2",
                               data=json.dumps(self._web_items()))
        vs.cmd_add_evidence(args)
        vs.cmd_add_evidence(args)   # 同 URL 再喂一次
        evidence, _bad = vs.load_evidence(self.dir)
        self.assertEqual(len(evidence), 1)
        st, _ = vs.load_state(self.dir)
        self.assertEqual(st["search_budget"]["by_channel"]["web"]["results"], 1)

    def test_add_evidence_writes_nothing_when_any_item_invalid(self):
        """一条不合法就全部驳回——避免「大部分有效 + 少量脏数据」混着落盘。"""
        self._plan_state()
        items = self._web_items() + [{"title": "缺字段的脏数据", "url": "https://example.com/p2"}]
        rc = vs.cmd_add_evidence(SimpleNamespace(
            dir=str(self.dir), channel="web", query_id="Q2", data=json.dumps(items)))
        self.assertEqual(rc, 1)
        evidence, _bad = vs.load_evidence(self.dir)
        self.assertEqual(evidence, [])

    def test_add_evidence_rejects_unknown_claim_and_query(self):
        self._plan_state()
        bad = self._web_items()
        bad[0]["claim_ids"] = ["C404"]
        rc = vs.cmd_add_evidence(SimpleNamespace(dir=str(self.dir), channel="web",
                                                 query_id="Q2", data=json.dumps(bad)))
        self.assertEqual(rc, 1)
        rc2 = vs.cmd_add_evidence(SimpleNamespace(dir=str(self.dir), channel="web",
                                                  query_id="Q77", data=json.dumps(self._web_items())))
        self.assertEqual(rc2, 1)
        evidence, _bad = vs.load_evidence(self.dir)
        self.assertEqual(evidence, [])

    def test_add_evidence_reads_from_file(self):
        self._plan_state()
        f = self.dir / "items.json"
        f.write_text(json.dumps(self._web_items()), encoding="utf-8")
        rc = vs.cmd_add_evidence(SimpleNamespace(dir=str(self.dir), channel="product",
                                                 query_id=None, data=None, file=str(f)))
        self.assertEqual(rc, 0)
        evidence, _bad = vs.load_evidence(self.dir)
        self.assertEqual(evidence[0]["channel"], "product")


class TestTimeliness(unittest.TestCase):
    """时效性：Claim 级 time_sensitivity + 全局窗口。旧结论不能冒充「现在仍成立」。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _supported(self, cid, **kw):
        return claim(cid, status="supported", confidence=0.7, evidence_ids=["E1"], **kw)

    def _errors(self, state, evidence):
        errs, warns = [], []
        vs.cross_check(state, evidence, errs, warns)
        return errs, warns

    # --- 门禁 -------------------------------------------------------------
    def test_evolving_claim_with_only_old_evidence_is_error(self):
        """LLM 这类快变领域：2020 的证据不能支撑 2026 的「仍成立」。"""
        state = empty_state(claims=[self._supported("C1", time_sensitivity="evolving")],
                            time_policy={"as_of": f"{THIS_YEAR}-01-01", "recency_window_years": 2})
        errs, _ = self._errors(state, [ev("E1", ["C1"], publication_year=THIS_YEAR - 5)])
        self.assertTrue(any("C1" in e and "evolving" in e for e in errs))
        self.assertIn(str(THIS_YEAR - 2), errs[0])   # cutoff 写进报错，方便照着补检索

    def test_timeless_claim_with_old_evidence_is_fine(self):
        """永真事实/理论界：十几年前的证据依然有效，不该拦。"""
        state = empty_state(claims=[self._supported("C1", time_sensitivity="timeless")],
                            time_policy={"as_of": f"{THIS_YEAR}-01-01", "recency_window_years": 2})
        errs, _ = self._errors(state, [ev("E1", ["C1"], publication_year=THIS_YEAR - 15)])
        self.assertEqual(errs, [])

    def test_evolving_claim_with_recent_evidence_passes(self):
        state = empty_state(claims=[self._supported("C1", time_sensitivity="evolving")],
                            time_policy={"as_of": f"{THIS_YEAR}-01-01", "recency_window_years": 2})
        errs, _ = self._errors(state, [ev("E1", ["C1"], publication_year=THIS_YEAR - 1)])
        self.assertEqual(errs, [])

    def test_gate_only_applies_to_positive_verdicts(self):
        """unknown / contradicted 不需要「近年证据」背书。"""
        state = empty_state(
            claims=[claim("C1", status="unknown", evidence_ids=["E1"],
                          time_sensitivity="evolving"),
                    claim("C2", status="contradicted", evidence_ids=["E1"],
                          time_sensitivity="evolving")],
            time_policy={"as_of": f"{THIS_YEAR}-01-01", "recency_window_years": 2})
        errs, _ = self._errors(state, [ev("E1", ["C1", "C2"], publication_year=THIS_YEAR - 6)])
        self.assertEqual(errs, [])

    def test_claim_level_window_overrides_global(self):
        """单条 Claim 可以放宽/收紧窗口（如硬件迭代慢，用 5 年）。"""
        state = empty_state(
            claims=[self._supported("C1", time_sensitivity="evolving", recency_window_years=6)],
            time_policy={"as_of": f"{THIS_YEAR}-01-01", "recency_window_years": 2})
        errs, _ = self._errors(state, [ev("E1", ["C1"], publication_year=THIS_YEAR - 4)])
        self.assertEqual(errs, [])

    def test_missing_time_sensitivity_defaults_to_evolving(self):
        """缺字段取保守值：宁可多查一轮，也不让过时结论蒙混。"""
        c = self._supported("C1")
        c.pop("time_sensitivity")
        state = empty_state(claims=[c],
                            time_policy={"as_of": f"{THIS_YEAR}-01-01", "recency_window_years": 2})
        errs, _ = self._errors(state, [ev("E1", ["C1"], publication_year=THIS_YEAR - 9)])
        self.assertTrue(errs)

    def test_default_window_and_as_of_when_policy_absent(self):
        """state 没写 time_policy：按「今天 + 默认窗口」兜底，不报错。"""
        state = empty_state(claims=[self._supported("C1", time_sensitivity="evolving")])
        state.pop("time_policy", None)
        tp = vs.time_policy(state)
        self.assertEqual(tp["window"], vs.DEFAULT_RECENCY_WINDOW_YEARS)
        self.assertEqual(tp["as_of"], datetime.now().date().isoformat())
        self.assertFalse(tp["explicit"])

    # --- 饱和与循环判决 ---------------------------------------------------
    def test_no_recent_evidence_blocks_saturation(self):
        """旧证据撑起独立数也不能判饱和：否则拿旧结论提前收口。"""
        state = empty_state(claims=[claim("C1", time_sensitivity="evolving")],
                            time_policy={"as_of": f"{THIS_YEAR}-01-01", "recency_window_years": 2})
        evidence = [ev(f"E{i}", ["C1"], source=s, publication_year=THIS_YEAR - 8)
                    for i, s in enumerate(["Nature", "IEEE", "ACM"], 1)]
        rows = vs.saturation_rows(state, evidence)
        self.assertEqual(rows[0]["independent"], 3)   # 判据本身已满足
        self.assertTrue(rows[0]["no_recent"])
        self.assertFalse(rows[0]["saturated"])
        self.assertIn("ADVISE:query_recent_work", rows[0]["advice"])

    def test_stop_check_continues_on_stale_evolving_claim(self):
        """还有额度就不许拿旧结论 FINALIZE。"""
        st = empty_state(claims=[claim("C1", time_sensitivity="evolving")],
                         search_plans=[{"claim_id": "C1", "queries": [
                             {"id": "Q1", "channel": "web", "query": "recent work",
                              "status": "pending"}]}],
                         time_policy={"as_of": f"{THIS_YEAR}-01-01", "recency_window_years": 2})
        write_state(self.dir, st, evidence=[
            ev("E1", ["C1"], source="Nature", publication_year=THIS_YEAR - 8),
            ev("E2", ["C1"], source="IEEE", publication_year=THIS_YEAR - 7),
            ev("E3", ["C1"], source="ACM", publication_year=THIS_YEAR - 6)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            vs.cmd_stop_check(SimpleNamespace(dir=str(self.dir), json=False))
        out = buf.getvalue()
        self.assertIn("CONTINUE", out)
        self.assertIn("C1", out)
        st2, _ = vs.load_state(self.dir)
        self.assertFalse(st2.get("saturation", {}).get("C1", {}).get("stopped"))

    def test_stop_check_finalizes_when_quota_exhausted_even_if_stale(self):
        """没额度了只能收口：判决仍要报 FINALIZE，不能死循环。"""
        st = empty_state(claims=[claim("C1", time_sensitivity="evolving")],
                         search_plans=[],
                         time_policy={"as_of": f"{THIS_YEAR}-01-01", "recency_window_years": 2})
        write_state(self.dir, st, evidence=[
            ev("E1", ["C1"], publication_year=THIS_YEAR - 8)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            vs.cmd_stop_check(SimpleNamespace(dir=str(self.dir), json=False))
        self.assertIn("FINALIZE", buf.getvalue())

    def test_saturation_command_prints_as_of(self):
        """saturation 输出必须声明基准时点，否则窗口无从核对。"""
        st = empty_state(claims=[claim("C1", time_sensitivity="evolving")],
                         time_policy={"as_of": "2026-03-01", "recency_window_years": 3})
        write_state(self.dir, st, evidence=[])
        buf = io.StringIO()
        with redirect_stdout(buf):
            vs.cmd_saturation(SimpleNamespace(dir=str(self.dir)))
        out = buf.getvalue()
        self.assertIn("as_of=2026-03-01", out)
        self.assertIn("recent_window=3y", out)
        self.assertIn("2023", out)          # cutoff 2026-3=2023

    # --- init -------------------------------------------------------------
    def test_init_writes_time_policy(self):
        d = Path(self.tmp.name) / "init"
        buf = io.StringIO()
        with redirect_stdout(buf):
            vs.cmd_init(SimpleNamespace(root=str(d), idea="时效性 idea", domain="",
                                        profile="standard", recency_window=5))
        state, _ = vs.load_state(Path(buf.getvalue().strip()))
        self.assertEqual(state["time_policy"]["recency_window_years"], 5)
        self.assertEqual(state["time_policy"]["as_of"], datetime.now().date().isoformat())
        self.assertEqual(vs.Validator(SCHEMA_DIR).validate(
            state, vs.Validator(SCHEMA_DIR).load("research-state.json")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
