 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/docs/source_integrity_recovery.md b/docs/source_integrity_recovery.md
new file mode 100644
index 0000000000000000000000000000000000000000..098ea6fcba8b372d3d63e9a4585149e92f2c2efc
--- /dev/null
+++ b/docs/source_integrity_recovery.md
@@ -0,0 +1,43 @@
+# Source Integrity Recovery
+
+If Streamlit reports an error like this while opening the app:
+
+```text
+File "/mount/src/network-intelligence-platform/app.py", line 1
+(cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF'
+^
+IndentationError: unexpected indent
+```
+
+then a shell patch command was pasted into `app.py` instead of being executed in a terminal.
+
+## Fix
+
+1. Restore `app.py` from git:
+
+   ```bash
+   git checkout -- app.py
+   ```
+
+2. If other Python files were edited the same way, restore them too or run:
+
+   ```bash
+   git status --short
+   git checkout -- path/to/corrupted_file.py
+   ```
+
+3. Run the source integrity check:
+
+   ```bash
+   python scripts/check_source_integrity.py
+   ```
+
+4. Run the Python syntax check:
+
+   ```bash
+   python -m py_compile app.py
+   ```
+
+## Prevention
+
+Patch blocks that start with `git apply`, `cat > file`, or `*** Begin Patch` must be run in a terminal or applied by a development tool. They should never be pasted into `app.py` or any other Python source file.
 
EOF
)
