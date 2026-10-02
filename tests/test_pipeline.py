#!/usr/bin/env python3
"""P6 全链路回归：用 tests/fixtures/ 下的 idea 跑完整流程（离线，不联网）。

覆盖：init → decompose → search-planning → evidence → verify/finalize → analyze → report，
逐段卡 stage 门禁，最后一个负例验证门禁确实会拦截而不是放行。

fixture 格式：
    idea / claims / queries({"C1":["channel|query", ...]}) / evidence（无 id，由脚本分配）
    judgments / prior_art / analysis / recommendation
    expect_pass + expect_verdict，或 expect_fail_stage + expect_error_contains

运行： python3 tests/test_pipeline.py
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "validate_state.py"
FIXTURES = sorted((ROOT / "tests" / "fixtures").glob("idea-*.json"))


def sh(*args):
    r = subprocess.run([sys.executable, str(SCRIPT), *args],
                       capture_output=True, text=True, cwd=str(ROOT))
    return r.returncode, (r.stdout + r.stderr)


def build_search_plans(queries: dict):
    """{"C1": ["web|xxx", ...]} → search_plans（Q 编号全局连续）。"""
    plans, n = [], 0
    for claim_id, items in queries.items():
        qs = []
        for raw in items:
            n += 1
            channel, _, query = raw.partition("|")
            qs.append({"id": f"Q{n}", "channel": channel, "query": query, "status": "pending"})
        plans.append({"claim_id": claim_id, "queries": qs})
    return plans


def plan_query_ids(queries: dict) -> dict:
    """{"C1": ["web|xxx"]} → {channel: [Q 编号]}，Q 编号规则与 build_search_plans 一致。"""
    out, n = {}, 0
    for _claim_id, items in queries.items():
        for raw in items:
            n += 1
            out.setdefault(raw.partition("|")[0], []).append(f"Q{n}")
    return out


class PipelineCase:
    def __init__(self, fixture_path: Path):
        self.fx = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.name = self.fx["id"]
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dir = None

    def init(self):
        rc, out = sh("init", "--idea", self.fx["raw"], "--domain", self.fx["domain"],
                     "--root", str(self.root))
        assert rc == 0, out
        self.dir = out.strip().splitlines()[-1]
        return self

    def merge(self, patch: dict, expect_ok=True):
        rc, out = sh("merge", self.dir, "--data", json.dumps(patch, ensure_ascii=False))
        if expect_ok:
            assert rc == 0, f"{self.name}: merge 失败\n{out}"
        return rc, out

    def check(self, stage):
        return sh("check", self.dir, "--stage", str(stage), "--json")


def run_positive(case: PipelineCase):
    fx = case.fx
    case.init()

    rc, out = case.check(1)
    assert rc == 1, "空 state 本就应卡在 stage 1"

    case.merge({"claims": fx["claims"]})
    rc, out = case.check(1)
    assert rc == 0, f"{case.name}: stage 1 应通过\n{out}"

    case.merge({"search_plans": build_search_plans(fx["queries"])})
    rc, out = case.check(2)
    assert rc == 0, f"{case.name}: stage 2 应通过\n{out}"

    # 证据落盘（离线：直接用 fixture 里的条目，不联网）
    sys.path.insert(0, str(ROOT / "scripts"))
    import validate_state as vs
    by_channel = {}
    for e in fx["evidence"]:
        by_channel.setdefault(e["channel"], []).append(e)
    # query 级记账：每个通道的取回结果挂到该通道第一条 planned query 上
    plan_ids = plan_query_ids(fx["queries"])
    added_total = 0
    for channel, items in by_channel.items():
        qid = (plan_ids.get(channel) or [None])[0]
        added, _ = vs.append_evidence(case.dir, items, channel, query_id=qid)
        if qid:
            vs.finish_query(case.dir, qid, "done", len(added))
        added_total += len(added)
    assert added_total == len(fx["evidence"]), f"{case.name}: 证据应全部写入"

    # 回填 claim.evidence_ids，让交叉校验与 verdict 判定能引用到
    claims_patch = []
    for c in fx["claims"]:
        eids = [f"E{i + 1}" for i, e in enumerate(fx["evidence"])
                if c["id"] in e.get("claim_ids", [])]
        if eids:
            claims_patch.append({"id": c["id"], "evidence_ids": eids})
    if claims_patch:
        case.merge({"claims": claims_patch})

    if fx.get("judgments"):
        case.merge({"judgments": fx["judgments"]})
    rc, out = sh("finalize", case.dir, "--reason", "fixture 收口：")
    assert rc == 0, out
    rc, out = case.check(4)
    assert rc == 0, f"{case.name}: stage 4 应通过\n{out}"

    case.merge({"prior_art": fx["prior_art"], "analysis": fx["analysis"]})
    rc, out = case.check(5)
    assert rc == 0, f"{case.name}: stage 5 应通过\n{out}"

    case.merge({"recommendation": fx["recommendation"], "status": "reported"})
    rc, out = case.check(6)
    assert rc == 0, f"{case.name}: stage 6 应通过\n{out}"

    state = json.loads((Path(case.dir) / "research-state.json").read_text(encoding="utf-8"))
    return state


class TestFullPipeline(unittest.TestCase):
    def setUp(self):
        self.cases = []

    def tearDown(self):
        for c in self.cases:
            c.tmp.cleanup()

    def _case(self, fixture):
        c = PipelineCase(fixture)
        self.cases.append(c)
        return c

    def test_fixtures_loaded(self):
        self.assertEqual(len(FIXTURES), 8,
                         "应有 8 个 fixture：01–04 正例路径 + 05 坏分解 + 06 MODIFY + 07 PIVOT + 08 过时证据")

    def test_positive_fixtures_run_to_report(self):
        for path in FIXTURES:
            fx = json.loads(path.read_text(encoding="utf-8"))
            if not fx.get("expect_pass"):
                continue
            with self.subTest(fixture=fx["id"]):
                state = run_positive(self._case(path))
                self.assertEqual(state["status"], "reported")
                self.assertEqual(state["recommendation"]["verdict"], fx["expect_verdict"])
                # 所有 Claim 都必须有裁决（finalize 兜底后不应有遗漏）
                judged = {j["claim_id"] for j in state["judgments"]}
                self.assertEqual(judged, {c["id"] for c in state["claims"]})

    def test_modify_fixture_comes_from_partially_supported(self):
        """MODIFY 的语义锚点：high Claim 部分成立 + 非空 conditions，且没有 high Claim 被 contradicted。"""
        path = next(p for p in FIXTURES
                    if json.loads(p.read_text(encoding="utf-8"))["id"] == "idea-06")
        fx = json.loads(path.read_text(encoding="utf-8"))
        state = run_positive(self._case(path))
        self.assertEqual(state["recommendation"]["verdict"], "MODIFY")
        self.assertTrue(state["recommendation"]["conditions"], "MODIFY 必须给出调整条件")
        high_ids = {c["id"] for c in fx["claims"] if c["importance"] == "high"}
        judged = {j["claim_id"]: j["status"] for j in state["judgments"]}
        self.assertNotIn("contradicted", {judged[c] for c in high_ids})
        self.assertIn("partially_supported", {judged[c] for c in high_ids})

    def test_pivot_fixture_comes_from_contradicted_plus_adjacent(self):
        """PIVOT 的语义锚点：核心 Claim 被反驳，同时相邻子任务的 Claim 被支持。"""
        path = next(p for p in FIXTURES
                    if json.loads(p.read_text(encoding="utf-8"))["id"] == "idea-07")
        fx = json.loads(path.read_text(encoding="utf-8"))
        state = run_positive(self._case(path))
        self.assertEqual(state["recommendation"]["verdict"], "PIVOT")
        judged = {j["claim_id"]: j["status"] for j in state["judgments"]}
        self.assertEqual(judged["C2"], "contradicted")   # 原方向核心假设
        self.assertEqual(judged["C5"], "supported")      # 相邻机会
        self.assertTrue(state["recommendation"]["conditions"])

    def test_negative_fixtures_rejected_by_gate(self):
        negatives = [p for p in FIXTURES
                     if not json.loads(p.read_text(encoding="utf-8")).get("expect_pass")]
        self.assertGreaterEqual(len(negatives), 2, "应有多个负例：坏分解 + 过时证据")
        for path in negatives:
            fx = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(fixture=fx["id"]):
                case = self._case(path)
                case.init()
                case.merge({"claims": fx["claims"]})
                case.merge({"search_plans": build_search_plans(fx["queries"])})
                if fx.get("evidence"):
                    sys.path.insert(0, str(ROOT / "scripts"))
                    import validate_state as vs
                    by_channel = {}
                    for e in fx["evidence"]:
                        by_channel.setdefault(e["channel"], []).append(e)
                    plan_ids = plan_query_ids(fx["queries"])
                    for channel, items in by_channel.items():
                        qid = (plan_ids.get(channel) or [None])[0]
                        vs.append_evidence(case.dir, items, channel, query_id=qid)
                        if qid:
                            vs.finish_query(case.dir, qid, "done", len(items))
                if fx.get("judgments"):
                    case.merge({"judgments": fx["judgments"]})
                rc, out = case.check(fx["expect_fail_stage"])
                self.assertEqual(rc, 1, f"{fx['id']}: 负例应被门禁拦下，实际通过：\n{out}")
                for needle in fx["expect_error_contains"]:
                    self.assertIn(needle, out, f"{fx['id']}: 报错信息里应包含「{needle}」")

    def test_dont_do_fixture_has_identical_prior_art(self):
        path = next(p for p in FIXTURES
                    if json.loads(p.read_text(encoding="utf-8"))["id"] == "idea-04")
        state = run_positive(self._case(path))
        self.assertIn("identical", [p["similarity"] for p in state["prior_art"]])
        self.assertEqual(state["analysis"]["novelty"]["level"], "none")
        self.assertEqual(state["recommendation"]["verdict"], "DON'T_DO")

    def test_budget_accounted_after_evidence(self):
        path = next(p for p in FIXTURES
                    if json.loads(p.read_text(encoding="utf-8"))["id"] == "idea-01")
        fx = json.loads(path.read_text(encoding="utf-8"))
        case = self._case(path)
        case.init()
        case.merge({"claims": fx["claims"]})
        case.merge({"search_plans": build_search_plans(fx["queries"])})
        sys.path.insert(0, str(ROOT / "scripts"))
        import validate_state as vs
        by_channel = {}
        for e in fx["evidence"]:
            by_channel.setdefault(e["channel"], []).append(e)
        plan_ids = plan_query_ids(fx["queries"])
        for channel, items in by_channel.items():
            qid = (plan_ids.get(channel) or [None])[0]
            added, _ = vs.append_evidence(case.dir, items, channel, query_id=qid)
            if qid:
                vs.finish_query(case.dir, qid, "done", len(added))
        rc, out = sh("budget", case.dir)
        self.assertEqual(rc, 0)
        rows = {l.split()[0]: l for l in out.splitlines()
                if l.startswith(("academic", "github", "web", "product"))}
        # 计数来自 executed_queries 收据，不再是「调用时口头申报」
        self.assertIn("1/12", rows["academic"], out)   # academic 执行了 1 条 query
        self.assertIn("3/80", rows["academic"], out)   # 落 3 条证据
        self.assertIn("1/6", rows["github"], out)      # github 执行了 1 条 query
        self.assertIn("0/8", rows["web"], out)         # web 通道未调用


if __name__ == "__main__":
    unittest.main(verbosity=2)
