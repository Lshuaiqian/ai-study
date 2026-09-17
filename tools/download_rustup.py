"""下载 rustup-init.exe（用 python urllib，PowerShell 的 TLS 在这台机器上不可靠）。

优先官方源，失败回退中科大 / 字节 rsproxy 镜像。
"""
import hashlib
import io
import os
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TARGET = r"E:\Docs\Code\Java\book\tools\rustup-init.exe"
URLS = [
    "https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe",
    "https://mirrors.ustc.edu.cn/rust-static/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe",
    "https://rsproxy.cn/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe",
]

os.makedirs(os.path.dirname(TARGET), exist_ok=True)

for url in URLS:
    print(f"尝试 {url}")
    try:
        t0 = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": "rustup-downloader"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        size_mb = len(data) / 1024 / 1024
        print(f"  ✅ {size_mb:.2f} MB，用时 {time.time()-t0:.1f}s")
        if len(data) < 3_000_000:
            print("  ⚠️ 体积异常偏小，可能不是完整文件，换下一个源")
            continue
        with open(TARGET, "wb") as f:
            f.write(data)
        print(f"  sha256 = {hashlib.sha256(data).hexdigest()}")
        print(f"  已保存 → {TARGET}")
        sys.exit(0)
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ {type(e).__name__}: {e}")

print("全部源失败")
sys.exit(1)
