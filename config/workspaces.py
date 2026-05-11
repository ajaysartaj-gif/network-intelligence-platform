 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/config/workspaces.py b/config/workspaces.py
new file mode 100644
index 0000000000000000000000000000000000000000..c8747c169e8d0c35f58496e706656a73dae7810f
--- /dev/null
+++ b/config/workspaces.py
@@ -0,0 +1,23 @@
+"""Workspace registry used by the top navigation."""
+
+WORKSPACES = [
+    ('operations', '⚡', 'Operations'),
+    ('incident', '🚨', 'Incidents'),
+    ('topology', '🗺', 'Topology'),
+    ('observe', '📡', 'Observability'),
+    ('troubleshoot', '🔧', 'Diagnose'),
+    ('change', '📋', 'Changes'),
+    ('autonomous', '🤖', 'Autonomous'),
+    ('twin', '👾', 'Digital Twin'),
+    ('security', '🔒', 'Security'),
+    ('compliance', '🛡', 'Compliance'),
+    ('design', '🏗', 'Design'),
+    ('mdq', '⚡', 'Multi-Device'),
+    ('nlp', '🧬', 'NLP'),
+    ('rag', '📚', 'Knowledge'),
+    ('learn', '📖', 'Learn'),
+    ('devices', '🖧', 'Devices'),
+    ('executive', '📈', 'Executive'),
+    ('finops', '💰', 'FinOps'),
+    ('audit', '🔐', 'Audit'),
+]
 
EOF
)
