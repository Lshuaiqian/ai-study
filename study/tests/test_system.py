"""知识体系与拆分器的单测（纯逻辑，不联网）。

运行：python -m unittest discover -s study/tests
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system import (apply_placement, course_index, derived_unlocks,   # noqa: E402
                    find_course_cycles, knowledge_index, load_placement,
                    load_system, placement_report, protected_ids, split_all,
                    summary, to_curriculum, to_route, topo_courses,
                    validate_system, write_derived)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM_PATH = os.path.join(BASE, "system", "west2-ai-2026.json")


def mini_system():
    return {
        "system_id": "mini",
        "title": "迷你体系",
        "dimensions": [{"id": "D1", "name": "基础"}],
        "stages": [{"id": "s1", "name": "阶段一"}, {"id": "s2", "name": "阶段二"}],
        "knowledge": [
            {"id": "a.one", "name": "知识点一", "dim": "D1", "level": "must",
             "keywords": [["一"]]},
            {"id": "a.two", "name": "知识点二", "dim": "D1", "level": "should",
             "keywords": [["二"]]},
            {"id": "a.orphan", "name": "没人讲的知识点", "dim": "D1", "level": "must",
             "keywords": [["孤儿"]]},
        ],
        "courses": [
            {"course_id": "c1", "title": "第一课", "stage": "s1", "requires": [],
             "knowledge": ["a.one"], "tasks": [{"id": "t1", "type": "code", "title": "做点啥"}]},
            {"course_id": "c2", "title": "第二课", "stage": "s2", "requires": ["c1"],
             "knowledge": ["a.two"], "tasks": [{"id": "t2", "type": "note", "title": "写笔记"}]},
        ],
    }


class TestValidate(unittest.TestCase):

    def test_mini_has_only_the_orphan_issue(self):
        kinds = [i["kind"] for i in validate_system(mini_system())]
        self.assertEqual(kinds, ["knowledge_not_taught"])

    def test_duplicate_knowledge(self):
        s = mini_system()
        s["knowledge"].append(dict(s["knowledge"][0]))
        kinds = [i["kind"] for i in validate_system(s)]
        self.assertIn("duplicate_knowledge", kinds)

    def test_unknown_dimension(self):
        s = mini_system()
        s["knowledge"][0]["dim"] = "D9"
        self.assertIn("unknown_dimension", [i["kind"] for i in validate_system(s)])

    def test_unknown_course_requires(self):
        s = mini_system()
        s["courses"][1]["requires"] = ["nope"]
        self.assertIn("unknown_course_requires", [i["kind"] for i in validate_system(s)])

    def test_unknown_knowledge_ref(self):
        s = mini_system()
        s["courses"][0]["knowledge"] = ["nope"]
        kinds = [i["kind"] for i in validate_system(s)]
        self.assertIn("unknown_knowledge_ref", kinds)

    def test_missing_keywords_flagged(self):
        s = mini_system()
        s["knowledge"][0].pop("keywords")
        self.assertIn("knowledge_without_keywords",
                      [i["kind"] for i in validate_system(s)])

    def test_course_without_tasks_flagged(self):
        s = mini_system()
        s["courses"][0]["tasks"] = []
        self.assertIn("course_without_tasks", [i["kind"] for i in validate_system(s)])

    def test_cycle_detected(self):
        s = mini_system()
        s["courses"][0]["requires"] = ["c2"]
        kinds = [i["kind"] for i in validate_system(s)]
        self.assertIn("course_cycle", kinds)
        self.assertTrue(find_course_cycles(s))

    def test_bad_level_flagged(self):
        s = mini_system()
        s["knowledge"][0]["level"] = "maybe"
        self.assertIn("bad_level", [i["kind"] for i in validate_system(s)])


class TestTopo(unittest.TestCase):

    def test_order_respects_requires(self):
        order = topo_courses(mini_system())
        self.assertLess(order.index("c1"), order.index("c2"))

    def test_unlocks_are_derived_not_written(self):
        s = mini_system()
        un = derived_unlocks(s)
        self.assertEqual(un["c1"], ["c2"])
        self.assertEqual(un["c2"], [])


class TestToCurriculum(unittest.TestCase):

    def test_local_k_ids_are_sequential_and_traceable(self):
        s = mini_system()
        cur = to_curriculum(s, s["courses"][0])
        self.assertEqual(len(cur["declares"]["knowledge"]), 1)
        k = cur["declares"]["knowledge"][0]
        self.assertEqual(k["id"], "K1")
        self.assertEqual(k["source_knowledge"], "a.one")
        self.assertEqual(k["level"], "must")

    def test_prerequisites_carry_titles(self):
        s = mini_system()
        cur = to_curriculum(s, s["courses"][1])
        self.assertEqual(cur["declares"]["prerequisites"],
                         [{"course_id": "c1", "name": "第一课"}])

    def test_unlocks_carry_titles(self):
        s = mini_system()
        cur = to_curriculum(s, s["courses"][0])
        self.assertEqual(cur["declares"]["unlocks"],
                         [{"course_id": "c2", "name": "第二课"}])

    def test_note_task_gets_note_acceptance(self):
        s = mini_system()
        cur = to_curriculum(s, s["courses"][1])
        self.assertIn("覆盖本课全部必会知识点", cur["tasks"][0]["acceptance"])

    def test_code_task_gets_code_acceptance(self):
        s = mini_system()
        cur = to_curriculum(s, s["courses"][0])
        self.assertIn("能跑通并产出非空结果", cur["tasks"][0]["acceptance"])

    def test_explicit_acceptance_is_preserved(self):
        s = mini_system()
        s["courses"][0]["tasks"][0]["acceptance"] = ["自定义标准"]
        cur = to_curriculum(s, s["courses"][0])
        self.assertEqual(cur["tasks"][0]["acceptance"], ["自定义标准"])

    def test_gate_defaults_present(self):
        cur = to_curriculum(mini_system(), mini_system()["courses"][0])
        self.assertIn("min_mastery", cur["gate"])
        self.assertIn("min_each", cur["gate"])

    def test_split_all_covers_every_course(self):
        s = mini_system()
        self.assertEqual(sorted(split_all(s)), ["c1", "c2"])

    def test_route_shape(self):
        route = to_route(mini_system())
        self.assertEqual(len(route["courses"]), 2)
        self.assertIn("请勿手改", route["note"])


class TestSummaryAndWrite(unittest.TestCase):

    def test_summary_counts(self):
        s = summary(mini_system())
        self.assertEqual(s["courses"], 2)
        self.assertEqual(s["knowledge"], 3)
        self.assertEqual(s["must"], 2)
        self.assertEqual(s["should"], 1)

    def test_write_derived_dry_run_touches_nothing(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="study_sys_")
        paths = write_derived(mini_system(), d, dry_run=True)
        self.assertTrue(paths)
        self.assertFalse(os.path.exists(os.path.join(d, "route.json")))

    def test_write_derived_writes_files(self):
        import json
        import tempfile
        d = tempfile.mkdtemp(prefix="study_sys2_")
        write_derived(mini_system(), d, dry_run=False)
        with open(os.path.join(d, "route.json"), encoding="utf-8") as f:
            route = json.load(f)
        self.assertEqual(len(route["courses"]), 2)
        with open(os.path.join(d, "curriculum", "c1.json"), encoding="utf-8") as f:
            cur = json.load(f)
        self.assertEqual(cur["course_id"], "c1")


class TestRealSystem(unittest.TestCase):
    """真实体系文件必须自洽——这是自上而下流程最容易出错的地方。"""

    @classmethod
    def setUpClass(cls):
        cls.system = load_system(SYSTEM_PATH)

    def test_no_issues(self):
        issues = validate_system(self.system)
        self.assertEqual(issues, [], f"体系有问题：{issues}")

    def test_scale(self):
        s = summary(self.system)
        self.assertGreaterEqual(s["courses"], 10)
        self.assertGreaterEqual(s["knowledge"], 40)
        self.assertEqual(s["dimensions"], 7)

    def test_foundation_is_linear(self):
        courses = course_index(self.system)
        for i in range(1, 5):
            cur = courses[f"west2-f{i}"]
            self.assertEqual(cur["requires"], [f"west2-f{i-1}"])

    def test_application_branch_requires_foundation(self):
        courses = course_index(self.system)
        self.assertEqual(courses["west2-a0"]["requires"], ["west2-f4"])
        self.assertEqual(courses["west2-a1"]["requires"], ["west2-a0"])
        self.assertEqual(courses["west2-r1"]["requires"], ["west2-f4"])

    def test_every_knowledge_is_taught(self):
        know = knowledge_index(self.system)
        taught = set()
        for c in self.system["courses"]:
            taught.update(c["knowledge"])
        self.assertEqual(set(know) - taught, set())

    def test_topology_starts_at_foundation(self):
        order = topo_courses(self.system)
        self.assertEqual(order[0], "west2-f0")

    def test_every_course_splits(self):
        for cid, cur in split_all(self.system).items():
            self.assertTrue(cur["declares"]["knowledge"], f"{cid} 没有知识点")
            self.assertTrue(cur["tasks"], f"{cid} 没有任务")
            for k in cur["declares"]["knowledge"]:
                self.assertTrue(k["keywords"], f"{cid}:{k['id']} 缺 keywords")

    def test_every_point_has_source_knowledge(self):
        """桥接要把体系全局 id 翻译成课程本地 K-id，缺了 source_knowledge 就翻不了。"""
        for cid, cur in split_all(self.system).items():
            for k in cur["declares"]["knowledge"]:
                self.assertTrue(k.get("source_knowledge"),
                                f"{cid}:{k['id']} 缺 source_knowledge")

    def test_local_k_ids_are_unique_within_course(self):
        for cid, cur in split_all(self.system).items():
            ids = [k["id"] for k in cur["declares"]["knowledge"]]
            self.assertEqual(len(ids), len(set(ids)), f"{cid} 的 K-id 有重复：{ids}")

    def test_foundation_courses_carry_self_check_with_points(self):
        """自检题是 quiz 维度能被结构化判分的唯一依据，Foundation 五课必须有。"""
        for i in range(5):
            cur = self.system["courses"][i]
            self.assertTrue(cur.get("self_check"), f"{cur['course_id']} 缺自检题")
            for q in cur["self_check"]:
                self.assertTrue(q.get("question"), f"{cur['course_id']} 有题为空")
                self.assertGreaterEqual(len(q.get("points") or []), 2,
                                        f"{cur['course_id']} {q.get('id')} 判定点太少")


PLACEMENT_PATH = os.path.join(BASE, "system", "placement-west2.json")


class TestPlacement(unittest.TestCase):
    """学习位置：把「你已经会什么」应用到课程上，但**不改课程内容本身**。"""

    def _placement(self):
        return {
            "placement_id": "mini@me",
            "assessed_at": "2026-01-01",
            "knowledge_status": {
                "a.one": {"status": "met", "evidence": "有产物"},
                "a.two": {"status": "partial", "evidence": "半会"},
            },
            "weak_points": [{"knowledge": "a.two", "issue": "反复错", "action": "回炉"}],
            "evidence": [{"source": "x", "says": "y"}],
        }

    def test_marks_prior_status(self):
        s = mini_system()
        cur = to_curriculum(s, s["courses"][0], self._placement())
        k = cur["declares"]["knowledge"][0]
        self.assertEqual(k["prior_status"], "met")
        self.assertEqual(k["prior_label"], "已具备")
        self.assertEqual(k["prior_evidence"], "有产物")

    def test_unknown_when_no_record(self):
        s = mini_system()
        cur = to_curriculum(s, s["courses"][1], {**self._placement(), "knowledge_status": {}})
        self.assertEqual(cur["declares"]["knowledge"][0]["prior_status"], "unknown")

    def test_focus_excludes_met(self):
        s = mini_system()
        cur = to_curriculum(s, s["courses"][1], self._placement())
        p = cur["placement"]
        self.assertEqual(p["met_count"], 0)          # a.two 是 partial，不算
        self.assertEqual([f["id"] for f in p["focus"]], ["K1"])

    def test_weak_point_flagged_on_knowledge(self):
        s = mini_system()
        cur = to_curriculum(s, s["courses"][1], self._placement())
        self.assertTrue(cur["declares"]["knowledge"][0]["is_weak_point"])
        self.assertEqual(len(cur["placement"]["weak_points"]), 1)

    def test_likely_fast_pass(self):
        s = mini_system()
        cur = to_curriculum(s, s["courses"][0], self._placement())
        self.assertTrue(cur["placement"]["likely_fast_pass"])
        self.assertEqual(cur["placement"]["remaining_ids"], [])

    def test_does_not_mutate_input(self):
        s = mini_system()
        before = json.dumps(s, ensure_ascii=False, sort_keys=True)
        to_curriculum(s, s["courses"][0], self._placement())
        self.assertEqual(json.dumps(s, ensure_ascii=False, sort_keys=True), before)

    def test_no_placement_means_no_block(self):
        cur = to_curriculum(mini_system(), mini_system()["courses"][0])
        self.assertNotIn("placement", cur)

    def test_report_next_course_and_rows(self):
        rep = placement_report(mini_system(), self._placement())
        self.assertTrue(rep["has_placement"])
        self.assertEqual(len(rep["rows"]), 2)
        self.assertEqual(rep["done_courses"], ["c1"])      # c1 的唯一知识点是 met
        self.assertEqual(rep["next_course"]["course_id"], "c2")
        self.assertEqual([f["knowledge"] for f in rep["focus"]], ["a.two"])

    def test_report_without_placement(self):
        self.assertFalse(placement_report(mini_system(), None)["has_placement"])


class TestRealPlacement(unittest.TestCase):
    """真实位置文件必须只引用体系里存在的知识点——否则会标出幽灵状态。"""

    @classmethod
    def setUpClass(cls):
        cls.system = load_system(SYSTEM_PATH)
        cls.placement = load_placement(PLACEMENT_PATH)

    def test_placement_file_exists(self):
        self.assertIsNotNone(self.placement, "缺 placement-west2.json")

    def test_every_status_key_is_a_real_knowledge_id(self):
        know = knowledge_index(self.system)
        unknown = [k for k in (self.placement.get("knowledge_status") or {})
                   if k not in know]
        self.assertEqual(unknown, [], f"位置文件引用了不存在的知识点：{unknown}")

    def test_every_weak_point_is_a_real_knowledge_id(self):
        know = knowledge_index(self.system)
        bad = [w["knowledge"] for w in self.placement.get("weak_points") or []
               if w["knowledge"] not in know]
        self.assertEqual(bad, [])

    def test_every_status_has_evidence(self):
        for kid, rec in (self.placement.get("knowledge_status") or {}).items():
            self.assertIn(rec.get("status"),
                          ("met", "partial", "unknown", "not_started"), kid)
            self.assertTrue(rec.get("evidence"), f"{kid} 缺证据")

    def test_report_is_consistent_with_system(self):
        rep = placement_report(self.system, self.placement)
        self.assertEqual(len(rep["rows"]), len(self.system["courses"]))
        self.assertTrue(rep["next_course"], "应有下一步建议")
        # 已具备的课必须排在未具备的课前面（拓扑序里第一门未完成的就是下一步）
        codes = [r["course_id"] for r in rep["rows"]]
        self.assertLess(codes.index(rep["next_course"]["course_id"]),
                        len(codes))

    def test_carried_over_uses_local_knowledge_ids(self):
        """回归：placement 字典里 met 用本地 id、carried_over 却用体系级 id。

        两套 id 空间混在一起时，`protected_ids()` 返回的挂账点永远匹配不上
        任何知识点，挂账会静默失去保护、被整理误判成未通过（实测 F0 的 4 个挂账点）。
        """
        for course in self.system["courses"]:
            cid = course["course_id"]
            cur = to_curriculum(self.system, course, self.placement)
            local = {k["id"] for k in cur["declares"]["knowledge"]}
            p = cur.get("placement") or {}
            for field in ("met", "partial", "unknown", "not_started",
                          "carried_over"):
                stray = [x for x in (p.get(field) or []) if x not in local]
                self.assertEqual(stray, [],
                                 f"{cid}.placement.{field} 混进了非本地 id：{stray}")

    def test_protected_ids_match_knowledge_points(self):
        for course in self.system["courses"]:
            cur = to_curriculum(self.system, course, self.placement)
            local = {k["id"] for k in cur["declares"]["knowledge"]}
            stray = protected_ids(cur) - local
            self.assertEqual(stray, set(),
                             f"{course['course_id']} 的保护集混进了外部 id：{stray}")

    def test_fast_pass_courses_protect_all_points(self):
        """快速过的课：met + carried_over 必须覆盖全部知识点，否则挂账会漏。"""
        for course in self.system["courses"]:
            cur = to_curriculum(self.system, course, self.placement)
            p = cur.get("placement") or {}
            if not p.get("fast_pass"):
                continue
            local = {k["id"] for k in cur["declares"]["knowledge"]}
            self.assertEqual(protected_ids(cur), local,
                             f"{course['course_id']} 是快速过，但有知识点既非"
                             f"met 也未挂账：{sorted(local - protected_ids(cur))}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
