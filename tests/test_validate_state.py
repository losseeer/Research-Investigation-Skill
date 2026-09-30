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


def ev(eid, claim_ids, **kw):
    base = {
        "id": eid, "channel": "academic", "source_type": "academic",
        "title": "t", "url": f"https://example.org/{eid}", "summary": "s",
        "relevance": 0.8, "strength": "medium", "implementation_level": "paper",
        "claim_ids": claim_ids, "changes_judgment": False,
    }
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
            claims=[{"id": "C1", "statement": "x", "type": "technical", "importance": "high",
                     "status": "supported", "confidence": 0.8, "evidence_ids": ["E1"]}],
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
        errs, warns = self._run(state, [ev("E1", ["C1"])])
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
        state = empty_state(claims=[{"id": "C1", "statement": "x", "type": "technical",
                                     "importance": "high", "status": "unknown",
                                     "confidence": 0.0, "evidence_ids": []}])
        evidence = [
            ev("E1", ["C1"], source="Nature"),
            ev("E2", ["C1"], source="IEEE", source_type="github", channel="github"),
            ev("E3", ["C1"], source="ACM"),
        ]
        rows = vs.saturation_rows(state, evidence)
        self.assertTrue(rows[0]["saturated"])
        self.assertEqual(rows[0]["independent"], 3)

    def test_saturation_detects_duplicates(self):
        state = empty_state(claims=[{"id": "C1", "statement": "x", "type": "technical",
                                     "importance": "high", "status": "unknown",
                                     "confidence": 0.0, "evidence_ids": []}])
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
        claims = [{"id": "C1", "statement": "s", "type": "technical",
                   "importance": "high", "status": "unknown", "confidence": 0.0,
                   "evidence_ids": [], "search_queries": []}]

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
        st = self._state(claims=[{"id": "C1", "statement": "x", "type": "technical",
                                  "importance": "high", "status": "unknown",
                                  "confidence": 0.0, "evidence_ids": []}],
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
        st = self._state(claims=[{"id": "C1", "statement": "x", "type": "technical",
                                  "importance": "high", "status": "unknown",
                                  "confidence": 0.0, "evidence_ids": []}])
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
