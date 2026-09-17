"""library · 近似重复检测（确定性，无网络依赖）。

为什么需要：实测发现抽取有两个相反的失败模式——
  - 抽太松：把"我这次改了三处""跑到第 2 页共 20 条"这类**过程性叙述**当知识（收紧提示词后已解决）
  - 抽太碎：同一个道理拆成 4 条近似句（"限速逻辑与站点无关""落盘方式与站点无关"…）

`atom_id` 用内容哈希只能挡**完全相同**的重复，挡不住语义近似。
这里用字符 n-gram 的 Jaccard 相似度做程序化提示——中文不需要分词，
交给人工在确认阶段决定合并还是都留。

刻意不做自动合并：合并会丢信息，而"是否同一个知识点"是人的判断。
"""
import re

DEFAULT_THRESHOLD = 0.55
NGRAM = 2


def _shingles(text, n=NGRAM):
    t = re.sub(r"\s+", "", text or "")
    if len(t) < n:
        return {t} if t else set()
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def similarity(a, b):
    """字符 2-gram Jaccard 相似度 ∈ [0,1]。"""
    A = _shingles(a)
    B = _shingles(b)
    if not A and not B:
        return 1.0
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def _text_of(atom):
    return f"{atom.get('title', '')}{atom.get('statement', '')}"


def find_near_duplicates(atoms, threshold=DEFAULT_THRESHOLD, course_id=None):
    """找出疑似重复的原子对。返回 [{a, b, score, titles}]，按相似度降序。

    atoms 可以是 {id: atom} 或 [atom, ...]。
    """
    pool = list(atoms.values()) if isinstance(atoms, dict) else list(atoms)
    if course_id:
        pool = [a for a in pool if a.get("course") == course_id]
    pool = sorted(pool, key=lambda a: a.get("atom_id", ""))

    pairs = []
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            a, b = pool[i], pool[j]
            score = similarity(_text_of(a), _text_of(b))
            if score >= threshold:
                pairs.append({
                    "a": a.get("atom_id"), "b": b.get("atom_id"),
                    "score": round(score, 4),
                    "a_title": a.get("title", ""), "b_title": b.get("title", ""),
                })
    return sorted(pairs, key=lambda p: -p["score"])


def cluster_duplicates(atoms, threshold=DEFAULT_THRESHOLD, course_id=None):
    """把疑似重复的原子聚成组（并查集），便于一次决定去留。"""
    pool = list(atoms.values()) if isinstance(atoms, dict) else list(atoms)
    if course_id:
        pool = [a for a in pool if a.get("course") == course_id]
    parent = {a["atom_id"]: a["atom_id"] for a in pool}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for p in find_near_duplicates(pool, threshold):
        union(p["a"], p["b"])

    groups = {}
    for a in pool:
        groups.setdefault(find(a["atom_id"]), []).append(a["atom_id"])
    return [sorted(v) for v in groups.values() if len(v) > 1]


def render_duplicates(pairs):
    if not pairs:
        return "近似重复：✅ 未发现"
    L = [f"近似重复：⚠️ 发现 {len(pairs)} 对（相似度 ≥ {DEFAULT_THRESHOLD}），建议人工合并或删除："]
    for p in pairs:
        L.append(f"  {p['score']:.2f}  {p['a']} {p['a_title'][:26]}")
        L.append(f"          {p['b']} {p['b_title'][:26]}")
    return "\n".join(L)
