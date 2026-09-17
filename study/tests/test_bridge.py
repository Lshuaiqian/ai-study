# -*- coding: utf-8 -*-
"""老 9 课 × 西二内容的桥接校验（纯逻辑 + 读真实文件，不联网）。

为什么这些检查值得写死成测试：
  - **keywords 写坏不会有任何报错**，只会让覆盖率恒 0 或恒 1。这是最隐蔽的失效方式。
  - **知识点改号**会让 mastery.json 里的历史原子集体失配，也是静默的。
  - **西二知识点漏接管**（没人补也没人排除）正是「9 门课里 6 门是空壳」的成因。

运行：python -m unittest discover -s study/tests
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, STUDY)

from notedoctor.doctor import check_coverage                       # noqa: E402
from system.merge_py9 import (APPEND_COURSES, BRIDGE_DIR,          # noqa: E402
                              CURRICULUM_DIR, NEW_COURSES, ROUTE_PATH,
                              SYSTEM_PATH, bridge_offset, load_bridges,
                              load_json)

LEDGER = os.path.join(BRIDGE_DIR, "_index.json")
COURSES = NEW_COURSES + APPEND_COURSES

# 一段"什么知识点都没讲"的泛泛中文笔记：任何知识点被它覆盖，就说明 keywords 太宽
GENERIC_NOTE = (
    "我学了 Python，写了一些代码，跑通了程序，感觉很有收获，继续加油。\n"
    "今天看了文档，理解了基本概念，做了练习，也复习了前面的内容。\n"
    "工具很好用，环境也装好了，笔记记了一些要点，下次继续深入。\n"
)


def curriculum_path(cid):
    return os.path.join(CURRICULUM_DIR, cid.replace("-", "_") + ".json")


class TestBridges(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.system = load_json(SYSTEM_PATH)
        cls.kp_index = {k["id"]: k for k in cls.system["knowledge"]}
        cls.route = load_json(ROUTE_PATH)
        cls.bridges = load_bridges()
        cls.ledger = load_json(LEDGER)

    def live_ids(self, cid):
        path = curriculum_path(cid)
        if not os.path.isfile(path):
            return []                      # 还没生成过的课（生成前跑测试的正常情况）
        with open(path, encoding="utf-8") as f:
            cur = json.load(f)
        return [k["id"] for k in cur["declares"]["knowledge"]]

    def bridge_offset(self, cid):
        # 与生成器共用同一个函数：两边各算一套的话，第二次运行就会漂移
        return bridge_offset(cid, self.bridges[cid])

    # ---------- 覆盖完整性 ----------

    def test_every_course_has_a_bridge(self):
        missing = [c for c in COURSES if c not in self.bridges]
        self.assertEqual(missing, [], f"这些课还没有 bridge：{missing}")

    def test_no_extra_bridges(self):
        extra = sorted(set(self.bridges) - set(COURSES))
        self.assertEqual(extra, [], f"多了不该有的 bridge：{extra}")

    # ---------- 台账 ----------

    def test_ledger_partitions_all_west2_knowledge(self):
        """54 个西二知识点必须每个都恰好有归宿：老课已有 / 新增 / 显式排除。"""
        buckets = {}
        for name in ("existing", "planned", "excluded"):
            buckets[name] = {k for k in (self.ledger.get(name) or {})
                             if k != "comment"}
        all_kp = set(self.kp_index)
        union = set().union(*buckets.values())
        self.assertEqual(sorted(all_kp - union), [],
                         "这些西二知识点没有任何归宿（既没补也没排除）")
        self.assertEqual(sorted(union - all_kp), [],
                         "台账引用了不存在的西二知识点")
        for a, b in (("existing", "planned"), ("existing", "excluded"),
                     ("planned", "excluded")):
            dup = sorted(buckets[a] & buckets[b])
            self.assertEqual(dup, [], f"{a} 与 {b} 重复登记：{dup}")

    def test_excluded_is_f0_and_documented(self):
        """F0 的 9 个点被显式排除，而且要留下代价说明——不许静默丢弃。"""
        excluded = {k: v for k, v in self.ledger["excluded"].items()
                    if k != "comment"}
        f0 = {k for k, v in self.kp_index.items()
              if v["id"].split(".")[0] in ("env", "git", "md", "code", "algo")}
        self.assertEqual(sorted(excluded), sorted(f0))
        cons = self.ledger.get("excluded_consequence") or {}
        self.assertTrue(cons.get("highest_cost"), "排除 F0 必须留下代价说明")
        self.assertEqual(sorted(cons.get("was_carried_over") or []),
                         sorted(["env.ide", "git.spec", "md.apple", "algo.basic"]))

    def test_existing_targets_really_exist_in_curricula(self):
        """台账说『老课已经覆盖了』的目标必须真的存在于当前课程文件里。"""
        live = set()
        for name in os.listdir(CURRICULUM_DIR):        # 全部课程，不只是桥接过的
            if not name.endswith(".json"):
                continue
            with open(os.path.join(CURRICULUM_DIR, name), encoding="utf-8") as f:
                cur = json.load(f)
            cid = cur.get("course_id")
            for k in (cur.get("declares") or {}).get("knowledge") or []:
                live.add(f"{cid}:{k['id']}")
        for src, target in self.ledger["existing"].items():
            if src == "comment":
                continue
            for t in (target if isinstance(target, list) else [target]):
                self.assertIn(t, live, f"台账说 {src} → {t}，但课程里没有它")
    def test_planned_matches_bridge_reality(self):
        planned = {k: v for k, v in self.ledger["planned"].items()
                   if k != "comment"}
        actual = {}
        for cid, b in self.bridges.items():
            off = self.bridge_offset(cid)
            for i, k in enumerate(b["knowledge"], start=1):
                if k.get("from"):
                    actual.setdefault(k["from"], []).append(f"{cid}:K{off + i}")
        self.assertEqual(sorted(set(planned) - set(actual)), [],
                         "台账 planned 里有 bridge 没接的来源")
        self.assertEqual(sorted(set(actual) - set(planned)), [],
                         "bridge 接了台账没登记的来源")
        for src, tgt in planned.items():
            self.assertIn(tgt, actual.get(src, []), f"{src} 的落点与台账不符")

    # ---------- bridge 结构 ----------

    def test_local_ids_are_contiguous(self):
        for cid, b in self.bridges.items():
            off = self.bridge_offset(cid)
            got = [k["local"] for k in b["knowledge"]]
            want = [f"K{off + i}" for i in range(1, len(got) + 1)]
            self.assertEqual(got, want, f"{cid} 的 local 编号不连续")

    def test_sourced_knowledge_does_not_redefine_name_or_keywords(self):
        """有来源就必须用来源的 name/keywords——自撰一份等于埋一颗覆盖率炸弹。"""
        for cid, b in self.bridges.items():
            for k in b["knowledge"]:
                if k.get("from"):
                    self.assertIn(k["from"], self.kp_index,
                                  f"{cid}:{k['local']} 的 from 不存在")
                    for field in ("name", "keywords", "level"):
                        self.assertNotIn(
                            field, k,
                            f"{cid}:{k['local']} 有来源却自带 {field}")

    def test_self_authored_knowledge_is_fully_specified(self):
        for cid, b in self.bridges.items():
            must = 0
            for k in b["knowledge"]:
                if k.get("from"):
                    continue
                for field in ("name", "level", "keywords"):
                    self.assertTrue(k.get(field),
                                    f"{cid}:{k['local']} 自撰条目缺 {field}")
                self.assertIn(k["level"], ("must", "should"),
                              f"{cid}:{k['local']} 的 level 只能是 must / should")
                must += k["level"] == "must"
                groups = k["keywords"]
                self.assertTrue(2 <= len(groups) <= 4,
                                f"{cid}:{k['local']} 的 keyword 组数应在 2–4")
                for g in groups:
                    self.assertTrue(g, f"{cid}:{k['local']} 有空 keyword 组")
            if any(not k.get("from") for k in b["knowledge"]):
                self.assertGreater(must, 0,
                                   f"{cid} 全是 should 级自撰知识点——门禁会永远放行")

    def test_self_authored_declared_in_ledger(self):
        declared = self.ledger.get("self_authored") or {}
        for cid, b in self.bridges.items():
            authored = [k["local"] for k in b["knowledge"] if not k.get("from")]
            if authored:
                self.assertEqual(sorted(declared.get(cid) or []), sorted(authored),
                                 f"{cid} 的自撰知识点没在台账里声明")

    def test_self_check_is_three_by_three(self):
        """新建课的自检题写在 bridge 里；追加课的自检题由生成器并进老课，见 TestMergedCurricula。"""
        for cid, b in self.bridges.items():
            if cid in APPEND_COURSES:
                continue
            self.assertEqual(len(b.get("self_check") or []), 3,
                             f"{cid} 的自检题必须是 3 题")
            for q in b["self_check"]:
                self.assertEqual(len(q.get("points") or []), 3,
                                 f"{cid}:{q.get('id')} 必须是 3 个采分点")

    def test_tasks_are_verifiable_and_include_transfer(self):
        for cid, b in self.bridges.items():
            if cid in APPEND_COURSES:
                continue               # 追加课沿用老课的任务清单
            tasks = b.get("tasks") or []
            self.assertTrue(3 <= len(tasks) <= 4, f"{cid} 任务数应在 3–4")
            kinds = [t.get("type") for t in tasks]
            self.assertIn("transfer", kinds, f"{cid} 缺 transfer 任务")
            self.assertTrue({"note", "concept"} & set(kinds),
                            f"{cid} 缺 note/concept 任务")
            local_ids = {k["local"] for k in b["knowledge"]}
            for t in tasks:
                self.assertTrue(t.get("task_id"), f"{cid} 有任务缺 task_id")
                self.assertTrue(t.get("brief"), f"{cid}:{t['task_id']} 缺 brief")
                self.assertTrue(t.get("deliverable"),
                                f"{cid}:{t['task_id']} 缺 deliverable")
                self.assertTrue(t.get("acceptance"),
                                f"{cid}:{t['task_id']} 缺可验收标准")
                self.assertTrue(set(t.get("atoms") or []) <= local_ids,
                                f"{cid}:{t['task_id']} 的 atoms 越界")

    def test_every_knowledge_point_has_seed_material(self):
        """每个知识点至少一条种子资料——否则学习库与笔记体检对它就是空的。"""
        for cid, b in self.bridges.items():
            local_ids = {k["local"] for k in b["knowledge"]}
            atoms = (b.get("materials") or {}).get("atoms") or []
            have = {a.get("knowledge_id") for a in atoms}
            lacking = sorted(local_ids - have)
            self.assertEqual(lacking, [],
                             f"{cid} 这些知识点没有任何种子资料：{lacking}")
            for a in atoms:
                self.assertIn(a.get("knowledge_id"), local_ids,
                              f"{cid}:{a.get('id')} 指向了本课之外的知识点")
                self.assertTrue(len(a.get("text") or "") >= 20,
                                f"{cid}:{a.get('id')} 的资料太短")

    def test_requires_have_real_reasons(self):
        # 只禁真正的套话。「指令顺序」这种是技术术语，误伤它会逼出更差的内容——
        # 第一版就是因为裸禁「顺序」而误报了一条讲自回归采样顺序的正当理由。
        banned = ("因为顺序如此", "按顺序来", "按部就班", "自然就会", "前面学过所以")
        for cid, b in self.bridges.items():
            for k in b["knowledge"]:
                for r in k.get("requires") or []:
                    why = r.get("why") or ""
                    self.assertTrue(why, f"{cid}:{k['local']} 的 requires 缺 why")
                    self.assertTrue(len(why) >= 10,
                                    f"{cid}:{k['local']} 的 why 太敷衍：{why}")
                    for w in banned:
                        self.assertNotIn(w, why,
                                         f"{cid}:{k['local']} 的 why 是套话：{why}")

    def test_material_ids_are_unique_and_theory_refs_resolve(self):
        """资料 id 必须唯一，且 theory 引用的 atom_id 必须真的存在。

        子代理和我都往 bridge 里追加过资料，id 一开始是 TMP* 占位；
        只给占位续号（而不是整体重排）才不会让 theory 的引用错链到另一条资料。
        """
        for cid, b in self.bridges.items():
            atoms = (b.get("materials") or {}).get("atoms") or []
            ids = [a.get("id") for a in atoms]
            self.assertEqual(len(ids), len(set(ids)), f"{cid} 资料 id 有重复：{ids}")
            for a in atoms:
                self.assertNotIn("TMP", str(a.get("id")),
                                 f"{cid} 还有占位 id 没续号：{a.get('id')}")
            for t in b.get("theory") or []:
                self.assertIn(t.get("atom_id"), ids,
                              f"{cid} theory 引用了不存在的资料 {t.get('atom_id')}")


class TestKeywordSanity(unittest.TestCase):
    """keywords 是确定性覆盖判定的唯一依据，写坏了不会报错只会算错。"""

    @classmethod
    def setUpClass(cls):
        cls.system = load_json(SYSTEM_PATH)
        cls.kp_index = {k["id"]: k for k in cls.system["knowledge"]}
        cls.bridges = load_bridges()

    def declares_of(self, cid):
        """把 bridge 的知识点拼成 check_coverage 要的 declares（与生成器同规则）。"""
        out = []
        for k in self.bridges[cid]["knowledge"]:
            if k.get("from"):
                src = self.kp_index[k["from"]]
                out.append({"id": k["local"], "name": src["name"],
                            "level": src.get("level", "must"),
                            "keywords": [list(g) for g in src["keywords"]]})
            else:
                out.append({"id": k["local"], "name": k["name"],
                            "level": k["level"],
                            "keywords": [list(g) for g in k["keywords"]]})
        return {"knowledge": out}

    def test_generic_note_covers_nothing(self):
        """泛泛而谈的笔记不该命中任何必会知识点——命中说明 keyword 组太宽。"""
        for cid in self.bridges:
            cov = check_coverage(self.declares_of(cid), GENERIC_NOTE)
            self.assertEqual(cov["covered"], [],
                             f"{cid} 的 keyword 太宽：泛泛笔记覆盖了 {cov['covered']}")

    def test_keyword_groups_are_not_trivially_satisfied(self):
        """单个组内不许出现『Python』『代码』这类几乎任何笔记都有的词。"""
        too_common = {"python", "代码", "笔记", "学习", "程序", "内容", "知识",
                      "函数", "文件", "数据", "模型", "the", "a"}
        for cid, b in self.bridges.items():
            for k in b["knowledge"]:
                groups = ([list(g) for g in self.kp_index[k["from"]]["keywords"]]
                          if k.get("from") else [list(g) for g in k["keywords"]])
                for g in groups:
                    slim = [w for w in g if w.strip().lower() not in too_common]
                    self.assertTrue(
                        slim,
                        f"{cid}:{k['local']} 有一个组全是常见词，等于白送分：{g}")

    def test_every_group_has_a_short_landing_word(self):
        """反过来防『太严』：每个 keyword 组都要有一个短到能落在正常句子里的词。

        子代理实测过这个坑：08 的 K2 第 3 组原本只有「终止条件」，而学生笔记里
        写的是「什么时候停」——用书面术语当唯一入口，会导致怎么学都判未覆盖。
        「至少 2 个同义变体」这条只对**自撰**条目要求：继承来的 keywords 属于西二
        官方定义，改了它就破坏了「原样复用、不自撰」这条规矩。
        """
        for cid, b in self.bridges.items():
            for k in b["knowledge"]:
                inherited = bool(k.get("from"))
                groups = ([list(g) for g in self.kp_index[k["from"]]["keywords"]]
                          if inherited else [list(g) for g in k["keywords"]])
                for g in groups:
                    self.assertLessEqual(
                        min(len(w) for w in g), 12,
                        f"{cid}:{k['local']} 有个组全是长短语，"
                        f"学生正常写句子匹配不上：{g}")
                    if not inherited:
                        self.assertGreaterEqual(
                            len(g), 2,
                            f"{cid}:{k['local']} 有个自撰组只有 1 个词，"
                            f"没有同义落点：{g}")

    def test_student_facing_text_touches_its_points(self):
        """正向信号：西二课程自己的**任务与自检题**文本应当能命中它的必会点。

        为什么不用「学习内容」当语料：西二 f3 的 `学习内容` 原文是
        「你什么都学不到，或者说你想学的话，你能学到很多。」——一句玩笑话，
        不是内容描述，拿它测覆盖率是无效命题（实测 0/5）。
        改用 tasks[].brief 与 self_check[] 的问题/采分点：那是学生真的要读要答的文本，
        学生读完之后写出的笔记理应落在同一批词上。

        阈值只要求至少命中 1 个：这是**连通性**的冒烟检查（keywords 与课程实际
        讲的东西是不是同一批词），不是覆盖率指标——覆盖率由 check_coverage 在
        真实笔记上算。要求更高的阈值会把「按官方定义原样复用 keywords」这条规矩
        变成必须自撰，得不偿失。
        """
        for cid, b in self.bridges.items():
            if cid in APPEND_COURSES:
                continue
            src_courses = [c for c in b.get("sources") or [] if c != "self"]
            if not src_courses:
                continue
            text = ""
            for sid in src_courses:
                course = next((c for c in self.system["courses"]
                               if c["course_id"] == sid), None)
                if not course:
                    continue
                for t in course.get("tasks") or []:
                    text += (t.get("title") or "") + (t.get("brief") or "") \
                        + (t.get("deliverable") or "")
                for q in course.get("self_check") or []:
                    text += (q.get("question") or "") + "".join(q.get("points") or [])
            if len(text.strip()) < 50:
                continue
            declares = self.declares_of(cid)
            must = [kp for kp in declares["knowledge"] if kp["level"] == "must"]
            hits = [kp["id"] for kp in must
                    if check_coverage({"knowledge": [kp]}, text)["covered"]]
            self.assertGreaterEqual(
                len(hits), 1,
                f"{cid} 的必会点一个都没被课程的任务/自检题命中，"
                f"keywords 与实际讲授内容脱节：{[kp['keywords'] for kp in must]}")


class TestMergedCurricula(unittest.TestCase):
    """校验**生成出来的**九门课，而不是 bridge 输入。

    这一层是必要的：bridge 全对、生成结果仍然可能违反课程标准。
    实例——给老 3 追加 K7 时顺手加了一道自检题，于是第 3 课从 3 道变 4 道，
    而演示答卷只有 3 道答案，quiz 维度被拉低，本该通过的提交卡在 0.8318 < 0.85。

    当时想用「新增题与旧题的文字相似度」来防它，实测相似度只有 0.058——
    两个问题措辞完全不同、语义完全相同，文本相似度抓不住。
    真正抓得住的是这条**数量不变量**：自检题恰好 3 道（本来就是质量标准）。
    """

    @classmethod
    def setUpClass(cls):
        cls.curricula = {}
        for name in os.listdir(CURRICULUM_DIR):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(CURRICULUM_DIR, name), encoding="utf-8") as f:
                cur = json.load(f)
            cls.curricula[cur["course_id"]] = cur

    def test_all_nine_courses_generated(self):
        with open(ROUTE_PATH, encoding="utf-8") as f:
            route = json.load(f)
        want = sorted(c["course_id"] for c in route["courses"])
        self.assertEqual(len(want), 9, "路线图里不是 9 门课")
        self.assertEqual(sorted(self.curricula), want, "九门课没有全部生成")

    def test_self_check_count_is_reasonable_in_every_course(self):
        """自检题 3–5 道，每题恰好 3 个采分点。

        为什么是区间而不是「恰好 3」：给老课追加知识点后，新内容需要自己的自检题，
        硬卡 3 道会逼出「把两道题缝在一起」这种更差的结果。
        但也不能无限加——超过 5 道学生不会认真答，quiz 维度就失去意义了。

        数量本身还是个**信号**：第 3 课曾经变成 4 道，因为追加 K7 时加的一道题
        与原有 Q1（怎么判断静态/动态）语义重复。当时想用「文字相似度」来防，
        实测两道题相似度只有 0.058（措辞完全不同、语义完全相同），文本相似度抓不住。
        真正抓住它的是下游：演示答卷只有 3 道答案，quiz 被拉低，本该通过的提交卡在
        0.8318 < 0.85。所以这条测试只能挡住"数量失控"，语义重复要靠人工审——
        追加知识点前先问一句：这件事现有自检题是不是已经问过了？
        """
        for cid, cur in self.curricula.items():
            qs = cur.get("self_check") or []
            self.assertTrue(3 <= len(qs) <= 5,
                            f"{cid} 自检题 {len(qs)} 道，应在 3–5 道之间")
            for q in qs:
                self.assertEqual(len(q.get("points") or []), 3,
                                 f"{cid}:{q.get('id')} 采分点数不是 3")

    def test_every_knowledge_point_is_assessable(self):
        """每个知识点都要有 keywords（否则永远判不了覆盖）和至少一条种子资料。"""
        for cid, cur in self.curricula.items():
            kps = cur["declares"]["knowledge"]
            self.assertTrue(kps, f"{cid} 没有知识点")
            ids = [k["id"] for k in kps]
            self.assertEqual(len(ids), len(set(ids)), f"{cid} 知识点 id 有重复")
            for k in kps:
                self.assertTrue(k.get("keywords"),
                                f"{cid}:{k['id']} 没有 keywords，永远判不了覆盖")
            atoms = (cur.get("materials") or {}).get("atoms") or []
            have = {a.get("knowledge_id") for a in atoms}
            lacking = [k["id"] for k in kps if k["id"] not in have]
            self.assertEqual(lacking, [],
                             f"{cid} 这些知识点没有种子资料：{lacking}")

    def test_tasks_are_verifiable(self):
        """任务 3–6 个（追加知识点后会长），每个都要可验收。

        上限放宽的理由与自检题相同：给老课追加的知识点必须有自己的任务，
        否则「必须完全掌握」无从验证。但每个任务都必须有产出物与验收标准——
        数量可以长，门槛不能松。
        """
        for cid, cur in self.curricula.items():
            tasks = cur.get("tasks") or []
            self.assertTrue(3 <= len(tasks) <= 6,
                            f"{cid} 任务数 {len(tasks)} 不在 3–6")
            for t in tasks:
                self.assertTrue(t.get("brief"), f"{cid}:{t.get('task_id')} 缺 brief")
                self.assertTrue(t.get("deliverable"),
                                f"{cid}:{t.get('task_id')} 缺 deliverable")
                self.assertTrue(t.get("acceptance"),
                                f"{cid}:{t.get('task_id')} 缺可验收标准")

    def test_new_knowledge_keeps_old_ids_and_appends(self):
        """老 1/3 的老知识点必须原样在前，新增的接在后面。"""
        expected_head = {"py-agent-01": ["K1", "K2", "K3", "K4", "K5"],
                         "py-agent-03": ["K1", "K2", "K3", "K4", "K5", "K6"]}
        for cid, head in expected_head.items():
            ids = [k["id"] for k in self.curricula[cid]["declares"]["knowledge"]]
            self.assertEqual(ids[:len(head)], head,
                             f"{cid} 老知识点的顺序被改了：{ids}")
            self.assertGreater(len(ids), len(head), f"{cid} 没有追加任何知识点")

    def test_every_must_point_belongs_to_some_task(self):
        """必会知识点必须在某个任务里被覆盖到，否则"必须掌握"无从验证。"""
        for cid, cur in self.curricula.items():
            must = {k["id"] for k in cur["declares"]["knowledge"]
                    if k.get("level") == "must"}
            covered = set()
            for t in cur.get("tasks") or []:
                covered |= set(t.get("atoms") or [])
            missing = sorted(must - covered)
            self.assertEqual(missing, [],
                             f"{cid} 这些必会知识点不在任何任务里，无法验收：{missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
