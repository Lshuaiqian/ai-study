//! 把「花笺单层分类 → 多层文件夹」补丁里的**算法部分**抽出来，脱离 Tauri 单独编译验证。
//!
//! 为什么要有这个 crate：这台机器上 Windows 智能应用控制（SAC，强制模式）会拦截
//! `vswhom-sys` 的构建脚本（`os error 4551`），导致整个花笺后端编不了。
//! 但补丁里真正需要验证的是**扫描递归**与**分类路径归一化**这两段纯逻辑，
//! 它们只依赖 std。所以这里零依赖复刻一遍，用真实测试把它钉死。
//!
//! 对应源码：`src-tauri/src/services/notes.rs` 的
//! `rebuild_metadata` / `scan_dir_for_notes` / `note_path_in_category` / 分类名校验。

use std::fs;
use std::path::{Path, PathBuf};

// ---------------------------------------------------------------- 数据模型

#[derive(Debug, Clone, PartialEq)]
pub struct NoteMetadata {
    pub id: String,
    pub title: String,
    pub file_name: String,
    pub category: String,
    pub word_count: usize,
    pub preview: String,
}

// ---------------------------------------------------------------- 补丁：分类归一化

/// 归一化分类路径：允许 `工作/2026` 这种多层写法，
/// 但拒绝空段、`.`、`..` 以及 Windows 非法字符，防止写出 notes_dir 之外。
///
/// 这是补丁新增的函数，取代原来「一律拒绝 `/`」的校验。
pub fn normalize_category(name: &str) -> Result<String, &'static str> {
    let name = name.trim().replace('\\', "/");
    let name = name.trim_matches('/');
    if name.is_empty() {
        return Err("categoryNameEmpty");
    }
    let mut parts: Vec<&str> = Vec::new();
    for part in name.split('/') {
        let part = part.trim();
        if part.is_empty() || part == "." || part == ".." {
            return Err("categoryNameInvalidChars");
        }
        if part.contains([':', '*', '?', '"', '<', '>', '|']) {
            return Err("categoryNameInvalidChars");
        }
        parts.push(part);
    }
    Ok(parts.join("/"))
}

// ---------------------------------------------------------------- 补丁：路径拼接

/// 未改动，但一并复刻以便测试：`PathBuf::join` 在 Windows 上同样把 `/` 当分隔符，
/// 所以 `category = "工作/2026"` 天然就能落到 `notes/工作/2026/`。
pub fn note_path_in_category(notes_dir: &Path, file_name: &str, category: &str) -> PathBuf {
    if category.is_empty() {
        notes_dir.join(file_name)
    } else {
        notes_dir.join(category).join(file_name)
    }
}

// ---------------------------------------------------------------- 补丁：递归扫描

/// 从 `<id>_<标题>.md` 或 `<id>.md` 里取 id。
fn id_from_file_name(file_name: &str) -> Option<String> {
    let stem = file_name.strip_suffix(".md")?;
    let bytes = stem.as_bytes();
    // UUID: 8-4-4-4-12，用 '-' 分段、总长 36
    if stem.len() >= 36
        && bytes[8] == b'-'
        && bytes[13] == b'-'
        && bytes[18] == b'-'
        && bytes[23] == b'-'
    {
        return Some(stem[..36].to_string());
    }
    None
}

fn infer_title(file_name: &str, content: &str) -> String {
    let stem = file_name.strip_suffix(".md").unwrap_or(file_name);
    if let Some(id) = id_from_file_name(file_name) {
        let rest = stem[id.len()..].trim_start_matches('_').trim();
        if !rest.is_empty() {
            return rest.to_string();
        }
    }
    for line in content.lines() {
        let line = line.trim();
        if let Some(h) = line.strip_prefix('#') {
            let t = h.trim_start_matches('#').trim();
            if !t.is_empty() {
                return t.to_string();
            }
        }
    }
    String::new()
}

fn preview(content: &str) -> String {
    for line in content.lines() {
        let t = line.trim().trim_start_matches('#').trim();
        if !t.is_empty() {
            return t.chars().take(80).collect();
        }
    }
    String::new()
}

fn count_words(content: &str) -> usize {
    content.chars().filter(|c| !c.is_whitespace()).count()
}

/// **补丁核心**：递归扫描，`category` 用相对路径（`"工作/2026"`）拼接。
///
/// 改前：只在 `rebuild_metadata` 里遍历一层子目录，且 `scan_dir_for_notes`
/// 遇到子目录直接跳过（因为它只处理 `.md`）。
/// 改后：子目录继续递归，层级由当前 `category` + 子目录名拼出。
pub fn scan_dir_for_notes(
    dir: &Path,
    category: &str,
    out: &mut Vec<NoteMetadata>,
) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();

        if path.is_dir() {
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with('.') {
                continue; // 跳过隐藏目录
            }
            let child = if category.is_empty() {
                name
            } else {
                format!("{category}/{name}")
            };
            scan_dir_for_notes(&path, &child, out)?;
            continue;
        }

        if path.extension().and_then(|e| e.to_str()) != Some("md") {
            continue;
        }
        let file_name = entry.file_name().to_string_lossy().to_string();
        let Some(id) = id_from_file_name(&file_name) else {
            continue; // 不符合花笺命名规范的，不收
        };
        let content = fs::read_to_string(&path).unwrap_or_default();
        out.push(NoteMetadata {
            id,
            title: infer_title(&file_name, &content),
            file_name,
            category: category.to_string(),
            word_count: count_words(&content),
            preview: preview(&content),
        });
    }
    Ok(())
}

/// **补丁核心**：一次递归搞定，不再假设只有一层。
pub fn rebuild_metadata(notes_dir: &Path) -> std::io::Result<Vec<NoteMetadata>> {
    fs::create_dir_all(notes_dir)?;
    let mut notes = Vec::new();
    scan_dir_for_notes(notes_dir, "", &mut notes)?;
    notes.sort_by(|a, b| (a.category.clone(), a.file_name.clone())
        .cmp(&(b.category.clone(), b.file_name.clone())));
    Ok(notes)
}

/// 是否已有 `.md`（对应 `notes_dir_has_md_files`，本来就是递归的）。
pub fn notes_dir_has_md_files(notes_dir: &Path) -> bool {
    fn walk(dir: &Path) -> bool {
        let Ok(entries) = fs::read_dir(dir) else { return false };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                if walk(&path) {
                    return true;
                }
            } else if path.extension().and_then(|e| e.to_str()) == Some("md") {
                return true;
            }
        }
        false
    }
    walk(notes_dir)
}

// ================================================================ 测试

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    const UUID_A: &str = "11111111-1111-1111-1111-111111111111";
    const UUID_B: &str = "22222222-2222-2222-2222-222222222222";
    const UUID_C: &str = "33333333-3333-3333-3333-333333333333";

    fn tmp(name: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!("huajian_probe_{name}"));
        let _ = fs::remove_dir_all(&p);
        fs::create_dir_all(&p).unwrap();
        p
    }

    fn write(root: &Path, rel: &str, text: &str) {
        let p = root.join(rel);
        if let Some(parent) = p.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(p, text).unwrap();
    }

    // ---------------- 分类归一化 ----------------

    #[test]
    fn category_allows_multilevel() {
        assert_eq!(normalize_category("工作/2026").unwrap(), "工作/2026");
        assert_eq!(normalize_category("  A / B  ").unwrap(), "A/B");
        assert_eq!(normalize_category("A\\B").unwrap(), "A/B"); // 反斜杠归一
        assert_eq!(normalize_category("/A/B/").unwrap(), "A/B"); // 去掉首尾斜杠
    }

    #[test]
    fn category_rejects_traversal_and_junk() {
        assert_eq!(normalize_category(""), Err("categoryNameEmpty"));
        assert_eq!(normalize_category("   "), Err("categoryNameEmpty"));
        assert_eq!(normalize_category(".."), Err("categoryNameInvalidChars"));
        assert_eq!(normalize_category("A/../B"), Err("categoryNameInvalidChars"));
        assert_eq!(normalize_category("A//B"), Err("categoryNameInvalidChars"));
        assert_eq!(normalize_category("A/./B"), Err("categoryNameInvalidChars"));
        assert_eq!(normalize_category("C:D"), Err("categoryNameInvalidChars"));
        assert_eq!(normalize_category("a*b"), Err("categoryNameInvalidChars"));
    }

    // ---------------- 路径拼接 ----------------

    #[test]
    fn path_supports_multilevel_category() {
        let base = PathBuf::from("N");
        assert!(note_path_in_category(&base, "x.md", "")
            .ends_with(Path::new("N").join("x.md")));
        assert!(note_path_in_category(&base, "x.md", "工作")
            .ends_with(Path::new("N").join("工作").join("x.md")));
        // 关键：含 / 的 category 直接生成多层路径，存储层无需改动
        assert!(note_path_in_category(&base, "x.md", "工作/2026")
            .ends_with(Path::new("N").join("工作").join("2026").join("x.md")));
    }

    // ---------------- 扫描：向后兼容 ----------------

    #[test]
    fn single_level_still_works() {
        let root = tmp("single");
        write(&root, &format!("{UUID_A}_根笔记.md"), "# 根");
        write(&root, &format!("工作/{UUID_B}_工作笔记.md"), "# 工作");
        let notes = rebuild_metadata(&root).unwrap();
        assert_eq!(notes.len(), 2);
        let cats: Vec<&str> = notes.iter().map(|n| n.category.as_str()).collect();
        assert!(cats.contains(&""));
        assert!(cats.contains(&"工作"));
    }

    // ---------------- 扫描：多层（补丁新增能力） ----------------

    #[test]
    fn multilevel_categories_are_discovered() {
        let root = tmp("multi");
        write(&root, &format!("{UUID_A}_根.md"), "# 根");
        write(&root, &format!("工作/{UUID_B}_一层.md"), "# 一层");
        write(&root, &format!("工作/2026/{UUID_C}_两层.md"), "# 两层");
        let notes = rebuild_metadata(&root).unwrap();
        assert_eq!(notes.len(), 3, "两层目录里的笔记必须被扫到");

        let by_title: Vec<(String, String)> = notes
            .iter()
            .map(|n| (n.title.clone(), n.category.clone()))
            .collect();
        assert!(by_title.contains(&("根".into(), "".into())));
        assert!(by_title.contains(&("一层".into(), "工作".into())));
        assert!(by_title.contains(&("两层".into(), "工作/2026".into())));
    }

    #[test]
    fn three_levels_deep() {
        let root = tmp("deep");
        write(&root, &format!("A/B/C/{UUID_A}_深.md"), "# 深");
        let notes = rebuild_metadata(&root).unwrap();
        assert_eq!(notes.len(), 1);
        assert_eq!(notes[0].category, "A/B/C");
    }

    // ---------------- 忽略与容错 ----------------

    #[test]
    fn ignores_non_md_and_non_uuid_and_hidden() {
        let root = tmp("ignore");
        write(&root, &format!("{UUID_A}_正常.md"), "# 正常");
        write(&root, "随便写的.md", "没有 UUID 前缀");
        write(&root, "notes.txt", "不是 md");
        write(&root, &format!(".hidden/{UUID_B}_隐藏.md"), "# 隐藏");
        let notes = rebuild_metadata(&root).unwrap();
        assert_eq!(notes.len(), 1);
        assert_eq!(notes[0].id, UUID_A);
    }

    #[test]
    fn id_and_title_parsing() {
        assert_eq!(id_from_file_name(&format!("{UUID_A}_标题.md")), Some(UUID_A.into()));
        assert_eq!(id_from_file_name(&format!("{UUID_A}.md")), Some(UUID_A.into()));
        assert_eq!(id_from_file_name("普通.md"), None);
        assert_eq!(infer_title(&format!("{UUID_A}_functioncalling.md"), ""), "functioncalling");
        assert_eq!(infer_title(&format!("{UUID_A}.md"), "# 我的标题\n正文"), "我的标题");
        assert_eq!(infer_title(&format!("{UUID_A}.md"), "没标题"), "");
    }

    // ---------------- 空目录 / 不存在 ----------------

    #[test]
    fn empty_and_missing_dirs_are_safe() {
        let root = tmp("empty");
        assert!(rebuild_metadata(&root).unwrap().is_empty());
        assert!(!notes_dir_has_md_files(&root));

        let missing = std::env::temp_dir().join("huajian_probe_missing_dir");
        let _ = fs::remove_dir_all(&missing);
        // 不存在的目录会被 create_dir_all 建出来，不应 panic
        assert!(rebuild_metadata(&missing).unwrap().is_empty());
        fs::remove_dir_all(&missing).unwrap();
    }

    #[test]
    fn has_md_files_is_recursive() {
        let root = tmp("hasmd");
        write(&root, &format!("A/B/{UUID_A}_深.md"), "# 深");
        assert!(notes_dir_has_md_files(&root), "只看根目录会漏掉多层分类下的笔记");
    }

    // ---------------- 端到端：写进去再扫出来 ----------------

    #[test]
    fn write_then_rescan_roundtrip() {
        let root = tmp("roundtrip");
        let cat = normalize_category("学习/Python").unwrap();
        let path = note_path_in_category(&root, &format!("{UUID_A}_第3课.md"), &cat);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, "# 第3课\n爬虫笔记").unwrap();

        let notes = rebuild_metadata(&root).unwrap();
        assert_eq!(notes.len(), 1);
        assert_eq!(notes[0].category, "学习/Python");
        assert_eq!(notes[0].title, "第3课");
        assert!(notes[0].word_count > 0);
        assert_eq!(notes[0].preview, "第3课");
    }
}
