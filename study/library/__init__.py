"""library 包：学习库（知识原子）。

注意：`near_dup`（近似重复检测）与 `extractor.dedupe`（按 atom_id 精确去重）
是两回事，刻意分开放，避免同名混淆。
"""
from .extractor import (EXTRACT_SYSTEM, build_prompt, dedupe,  # noqa: F401
                        extract_candidates, to_atoms, verify_candidates)
from .near_dup import (DEFAULT_THRESHOLD, cluster_duplicates,  # noqa: F401
                       find_near_duplicates, render_duplicates, similarity)
from .store import (ATOM_TYPES, SOURCE_KINDS, STATUS_CONFIRMED,  # noqa: F401
                    STATUS_PENDING, STATUS_REJECTED, append_atoms,
                    confirmed, load_atoms, make_atom_id, set_status,
                    stats, update_atom, validate)
from .view import as_materials, course_view, global_stats, render_view  # noqa: F401
