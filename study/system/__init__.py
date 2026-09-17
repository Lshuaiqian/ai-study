"""system 包：知识体系（自上而下流程的源头）。"""
from .active import active_paths, load_active              # noqa: F401
from .split import (CODE_LABEL, COUNTED_MET, DEFAULT_GATE,  # noqa: F401
                    STAGE_LABEL, STATUS_LABEL, apply_placement,
                    check_label_order, code_of, course_index,
                    derived_unlocks, dimension_index, find_course_cycles,
                    knowledge_index, load_placement, load_system,
                    placement_report, protected_ids, protection_map,
                    split_all, summary, to_curriculum, to_route,
                    topo_courses, validate_system, write_derived)