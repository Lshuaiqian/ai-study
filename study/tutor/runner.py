"""tutor · 练习代码的安全执行器。

安全边界（沿用 tutor.py / mentor.py 的既有约束，此处显式化）：
  - 只允许运行【白名单目录】内的 .py 文件（路径先 realpath 再比对前缀）
  - 只允许调用当前解释器，不经过 shell，不接受任意命令
  - 超时强杀；stdout/stderr 截断
  - 这是"运行你自己的代码"，**不是沙箱**。服务化/多人使用前必须换成容器隔离。
"""
import ast
import importlib.util
import os
import subprocess
import sys
import tempfile

OUTPUT_LIMIT = 8000
DEFAULT_TIMEOUT = 25


class UnsafePathError(ValueError):
    pass


def resolve_inside(path, allowed_dirs):
    """把 path 解析为绝对路径并确认它位于 allowed_dirs 之内。"""
    target = os.path.abspath(path)
    for d in allowed_dirs:
        root = os.path.abspath(d)
        if target == root or target.startswith(root + os.sep):
            return target
    raise UnsafePathError(f"路径不在允许目录内: {path}")


def _truncate(text, limit=OUTPUT_LIMIT):
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[已截断，共 {len(text)} 字符]"


def check_syntax(path, allowed_dirs):
    """语法检查（不执行，可离线）。返回 {ok, error}。"""
    target = resolve_inside(path, allowed_dirs)
    if not target.endswith(".py"):
        return {"ok": False, "error": "仅支持 .py 文件"}
    fd, cfile = tempfile.mkstemp(suffix=".pyc")
    os.close(fd)
    try:
        import py_compile
        py_compile.compile(target, cfile=cfile, doraise=True)
        return {"ok": True, "error": ""}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        if os.path.exists(cfile):
            os.unlink(cfile)


def check_imports(path, allowed_dirs):
    """静态解析 import，检查第三方依赖是否真的装在这个环境里。

    为什么要这个：课程把 BeautifulSoup 标为"可安装增强"。如果学生的代码 import bs4
    而环境里没有，代码当然跑不通——但**这不是学生的错**。Tutor 必须先能区分
    「环境缺依赖」与「学生写错了」，否则会给出错误的点评，把环境问题算到人头上。
    """
    target = resolve_inside(path, allowed_dirs)
    try:
        with open(target, "r", encoding="utf-8") as f:
            src = f.read()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "missing": [], "modules": [], "error": f"{type(e).__name__}: {e}"}

    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return {"ok": False, "missing": [], "modules": [],
                "error": f"SyntaxError: line {e.lineno}: {e.msg}"}

    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])

    missing = []
    for name in sorted(modules):
        if name in sys.builtin_module_names:
            continue
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError, ModuleNotFoundError):
            missing.append(name)

    return {"ok": not missing, "missing": missing,
            "modules": sorted(modules), "error": ""}


def run_file(path, allowed_dirs, timeout=DEFAULT_TIMEOUT, cwd=None):
    """运行练习文件。返回 {ran, exit_code, stdout, stderr, timeout}。

    失败（含语法错误、超时、异常退出）不抛异常，而是如实记录，
    交由 Tutor 判断是否影响验收。
    """
    target = resolve_inside(path, allowed_dirs)
    if not target.endswith(".py"):
        return {"ran": False, "exit_code": None,
                "stdout": "", "stderr": "仅支持 .py 文件", "timeout": False}

    workdir = cwd or os.path.dirname(target)
    try:
        proc = subprocess.run(
            [sys.executable, target],
            cwd=workdir,
            capture_output=True,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        return {"ran": True, "exit_code": None, "timeout": True,
                "stdout": _truncate(e.stdout or ""),
                "stderr": _truncate(e.stderr or "") + f"\n[超时 {timeout}s，进程已终止]"}
    except Exception as e:  # noqa: BLE001
        return {"ran": False, "exit_code": None, "timeout": False,
                "stdout": "", "stderr": f"{type(e).__name__}: {e}"}

    return {
        "ran": True,
        "exit_code": proc.returncode,
        "timeout": False,
        "stdout": _truncate(proc.stdout),
        "stderr": _truncate(proc.stderr),
    }
