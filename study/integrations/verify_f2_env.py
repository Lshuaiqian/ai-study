#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""F2 环境自检：把开始「网络爬虫与数据分析」需要的东西一次验完。

west2 Task 2 要求两条解析路线都会：BeautifulSoup（可安装增强）与标准库 html.parser。
这个脚本把两条都跑一遍，免得你在写作业时才发现环境缺东西。

用法：
    python study\\integrations\\verify_f2_env.py
"""
import io
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HTML = """
<ul>
  <li><article class="product_pod">
    <div class="image_container"><a href="covers/a.jpg"><img src="a.jpg"></a></div>
    <p class="star-rating Three"></p>
    <h3><a href="a/index.html" title="A Light in the Attic">A Light in the Attic</a></h3>
    <div class="product_price"><p class="price_color">&pound;51.77</p></div>
  </article></li>
  <li><article class="product_pod">
    <div class="image_container"><a href="covers/b.jpg"><img src="b.jpg"></a></div>
    <p class="star-rating One"></p>
    <h3><a href="b/index.html" title="Tipping the Velvet">Tipping the Velvet</a></h3>
    <div class="product_price"><p class="price_color">&pound;53.74</p></div>
  </article></li>
</ul>
"""

results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((True, name, detail))
    except Exception as e:  # noqa: BLE001
        results.append((False, name, f"{type(e).__name__}: {e}"))


# ---- 1. 依赖 ----
def dep():
    import importlib.util as u
    mods = ["requests", "bs4", "pandas", "matplotlib", "lxml"]
    return "、".join(f"{m}={'OK' if u.find_spec(m) else '缺失'}" for m in mods)


check("依赖清单", dep)


def bs4_ver():
    import bs4
    return f"beautifulsoup4 {bs4.__version__}"


check("bs4 可导入", bs4_ver)


# ---- 2. BeautifulSoup 路线 ----
def route_bs4():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(HTML, "html.parser")
    out = []
    for card in soup.select("article.product_pod"):
        out.append({
            "title": card.select_one("h3 > a")["title"],
            "price": card.select_one("p.price_color").get_text(strip=True),
            "rating": card.select_one("p.star-rating")["class"][1],
            "url": card.select_one("h3 > a")["href"],
        })
    assert len(out) == 2, out
    return out


# ---- 3. 标准库 html.parser 路线 ----
def route_stdlib():
    from html.parser import HTMLParser

    class BookParser(HTMLParser):
        """注意：pod 里第一个 <a> 是封面图链接（无文字），书名链接在 <h3> 里。"""

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.books, self._in_pod, self._in_h3, self._cur, self._grab = \
                [], 0, 0, None, None

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            cls = a.get("class", "") or ""
            if tag == "article" and "product_pod" in cls:
                self._in_pod += 1
                self._cur = {"title": "", "price": "", "rating": "", "url": ""}
                return
            if not self._in_pod or self._cur is None:
                return
            if tag == "h3":
                self._in_h3 += 1
            elif tag == "a" and self._in_h3:
                self._cur["url"] = a.get("href", "")
                self._cur["title"] = a.get("title", "")
            elif tag == "p" and "price_color" in cls:
                self._grab = "price"
            elif tag == "p" and "star-rating" in cls:
                for t in cls.split():
                    if t != "star-rating":
                        self._cur["rating"] = t

        def handle_data(self, data):
            if self._grab and self._cur is not None:
                self._cur[self._grab] += data.strip()

        def handle_endtag(self, tag):
            if tag == "h3":
                self._in_h3 = max(0, self._in_h3 - 1)
            elif tag == "p":
                self._grab = None
            elif tag == "article" and self._cur is not None:
                self._in_pod -= 1
                if self._cur["title"]:
                    self.books.append(self._cur)
                self._cur = None
                self._grab = None

    p = BookParser()
    p.feed(HTML)
    assert len(p.books) == 2, p.books
    return p.books


# ---- 4. 两路结果一致 ----
def routes_agree():
    a = route_bs4()
    b = route_stdlib()
    for x, y in zip(a, b):
        assert x["title"] == y["title"], (x, y)
        assert x["rating"] == y["rating"], (x, y)
    return f"两条路线抽出同样的 {len(a)} 条：{'、'.join(x['title'] for x in a)}"


check("BeautifulSoup 路线", route_bs4)
check("标准库 html.parser 路线", route_stdlib)
check("两路结果一致", routes_agree)


# ---- 5. 网络（可选，失败不算环境问题）----
def net():
    import requests
    r = requests.get("https://books.toscrape.com/catalogue/page-1.html",
                     headers={"User-Agent": "west2-learn-bot/0.1"}, timeout=15)
    assert r.status_code == 200
    return f"HTTP {r.status_code}，拿到 {len(r.text)} 字符"


try:
    check("网络可达（练习站）", net)
except Exception:  # noqa: BLE001
    pass


print("F2 环境自检")
print("=" * 60)
ok_all = True
for ok, name, detail in results:
    print(f"  {'✅' if ok else '❌'} {name}")
    print(f"      {detail}")
    ok_all = ok_all and ok
print("=" * 60)
print(f"结论：{'PASS —— 可以开始 F2' if ok_all else 'CHECK —— 上面有失败项'}")

if shutil.which("pip"):
    print("\n提示：pandas / matplotlib 在「数据分析」那三个作业才用到，到那步再装即可：")
    print("  pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pandas matplotlib")
sys.exit(0 if ok_all else 1)
