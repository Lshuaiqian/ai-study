"""知识点 DAG 的单测（纯逻辑，不联网）。

运行：python -m unittest discover -s study/tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph import (AVAILABLE, IN_PROGRESS, LOCKED, PASSED, build,  # noqa: E402
                   cascade_recheck, course_dag_mermaid, course_status,
                   find_cycles, knowledge_mermaid, knowledge_status, kp_id,
                   load_curriculums, load_route, mastery_consistency,
                   route_text, topo_order_courses, unlock_path)
from gate.mastery import reflow  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mini_route():
    return {"title": "t", "entry": {"name": "e", "note": ""}, "courses": [
        {"course_id": "c1", "title": "C1", "requires": []},
        {"course_id": "c2", "title": "C2", "requires": ["c1"]},
        {"course_id": "c3", "title": "C3", "requires": ["c2"]},
    ]}


def mini_curriculums(k1_requires=(), k2_requires=()):
    return {
        "c1": {"course_id": "c1", "declares": {"prerequisites": [], "unlocks": [
            {"course_id": "c2"}], "knowledge": [
            {"id": "K1", "name": "A", "level": "must", "keywords": [["a"]],
             "requires": list(k1_requires)}]}},
        "c2": {"course_id": "c2", "declares": {"prerequisites": [
            {"course_id": "c1"}], "unlocks": [{"course_id": "c3"}], "knowledge": [
            {"id": "K1", "name": "B", "level": "must", "keywords": [["b"]],
             "requires": list(k2_requires)}]}},
    }


class TestBuild(unittest.TestCase):

    def test_nodes_and_edges(self):
        g = build(mini_route(), mini_curriculums(
            k2_requires=[{"course_id": "c1", "knowledge_id": "K1", "why": "w"}]))
        self.assertIn("c1", g["nodes"])
        self.assertIn(kp_id("c1", "K1"), g["nodes"])
        kinds = [i for i in g["issues"] if i["kind"] == "cycle"]
        self.assertEqual(kinds, [])
        requires = [e for e in g["edges"] if e["type"] == "requires"]
        # c1->c2 课程级 + c1:K1->c2:K1 知识点级
        pairs = {(e["src"], e["dst"]) for e in requires}
        self.assertIn(("c1", "c2"), pairs)
        self.assertIn((kp_id("c1", "K1"), kp_id("c2", "K1")), pairs)

    def test_unknown_course_prereq_reported(self):
        route = mini_route()
        route["courses"][1]["requires"] = ["nope"]
        g = build(route, mini_curriculums())
        self.assertTrue(any(i["kind"] == "unknown_course_requires" for i in g["issues"]))

    def test_unknown_knowledge_prereq_reported(self):
        g = build(mini_route(), mini_curriculums(
            k2_requires=[{"course_id": "c1", "knowledge_id": "K9", "why": "w"}]))
        self.assertTrue(any(i["kind"] == "unknown_knowledge_requires" for i in g["issues"]))

    def test_prereq_mismatch_reported(self):
        route = mini_route()
        route["courses"][1]["requires"] = []          # route 说没有前置
        g = build(route, mini_curriculums())           # declares 说 requires c1
        self.assertTrue(any(i["kind"] == "prereq_mismatch" for i in g["issues"]))

    def test_unlocks_mismatch_reported(self):
        cur = mini_curriculums()
        cur["c1"]["declares"]["unlocks"] = [{"course_id": "c3"}]   # 实际 c1 只解锁 c2
        g = build(mini_route(), cur)
        self.assertTrue(any(i["kind"] == "unlocks_mismatch" for i in g["issues"]))

    def test_course_not_in_route_reported(self):
        cur = mini_curriculums()
        cur["cX"] = {"course_id": "cX", "declares": {"knowledge": []}}
        g = build(mini_route(), cur)
        self.assertTrue(any(i["kind"] == "course_not_in_route" for i in g["issues"]))


class TestCycles(unittest.TestCase):

    def test_no_cycle(self):
        g = build(mini_route(), mini_curriculums(
            k2_requires=[{"course_id": "c1", "knowledge_id": "K1", "why": ""}]))
        self.assertEqual(find_cycles(g), [])

    def test_detects_knowledge_cycle(self):
        # c1:K1 依赖 c2:K1，同时 c2:K1 依赖 c1:K1
        cur = mini_curriculums(
            k1_requires=[{"course_id": "c2", "knowledge_id": "K1", "why": ""}],
            k2_requires=[{"course_id": "c1", "knowledge_id": "K1", "why": ""}])
        g = build(mini_route(), cur)
        cycles = find_cycles(g)
        self.assertTrue(cycles)
        self.assertTrue(any(i["kind"] == "cycle" for i in g["issues"]))

    def test_detects_course_cycle(self):
        route = mini_route()
        route["courses"][0]["requires"] = ["c3"]        # c1<-c3 造成环
        g = build(route, mini_curriculums())
        self.assertTrue(find_cycles(g, "course"))

    def test_shorthand_self_loop_is_caught(self):
        """字符串 requires 是同课简写；写成自己会形成自环，必须报出来。"""
        cur = {"c1": {"course_id": "c1", "declares": {"prerequisites": [], "unlocks": [], "knowledge": [
            {"id": "K1", "name": "A", "level": "must", "keywords": [["a"]], "requires": ["K1"]}]}}}
        route = {"title": "t", "entry": {"name": "e", "note": ""},
                 "courses": [{"course_id": "c1", "title": "C1", "requires": []}]}
        g = build(route, cur)
        self.assertTrue(find_cycles(g))
        self.assertTrue(any(i["kind"] == "cycle" for i in g["issues"]))


class TestTopo(unittest.TestCase):

    def test_topo_respects_deps(self):
        order = topo_order_courses(build(mini_route(), mini_curriculums()))
        self.assertLess(order.index("c1"), order.index("c2"))
        self.assertLess(order.index("c2"), order.index("c3"))

    def test_topo_handles_diamond(self):
        route = {"courses": [
            {"course_id": "a", "title": "A", "requires": []},
            {"course_id": "b", "title": "B", "requires": ["a"]},
            {"course_id": "c", "title": "C", "requires": ["a"]},
            {"course_id": "d", "title": "D", "requires": ["b", "c"]},
        ], "entry": {"name": "e", "note": ""}, "title": "t"}
        order = topo_order_courses(build(route, {}))
        self.assertEqual(order[0], "a")
        self.assertEqual(order[-1], "d")


class TestReadiness(unittest.TestCase):

    def setUp(self):
        self.g = build(mini_route(), mini_curriculums())

    def test_all_available_at_start(self):
        st = course_status(self.g, {})
        self.assertEqual(st["c1"]["status"], AVAILABLE)
        self.assertEqual(st["c2"]["status"], LOCKED)     # 缺 c1
        self.assertEqual(st["c3"]["status"], LOCKED)

    def test_passed_unlocks_next(self):
        st = course_status(self.g, {"lessons": {"c1": {"passed": True, "mastery": 0.9}}})
        self.assertEqual(st["c1"]["status"], PASSED)
        self.assertEqual(st["c2"]["status"], AVAILABLE)
        self.assertEqual(st["c3"]["status"], LOCKED)

    def test_in_progress(self):
        st = course_status(self.g, {"lessons": {"c1": {"passed": False, "mastery": 0.5}}})
        self.assertEqual(st["c1"]["status"], IN_PROGRESS)

    def test_missing_prereqs_listed(self):
        st = course_status(self.g, {})
        self.assertEqual(st["c3"]["missing_prerequisites"], ["c2"])

    def test_reflow_points_attached_to_course(self):
        st = course_status(self.g, {"atoms": {
            kp_id("c2", "K1"): {"mastery": 0.6, "passed": False, "review_queue": True}}})
        self.assertEqual(st["c2"]["reflow_points"], [kp_id("c2", "K1")])

    def test_unlock_path_transitive(self):
        self.assertEqual(unlock_path(self.g, "c3"), ["c1", "c2"])


class TestKnowledgeStatus(unittest.TestCase):

    def setUp(self):
        self.g = build(mini_route(), mini_curriculums(
            k2_requires=[{"course_id": "c1", "knowledge_id": "K1", "why": "w"}]))

    def test_blocked_when_prereq_unpassed(self):
        st = knowledge_status(self.g, {}, "c2")
        self.assertEqual(st[kp_id("c2", "K1")]["status"], "blocked")
        self.assertEqual(st[kp_id("c2", "K1")]["blocked_by"], [kp_id("c1", "K1")])

    def test_untouched_when_prereq_passed(self):
        st = knowledge_status(self.g, {"atoms": {
            kp_id("c1", "K1"): {"mastery": 0.9, "passed": True}}}, "c2")
        self.assertEqual(st[kp_id("c2", "K1")]["status"], "untouched")

    def test_weak_when_in_review_queue(self):
        st = knowledge_status(self.g, {"atoms": {
            kp_id("c2", "K1"): {"mastery": 0.6, "passed": False, "review_queue": True}}}, "c2")
        self.assertEqual(st[kp_id("c2", "K1")]["status"], "weak")

    def test_passed_wins(self):
        st = knowledge_status(self.g, {"atoms": {
            kp_id("c2", "K1"): {"mastery": 0.9, "passed": True}}}, "c2")
        self.assertEqual(st[kp_id("c2", "K1")]["status"], PASSED)


class TestRender(unittest.TestCase):

    def test_course_mermaid_has_all_courses(self):
        g = build(mini_route(), mini_curriculums())
        m = course_dag_mermaid(g, course_status(g, {}))
        self.assertTrue(m.startswith("flowchart LR"))
        for cid in ("c1", "c2", "c3"):
            self.assertIn(f"n_{cid}[", m)
        self.assertIn("class ", m)

    def test_knowledge_mermaid_marks_external_prereq(self):
        g = build(mini_route(), mini_curriculums(
            k2_requires=[{"course_id": "c1", "knowledge_id": "K1", "why": "w"}]))
        m = knowledge_mermaid(g, "c2", knowledge_status(g, {}, "c2"))
        self.assertIn("n_c1_K1[/", m)          # 外部节点用斜框
        self.assertIn("-.->", m)               # 前置用虚线

    def test_route_text_contains_status(self):
        g = build(mini_route(), mini_curriculums())
        t = route_text(g, course_status(g, {}))
        self.assertIn("可开始", t)
        self.assertIn("未解锁", t)


class TestRealData(unittest.TestCase):
    """用真实 route.json + curriculum/*.json 校验：无环、无未知引用、declares 与 route 一致。"""

    @classmethod
    def setUpClass(cls):
        cls.graph = build(load_route(os.path.join(BASE, "route.json")),
                          load_curriculums(os.path.join(BASE, "curriculum")))

    def test_no_fatal_issues(self):
        fatal = [i for i in self.graph["issues"]
                 if i["kind"] == "cycle" or i["kind"].startswith("unknown")]
        self.assertEqual(fatal, [], f"发现致命图问题: {fatal}")

    def test_no_consistency_issues(self):
        cons = [i for i in self.graph["issues"]
                if i["kind"] in ("prereq_mismatch", "unlocks_mismatch")]
        self.assertEqual(cons, [], f"declares 与 route 不一致: {cons}")

    def test_route_is_a_dag(self):
        self.assertEqual(self.graph["issues"].count(
            {"kind": "cycle"}), 0)

    def test_nine_courses_in_topo(self):
        order = topo_order_courses(self.graph)
        self.assertEqual(len(order), 9)
        self.assertLess(order.index("py-agent-02"), order.index("py-agent-03"))
        self.assertLess(order.index("py-agent-07"), order.index("py-agent-08"))

    def test_lesson3_has_cross_course_prereqs(self):
        """第 3 课的知识点必须真的连回第 1/2 课——这是『体系化』的证据。"""
        targets = set()
        for e in self.graph["edges"]:
            if e["type"] == "requires" and e["dst"].startswith("py-agent-03:"):
                targets.add(e["src"].split(":")[0])
        self.assertIn("py-agent-02", targets)
        self.assertIn("py-agent-01", targets)

    def test_empty_shell_courses_are_visible(self):
        """route 声明了课、却没有 declares 的，必须被显式列出来。

        这条曾经是一份**待补台账**（py-agent-04..09 六门空壳），现在已全部补齐，
        所以断言空列表。保留这条测试是为了两件事：
          (1) 将来再加课程时若忘了写内容，跑测试就会立刻发现；
          (2) 它记录过「9 门课里 6 门是空壳也一直没人发现」这个真实教训——
              当时建图不报错、门禁不报错，学习者一路学到第 4 课才撞墙。
        """
        missing = sorted(i["course"] for i in self.graph["issues"]
                         if i["kind"] == "missing_curriculum")
        self.assertEqual(missing, [],
                         f"又出现空壳课程了：{missing}")


class TestMasteryConsistency(unittest.TestCase):
    """掌握度状态与图的自洽性：绕过前置必须被报出来，而不是默默显示"已通过"。"""

    def setUp(self):
        self.g = build(mini_route(), mini_curriculums(
            k2_requires=[{"course_id": "c1", "knowledge_id": "K1", "why": "w"}]))

    def _kinds(self, state):
        return [i["kind"] for i in mastery_consistency(self.g, state)]

    def test_clean_state_has_no_issues(self):
        state = {"lessons": {"c1": {"passed": True}},
                 "atoms": {kp_id("c1", "K1"): {"passed": True}}}
        self.assertEqual(mastery_consistency(self.g, state), [])

    def test_detects_course_passed_without_prereqs(self):
        state = {"lessons": {"c3": {"passed": True}}}       # c3 需要 c2，c2 未通过
        kinds = self._kinds(state)
        self.assertIn("course_passed_without_prereqs", kinds)

    def test_detects_knowledge_passed_without_prereqs(self):
        state = {"atoms": {kp_id("c2", "K1"): {"passed": True}}}   # 前置 c1:K1 未通过
        kinds = self._kinds(state)
        self.assertIn("knowledge_passed_without_prereqs", kinds)

    def test_unpassed_states_never_reported(self):
        state = {"lessons": {"c3": {"passed": False}},
                 "atoms": {kp_id("c2", "K1"): {"passed": False, "review_queue": True}}}
        self.assertEqual(mastery_consistency(self.g, state), [])

    def test_reflowed_prereq_keeps_state_consistent(self):
        """回炉把前置打成未通过后，本课若仍标记已通过，就应报矛盾。"""
        state = {"lessons": {"c1": {"passed": True}},
                 "atoms": {kp_id("c1", "K1"): {"passed": True}}}
        self.assertEqual(mastery_consistency(self.g, state), [])
        reflow(state, [kp_id("c1", "K1")])                  # 前置被打回
        self.assertIn("knowledge_passed_without_prereqs",
                      self._kinds({"atoms": {kp_id("c2", "K1"): {"passed": True},
                                             kp_id("c1", "K1"): state["atoms"][kp_id("c1", "K1")]}}))


class TestCascadeRecheck(unittest.TestCase):
    """回炉的级联影响：依赖被打回知识点的上层【已通过】点应被标为待复查，但不翻转 passed。"""

    def _chain_graph(self):
        # 注意：字符串形式 "K1" 是【同课简写】，跨课必须用 dict 显式写 course_id，
        # 否则 c2:K1 会变成"要求自己"（自环）。
        cur = {
            "c1": {"course_id": "c1", "declares": {"prerequisites": [], "unlocks": [
                {"course_id": "c2"}], "knowledge": [
                {"id": "K1", "name": "A", "level": "must", "keywords": [["a"]], "requires": []}]}},
            "c2": {"course_id": "c2", "declares": {"prerequisites": [
                {"course_id": "c1"}], "unlocks": [{"course_id": "c3"}], "knowledge": [
                {"id": "K1", "name": "B", "level": "must", "keywords": [["b"]], "requires": [
                    {"course_id": "c1", "knowledge_id": "K1", "why": "w"}]}]}},
            "c3": {"course_id": "c3", "declares": {"prerequisites": [
                {"course_id": "c2"}], "unlocks": [], "knowledge": [
                {"id": "K1", "name": "C", "level": "must", "keywords": [["c"]], "requires": [
                    {"course_id": "c2", "knowledge_id": "K1", "why": "w"}]}]}},
        }
        return build(mini_route(), cur)

    def _all_passed(self):
        return {"atoms": {kp_id(c, "K1"): {"mastery": 0.9, "passed": True}
                          for c in ("c1", "c2", "c3")}}

    def test_marks_direct_and_transitive_dependents(self):
        g = self._chain_graph()
        state = self._all_passed()
        reflow(state, [kp_id("c1", "K1")])
        marked = cascade_recheck(g, state, [kp_id("c1", "K1")])
        by_id = {m["id"]: m for m in marked}
        self.assertEqual(by_id[kp_id("c2", "K1")]["depth"], 1)
        self.assertEqual(by_id[kp_id("c3", "K1")]["depth"], 2)
        self.assertTrue(state["atoms"][kp_id("c2", "K1")]["recheck_due"])
        self.assertEqual(state["atoms"][kp_id("c2", "K1")]["recheck_depth"], 1)

    def test_does_not_flip_passed(self):
        g = self._chain_graph()
        state = self._all_passed()
        reflow(state, [kp_id("c1", "K1")])
        cascade_recheck(g, state, [kp_id("c1", "K1")])
        self.assertTrue(state["atoms"][kp_id("c2", "K1")]["passed"])   # 进度没被抹掉
        self.assertEqual(state["atoms"][kp_id("c2", "K1")]["mastery"], 0.9)

    def test_recheck_silences_consistency_issue(self):
        g = self._chain_graph()
        state = self._all_passed()
        reflow(state, [kp_id("c1", "K1")])
        before = [i for i in mastery_consistency(g, state)
                  if i["kind"] == "knowledge_passed_without_prereqs"]
        self.assertTrue(before)                       # 先会报矛盾
        cascade_recheck(g, state, [kp_id("c1", "K1")])
        after = [i for i in mastery_consistency(g, state)
                 if i["kind"] == "knowledge_passed_without_prereqs"]
        self.assertEqual(after, [])                   # 标了待复查后不再算矛盾

    def test_already_unpassed_not_marked(self):
        g = self._chain_graph()
        state = {"atoms": {kp_id("c1", "K1"): {"mastery": 0.9, "passed": True},
                           kp_id("c2", "K1"): {"mastery": 0.4, "passed": False}}}
        reflow(state, [kp_id("c1", "K1")])
        marked = cascade_recheck(g, state, [kp_id("c1", "K1")])
        self.assertNotIn(kp_id("c2", "K1"), [m["id"] for m in marked])

    def test_does_not_mark_the_knocked_back_node_itself(self):
        g = self._chain_graph()
        state = self._all_passed()
        reflow(state, [kp_id("c1", "K1")])
        cascade_recheck(g, state, [kp_id("c1", "K1")])
        self.assertNotIn("recheck_due", state["atoms"][kp_id("c1", "K1")])

    def test_no_marking_when_nothing_passed(self):
        g = self._chain_graph()
        self.assertEqual(cascade_recheck(g, {"atoms": {}}, [kp_id("c1", "K1")]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
