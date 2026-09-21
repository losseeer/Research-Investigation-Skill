#!/usr/bin/env python3
"""P1 验收测试：Schema 冻结 + validate_state.py。stdlib unittest，无依赖。

运行： python3 tests/test_validate_state.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

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
        added, skipped = vs.append_evidence(self.dir, [first], "academic", queries=1)
        self.assertEqual(len(added), 1)
        added2, skipped2 = vs.append_evidence(self.dir, [same_paper_other_source], "academic",
                                              queries=1)
        self.assertEqual(added2, [])
        self.assertEqual(len(skipped2), 1)

    def test_dedupe_by_url(self):
        write_state(self.dir, empty_state())
        item = {"id": None, "channel": "web", "source_type": "web", "title": "t1",
                "url": "https://WWW.Example.com/a/?utm_source=x", "summary": "s",
                "relevance": 0.5, "strength": "low", "implementation_level": "idea"}
        added, _ = vs.append_evidence(self.dir, [item], "web", queries=1)
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["id"], "E1")
        dup = dict(item, url="http://example.com/a")
        added2, skipped2 = vs.append_evidence(self.dir, [dup], "web", queries=1)
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
        state = empty_state()
        state["search_budget"]["by_channel"]["github"] = {"max_queries": 1, "max_results": 10,
                                                          "queries": 0, "results": 0}
        write_state(self.dir, state)
        items = [{"title": f"t{i}", "url": f"https://github.com/a/{i}", "channel": "github",
                  "source_type": "github", "summary": "s", "relevance": 0.5,
                  "strength": "medium", "implementation_level": "code"} for i in range(3)]
        with self.assertRaises(ValueError):
            vs.append_evidence(self.dir, items, "github", queries=2)
        _, evidence = vs.load_evidence(self.dir)
        self.assertEqual(evidence, [])  # 超预算：一条都不写

    def test_consume_within_cap(self):
        write_state(self.dir, empty_state())
        vs.cmd_consume(type("A", (), {"dir": str(self.dir), "channel": "academic",
                                      "queries": 2, "results": 10, "iterations": 0}))
        state, _ = vs.load_state(self.dir)
        self.assertEqual(state["search_budget"]["by_channel"]["academic"]["queries"], 2)
        self.assertEqual(state["search_budget"]["used"]["results"], 10)

    def test_consume_over_cap_exits(self):
        write_state(self.dir, empty_state())
        args = type("A", (), {"dir": str(self.dir), "channel": "github",
                              "queries": 7, "results": 0, "iterations": 0})
        with self.assertRaises(SystemExit):
            vs.cmd_consume(args)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
