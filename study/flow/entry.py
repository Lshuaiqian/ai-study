"""flow · 课程准入门禁。

补上一个真实的洞：`gate.evaluate()` 只做**课程内部**的判定，
它不知道这门课的前置课有没有过。第 4 轮体系图就抓到过
"第 3 课已通过但前置 L2 未通过"这种自相矛盾的状态——
说明单课闭环是可以被绕过的。

所以准入检查必须独立成一道关，在**开课之前**执行。
"""
from graph.builder import (AVAILABLE, IN_PROGRESS, PASSED, course_status,
                           knowledge_status, unlock_path)


def entry_check(graph, mastery_state, course_id):
    """判断某门课现在能不能开。

    返回 {allowed, status, missing_prerequisites, blocked_points, reason}
    """
    if course_id not in graph["nodes"]:
        return {"allowed": False, "status": "unknown_course",
                "missing_prerequisites": [], "blocked_points": [],
                "reason": f"课程不存在：{course_id}"}

    st = course_status(graph, mastery_state)
    info = st.get(course_id, {})
    status = info.get("status")
    missing = info.get("missing_prerequisites") or []

    # 知识点级：哪些点因为前置未通过而被挡住（供提示用，不单独否决）
    kst = knowledge_status(graph, mastery_state, course_id)
    blocked = [nid for nid, v in kst.items() if v["status"] == "blocked"]

    allowed = status in (AVAILABLE, IN_PROGRESS)
    if status == PASSED:
        reason = "本课已通过；如需重练请显式选择重修"
    elif allowed:
        reason = "前置已满足，可以开始"
    else:
        names = "、".join(f"{p}" for p in missing)
        reach = unlock_path(graph, course_id)
        reason = f"缺前置：{names}"
        if len(reach) > len(missing):
            reason += f"（连带未通过：{'、'.join(sorted(set(reach) - set(missing)))}）"

    return {
        "allowed": allowed,
        "status": status,
        "missing_prerequisites": missing,
        "blocked_points": sorted(blocked),
        "reason": reason,
    }


class EntryDenied(RuntimeError):
    """开课被门禁拦下。"""

    def __init__(self, course_id, check):
        super().__init__(f"无法开始 {course_id}：{check['reason']}")
        self.course_id = course_id
        self.check = check


def require_entry(graph, mastery_state, course_id):
    """通过返回 check 结果；不通过抛 EntryDenied（供流程层使用）。"""
    check = entry_check(graph, mastery_state, course_id)
    if not check["allowed"]:
        raise EntryDenied(course_id, check)
    return check
