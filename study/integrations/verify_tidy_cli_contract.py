# -*- coding: utf-8 -*-
"""真实 CLI 冒烟：把笔记改名（模拟花笺改标题）后，--path 仍能定位课程并输出 JSONL。

不 patch 任何东西，直接跑 study/tools/tidy.py 子进程（用 --soft 免模型调用）。
"""
import json
import os
import subprocess
import sys
import tempfile
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

WS = r"E:\Docs\Code\Java\book"
PY = r"E:\Develop\python\python.exe"
NOTE = """<!-- study: course=west2-f0 stage=F0 -->
# F0 · 环境搭建

## 📋 考核要求

### 作业清单

- [ ] `t0-1` 装好 Python 与 venv

---

## ✍️ 我的笔记

HTTP 是无状态协议；状态码 200 成功、403 拒绝、429 要退避。
装好了 Python 3.11 与 venv，PATH 也配了。
"""


def main():
    tmp = tempfile.mkdtemp(prefix="smoke-")
    data = os.path.join(tmp, "huajian")
    notes = os.path.join(data, "notes", "西二AI-2026")
    os.makedirs(notes, exist_ok=True)
    with open(os.path.join(data, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"notes": []}, f)

    # 故意把文件名从 "F0-环境搭建" 改成 "环境搭建"：模拟用户在花笺里改标题
    path = os.path.join(notes, f"{uuid.uuid4()}_环境搭建.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(NOTE)
    print(f"临时花笺：{data}")
    print(f"笔记文件：{os.path.basename(path)}  ← 标题里没有 F0 前缀了")

    def run(argv):
        r = subprocess.run([PY, os.path.join(WS, "study", "tools", "tidy.py")] + argv,
                           capture_output=True, text=True, encoding="utf-8",
                           cwd=WS)
        return r.returncode, r.stdout, r.stderr

    print("\n=== ① 改名后 --path + --soft + --json ===")
    rc, out, err = run(["--west2", "--data-dir", data, "--path", path,
                        "--soft", "--json"])
    print(f"exit={rc}")
    for line in out.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)          # 解析失败会抛异常 = 契约破了
        t = obj.get("type")
        if t == "report":
            print(f"  report.payload = {json.dumps(obj['payload'], ensure_ascii=False)}")
        elif t == "done":
            print(f"  done.applied={obj['applied']} ai_zone={obj['changed']['ai_zone']} "
                  f"note_id={obj['note_id'][:8]}…")
        else:
            print(f"  {t}: {obj.get('name', '')} {obj.get('code', '')} "
                  f"{obj.get('msg', '')}")
    assert rc == 0, f"应成功，实际 {rc}\n{err}"
    kinds = [json.loads(x)["type"] for x in out.splitlines() if x.strip()]
    assert "stage" in kinds and "report" in kinds and "done" in kinds, kinds
    print("  ✅ 全部行可 JSON 解析，stage/report/done 齐全")

    print("\n=== ② 换成非课程笔记 → 退出码 3 ===")
    plain = os.path.join(notes, f"{uuid.uuid4()}_随手记.md")
    with open(plain, "w", encoding="utf-8", newline="\n") as f:
        f.write("# 随手记\n\n今天天气不错。\n")
    rc, out, _ = run(["--west2", "--data-dir", data, "--path", plain, "--soft", "--json"])
    ev = [json.loads(x) for x in out.splitlines() if x.strip()]
    print(f"exit={rc}  error={ev[-1].get('code')}")
    assert rc == 3, rc

    print("\n=== ③ --course 路径未回归（老用法照旧） ===")
    rc, out, _ = run(["--west2", "--data-dir", data, "--course", "west2-f0", "--soft"])
    print(f"exit={rc}  {'（找不到笔记，因为文件名已不含 F0 前缀 —— 这正是要引入标记的原因）' if rc == 3 else ''}")
    print("\n✅ 冒烟通过")


if __name__ == "__main__":
    sys.exit(main())
