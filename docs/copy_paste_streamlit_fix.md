 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/docs/copy_paste_streamlit_fix.md b/docs/copy_paste_streamlit_fix.md
new file mode 100644
index 0000000000000000000000000000000000000000..b699b0ecfc54ef9000f28f16e4ef4f0a2f0dbdc0
--- /dev/null
+++ b/docs/copy_paste_streamlit_fix.md
@@ -0,0 +1,136 @@
+# Copy/Paste Fix for the Streamlit `app.py` Line 1 Error
+
+This guide is for non-technical users.
+
+## The error
+
+If Streamlit shows this:
+
+```text
+File "/mount/src/network-intelligence-platform/app.py", line 1
+   (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF'
+  ^
+IndentationError: unexpected indent
+```
+
+then a command was pasted into the wrong place. That text must **not** be inside `app.py`.
+
+---
+
+## Option A — easiest fix in GitHub website
+
+### File name
+
+`app.py`
+
+### File location
+
+Repository root/top level:
+
+```text
+network-intelligence-platform/app.py
+```
+
+### What to check
+
+Open `app.py` in GitHub. The **first line must be exactly**:
+
+```python
+"""
+```
+
+The next lines should look like this:
+
+```python
+"""
+NetBrain AI — Autonomous Network Operating System
+app.py — Main entry point (Streamlit)
+```
+
+### What to delete
+
+If line 1 starts with this, delete it and any pasted patch text around it:
+
+```text
+(cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF'
+```
+
+After fixing, commit/save the file in GitHub, then reboot or redeploy the Streamlit app.
+
+---
+
+## Option B — copy/paste terminal repair script
+
+Paste the script below into a terminal opened at the repository root.
+
+> Important: paste this into a **terminal**, not into `app.py`.
+
+```bash
+cd "$(git rev-parse --show-toplevel)" || exit 1
+
+echo "Checking app.py..."
+python - <<'PY'
+from pathlib import Path
+import subprocess
+import sys
+import py_compile
+
+path = Path("app.py")
+text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
+first_25_lines = "\n".join(text.splitlines()[:25])
+markers = [
+    "git apply --3way <<",
+    "git apply <<",
+    "git rev-parse --show-toplevel",
+    "*** Begin Patch",
+    "*** End Patch",
+]
+
+looks_bad = any(marker in first_25_lines for marker in markers)
+looks_bad = looks_bad or first_25_lines.lstrip().startswith("(cd ")
+
+if looks_bad:
+    print("app.py contains pasted shell/patch text. Restoring app.py from git HEAD...")
+    subprocess.check_call(["git", "restore", "--source=HEAD", "--", "app.py"])
+else:
+    print("app.py header looks clean. No restore needed.")
+
+py_compile.compile("app.py", doraise=True)
+print("SUCCESS: app.py is valid Python now.")
+PY
+
+echo "Done. Now redeploy/reboot your Streamlit app."
+```
+
+---
+
+## Option C — use the repo repair tool
+
+If this repository already contains the repair tool, run:
+
+```bash
+python scripts/repair_pasted_patch.py app.py
+python -m py_compile app.py
+```
+
+If it says `app.py` is clean but Streamlit still shows the old error, Streamlit Cloud is running an old deployed copy. Reboot/redeploy the app from the latest GitHub commit.
+
+## Option D — create a script file manually
+
+If you prefer to paste into a file instead of a terminal, create this file:
+
+### File name
+
+`copy_paste_streamlit_fix.sh`
+
+### File location
+
+```text
+network-intelligence-platform/scripts/copy_paste_streamlit_fix.sh
+```
+
+Then paste the script from Option B into that file, save it, and run:
+
+```bash
+bash scripts/copy_paste_streamlit_fix.sh
+```
 
EOF
)
