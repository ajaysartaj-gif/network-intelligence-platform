 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/utils/html.py b/utils/html.py
new file mode 100644
index 0000000000000000000000000000000000000000..b277168c2a9c153554919beb950bf3ff9b6b5bf5
--- /dev/null
+++ b/utils/html.py
@@ -0,0 +1,20 @@
+"""HTML safety helpers for Streamlit components."""
+
+from __future__ import annotations
+
+from html import escape as _escape
+from typing import Any
+
+
+def html_escape(value: Any) -> str:
+    """Return a safe string for interpolation into unsafe_allow_html blocks."""
+    return _escape("" if value is None else str(value), quote=True)
+
+
+def clamp_percent(value: Any, default: int = 0) -> int:
+    """Coerce a value to an integer percentage bounded to 0..100."""
+    try:
+        score = int(value)
+    except (TypeError, ValueError):
+        score = default
+    return max(0, min(100, score))
 
EOF
)
