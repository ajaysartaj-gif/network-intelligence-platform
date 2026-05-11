 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/scripts/check_source_integrity.py b/scripts/check_source_integrity.py
new file mode 100644
index 0000000000000000000000000000000000000000..27fa56916ecbaf25a0743492994c4e178db4a63b
--- /dev/null
+++ b/scripts/check_source_integrity.py
@@ -0,0 +1,69 @@
+"""Detect accidentally pasted shell/patch text in Python source files.
+
+This catches the common recovery case where a `git apply <<'EOF'` command was
+pasted into `app.py` or another Python module instead of being executed in a
+terminal.
+"""
+
+from __future__ import annotations
+
+import sys
+from pathlib import Path
+
+ROOT = Path(__file__).resolve().parents[1]
+SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
+BAD_MARKERS = (
+    'git apply --3way <<',
+    'git apply <<',
+    'git rev-parse --show-toplevel',
+    "cat > app.py <<'PY'",
+    '*** Begin Patch',
+    '*** End Patch',
+)
+
+
+def iter_python_files() -> list[Path]:
+    files: list[Path] = []
+    self_path = Path(__file__).resolve()
+    for path in ROOT.rglob("*.py"):
+        if path.resolve() == self_path:
+            continue
+        if any(part in SKIP_DIRS for part in path.parts):
+            continue
+        files.append(path)
+    return sorted(files)
+
+
+def main() -> int:
+    failures: list[str] = []
+    for path in iter_python_files():
+        try:
+            text = path.read_text(encoding="utf-8")
+        except UnicodeDecodeError as exc:
+            failures.append(f"{path.relative_to(ROOT)}: cannot decode UTF-8 ({exc})")
+            continue
+
+        for lineno, line in enumerate(text.splitlines(), start=1):
+            if any(marker in line for marker in BAD_MARKERS):
+                failures.append(
+                    f"{path.relative_to(ROOT)}:{lineno}: looks like pasted shell/patch text: "
+                    f"{line.strip()[:120]}"
+                )
+
+    if failures:
+        print("Source integrity check failed:", file=sys.stderr)
+        for failure in failures:
+            print(f"- {failure}", file=sys.stderr)
+        print(
+            "\nFix: restore the affected file from git or remove the pasted patch command. "
+            "Patch commands must be run in a terminal, not pasted into Python files.",
+            file=sys.stderr,
+        )
+        return 1
+
+    print(f"Source integrity check passed ({len(iter_python_files())} Python files scanned).")
+    return 0
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
 
EOF
)
