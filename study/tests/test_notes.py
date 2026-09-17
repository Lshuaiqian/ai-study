"""花笺连接器的单测（纯逻辑 + 临时目录，不碰真实数据、不联网）。

运行：python -m unittest discover -s study/tests
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notes import (build_file_name, discover, infer_title, load_metadata,  # noqa: E402
                   make_entry, note_path, parse_id, read_note, reconcile,
                   safe_file_stem, scan, upsert_metadata, write_note)

UUID = "30d7efc2-513f-488d-af2c-e45cc45b60a5"


class TestParse(unittest.TestCase):

    def test_uuid_with_title(self):
        self.assertEqual(parse_id(f"{UUID}_functioncalling.md"), UUID)

    def test_uuid_only(self):
        self.assertEqual(parse_id(f"{UUID}.md"), UUID)

    def test_non_huajian(self):
        self.assertIsNone(parse_id("普通笔记.md"))
        self.assertIsNone(parse_id("notes.txt"))

    def test_infer_title_from_file_name(self):
        self.assertEqual(infer_title(f"{UUID}_functioncalling.md"), "functioncalling")

    def test_infer_title_falls_back_to_heading(self):
        self.assertEqual(infer_title(f"{UUID}.md", "# 我的标题\n正文"), "我的标题")

    def test_infer_title_empty(self):
        self.assertEqual(infer_title(f"{UUID}.md", "没有标题的正文"), "")


class TestSafeName(unittest.TestCase):

    def test_strips_illegal(self):
        self.assertEqual(safe_file_stem('a/b:c*d?e"f<g>h|i'), "abcdefghi")

    def test_strips_dots_and_space(self):
        self.assertEqual(safe_file_stem("  ..name..  "), "name")

    def test_length_capped(self):
        self.assertEqual(len(safe_file_stem("x" * 200)), 80)

    def test_build_file_name_with_and_without_title(self):
        self.assertEqual(build_file_name("id1", "标题"), "id1_标题.md")
        self.assertEqual(build_file_name("id1", "   "), "id1.md")
        self.assertEqual(build_file_name("id1", "a/b"), "id1_ab.md")


class TestNotePath(unittest.TestCase):

    def test_root(self):
        self.assertTrue(note_path("N", "a.md").endswith(os.path.join("N", "a.md")))

    def test_single_category(self):
        self.assertTrue(note_path("N", "a.md", "工作")
                        .endswith(os.path.join("N", "工作", "a.md")))

    def test_multi_level_category(self):
        """花笺当前只写一层，但路径逻辑按多层实现，将来无需再改。"""
        self.assertTrue(note_path("N", "a.md", "工作/2026/Q3")
                        .endswith(os.path.join("N", "工作", "2026", "Q3", "a.md")))

    def test_rejects_parent_escape(self):
        with self.assertRaises(ValueError):
            note_path("N", "a.md", "../外面")


class TestScan(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="huajian_")
        os.makedirs(os.path.join(self.root, "工作", "2026"), exist_ok=True)
        self._w(f"{UUID}_根.md", "# 根笔记")
        self._w(os.path.join("工作", f"{UUID}_一层.md"), "# 一层")
        self._w(os.path.join("工作", "2026", f"{UUID}_两层.md"), "# 两层")
        self._w("非花笺.md", "随便写的")
        self._w("忽略.txt", "不是 md")

    def _w(self, rel, text):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def test_recursive_scan(self):
        notes = scan(self.root)
        names = {n["file_name"] for n in notes}
        self.assertIn(f"{UUID}_根.md", names)
        self.assertIn(f"{UUID}_一层.md", names)
        self.assertIn(f"{UUID}_两层.md", names)     # 递归能进到第二层
        self.assertNotIn("忽略.txt", names)

    def test_category_is_relative_path(self):
        cats = {n["title"]: n["category"] for n in scan(self.root)}
        self.assertEqual(cats["根"], "")
        self.assertEqual(cats["一层"], "工作")
        self.assertEqual(cats["两层"], "工作/2026")

    def test_non_huajian_has_no_id(self):
        rec = next(n for n in scan(self.root) if n["file_name"] == "非花笺.md")
        self.assertIsNone(rec["id"])


class TestWriteAndMetadata(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="huajian_data_")
        self.notes = os.path.join(self.dir, "notes")
        os.makedirs(self.notes, exist_ok=True)

    def test_write_then_read_roundtrip(self):
        nid, path = write_note(self.notes, "第3课笔记", "# 爬虫\n内容", "学习")
        self.assertTrue(os.path.isfile(path))
        self.assertIn(os.path.join("学习"), path)
        self.assertEqual(read_note(path), "# 爬虫\n内容\n")
        self.assertEqual(parse_id(os.path.basename(path)), nid)

    def test_write_with_explicit_id(self):
        nid, path = write_note(self.notes, "T", "x", note_id="fixed-id")
        self.assertEqual(os.path.basename(path), "fixed-id_T.md")

    def test_metadata_created_and_updated(self):
        e = make_entry("id1", "标题", "id1_标题.md", "学习", "# 标题\n正文内容")
        upsert_metadata(self.dir, e)
        meta = load_metadata(self.dir)
        self.assertEqual(len(meta["notes"]), 1)
        self.assertEqual(meta["notes"][0]["title"], "标题")
        self.assertGreater(meta["notes"][0]["wordCount"], 0)

        upsert_metadata(self.dir, {**e, "title": "改过的标题"})
        meta = load_metadata(self.dir)
        self.assertEqual(len(meta["notes"]), 1)              # 不重复追加
        self.assertEqual(meta["notes"][0]["title"], "改过的标题")

    def test_metadata_backup_created(self):
        upsert_metadata(self.dir, make_entry("id1", "A", "id1_A.md", "", "x"))
        upsert_metadata(self.dir, make_entry("id2", "B", "id2_B.md", "", "y"))
        baks = [f for f in os.listdir(self.dir) if ".bak-" in f]
        self.assertEqual(len(baks), 1)

    def test_word_count_ignores_whitespace(self):
        e = make_entry("i", "t", "f", "", "a b\tc\nd")
        self.assertEqual(e["wordCount"], 4)


class TestReconcile(unittest.TestCase):

    def test_buckets(self):
        scanned = [
            {"id": "a", "file_name": "a_x.md"},
            {"id": None, "file_name": "散文件.md"},
            {"id": "b", "file_name": "b_y.md"},
        ]
        metadata = {"notes": [{"id": "a"}, {"id": "c"}]}
        r = reconcile(scanned, metadata)
        self.assertEqual(r["tracked"], ["a"])
        self.assertEqual(r["untracked_files"], ["b_y.md"])
        self.assertEqual(r["missing_files"], ["c"])
        self.assertEqual(r["non_huajian_md"], ["散文件.md"])


class TestDiscover(unittest.TestCase):

    def test_reads_notes_dir_from_config(self):
        d = tempfile.mkdtemp(prefix="huajian_cfg_")
        custom = os.path.join(d, "我的笔记")
        os.makedirs(custom)
        with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"locale": "zh-CN", "notesDir": custom}, f, ensure_ascii=False)
        got = discover(d)
        self.assertEqual(got["notes_dir"], custom)
        self.assertTrue(got["exists"])

    def test_falls_back_to_data_dir_notes(self):
        d = tempfile.mkdtemp(prefix="huajian_cfg2_")
        os.makedirs(os.path.join(d, "notes"))
        got = discover(d)
        self.assertEqual(got["notes_dir"], os.path.join(d, "notes"))

    def test_missing_config_is_tolerated(self):
        d = tempfile.mkdtemp(prefix="huajian_cfg3_")
        got = discover(d)
        self.assertFalse(got["exists"])
        self.assertEqual(got["config"], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
