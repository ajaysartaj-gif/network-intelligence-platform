 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/ui/components.py b/ui/components.py
new file mode 100644
index 0000000000000000000000000000000000000000..21195d7720d4c6424400381639dc604fa194372a
--- /dev/null
+++ b/ui/components.py
@@ -0,0 +1,151 @@
+"""Reusable Streamlit UI components for NetBrain AI."""
+
+from __future__ import annotations
+
+from typing import Optional, List
+
+import streamlit as st
+
+from ui.theme import DESIGN_SYSTEM_CSS
+from utils.html import clamp_percent, html_escape
+
+
+def inject_css() -> None:
+    """Inject the shared NetBrain AI design system CSS once per Streamlit run."""
+    st.markdown(DESIGN_SYSTEM_CSS, unsafe_allow_html=True)
+
+
+def ai_insight_card(
+    label: str,
+    text: str,
+    confidence: Optional[int] = None,
+    sources: Optional[List[str]] = None,
+    trusted_html: bool = True,
+) -> None:
+    """Render a compact AI insight card with optional confidence and source chips.
+
+    Existing workspace insight copy intentionally contains trusted inline markup
+    such as <strong>; dynamic labels and source chips are still escaped.
+    """
+    conf_html = ""
+    if confidence is not None:
+        confidence = clamp_percent(confidence)
+        cls = "conf-high" if confidence >= 80 else "conf-med" if confidence >= 60 else "conf-low"
+        conf_html = (
+            f'<div class="nb-conf {cls}">'
+            f'<span class="nb-conf-pct">{confidence}%</span>'
+            '<div class="nb-conf-track">'
+            f'<div class="nb-conf-fill" style="width:{confidence}%"></div>'
+            '</div><span style="font-size:10px;color:var(--text-tertiary)">'
+            'AI Confidence</span></div>'
+        )
+
+    src_html = ""
+    if sources:
+        src_html = "<div style='margin-top:4px'>" + "".join(
+            '<span style="font-size:10px;padding:1px 6px;border-radius:5px;'
+            'background:rgba(57,211,83,.1);color:#39d353;'
+            'font-family:JetBrains Mono,monospace;margin:1px">'
+            f'{html_escape(source)}</span>'
+            for source in sources
+            if source
+        ) + "</div>"
+
+    st.markdown(
+        f"""<div class="nb-ai-insight">
+          <div class="nb-ai-hdr">🧠 {html_escape(label)}</div>
+          <div class="nb-ai-body">{text if trusted_html else html_escape(text)}</div>
+          {conf_html}{src_html}
+        </div>""",
+        unsafe_allow_html=True,
+    )
+
+
+def metric_grid(metrics: List[dict]) -> None:
+    """Render metric cards in a responsive row."""
+    if not metrics:
+        return
+
+    cols = st.columns(len(metrics))
+    for col, metric in zip(cols, metrics):
+        with col:
+            color = html_escape(metric.get("color", "blue"))
+            st.markdown(
+                f"""<div class="nb-metric nb-m-{color}">
+                  <div class="nb-m-icon">{html_escape(metric.get('icon', ''))}</div>
+                  <div class="nb-m-lbl">{html_escape(metric.get('label', ''))}</div>
+                  <div class="nb-m-val">{html_escape(metric.get('value', ''))}</div>
+                  <div class="nb-m-meta">{html_escape(metric.get('meta', ''))}</div>
+                </div>""",
+                unsafe_allow_html=True,
+            )
+
+
+def render_chat_message(role: str, content: str, meta: Optional[dict] = None) -> None:
+    """Render a user or AI chat message and its provenance chips."""
+    safe_content = html_escape(content)
+    if role == "user":
+        st.markdown(
+            '<div style="text-align:right;margin:5px 0">'
+            f'<span class="nb-chat-user">{safe_content}</span></div>',
+            unsafe_allow_html=True,
+        )
+        return
+
+    st.markdown(
+        f'<div style="margin:5px 0"><span class="nb-chat-ai">{safe_content}</span></div>',
+        unsafe_allow_html=True,
+    )
+    if not meta:
+        return
+
+    pills = ""
+    if meta.get("persona_used"):
+        pills += f'<span class="nb-mp mp-per">👤 {html_escape(meta["persona_used"])}</span>'
+    if meta.get("rag_topics"):
+        pills += "".join(
+            f'<span class="nb-mp mp-rag">📚 {html_escape(topic)}</span>'
+            for topic in (meta.get("rag_topics") or [])[:2]
+            if topic
+        )
+    if meta.get("similar_incidents"):
+        pills += (
+            '<span class="nb-mp mp-inc">💡 '
+            f'{html_escape(str(meta["similar_incidents"][0])[:35])}</span>'
+        )
+    entities = meta.get("entities") or {}
+    if entities.get("protocols"):
+        pills += (
+            '<span class="nb-mp mp-nlp">🧬 '
+            f'{html_escape(", ".join(entities["protocols"][:3]))}</span>'
+        )
+    if pills:
+        st.markdown(f'<div class="nb-meta-row">{pills}</div>', unsafe_allow_html=True)
+
+
+def section_header(title: str, subtitle: str = "") -> None:
+    """Render a consistent section heading."""
+    subtitle_html = (
+        '<div style="font-size:12px;color:var(--text-tertiary);margin-top:2px">'
+        f'{html_escape(subtitle)}</div>'
+        if subtitle
+        else ""
+    )
+    st.markdown(
+        '<div style="margin-bottom:14px">'
+        '<div style="font-family:Fraunces,serif;font-size:18px;font-weight:700;'
+        f'color:var(--text-primary)">{html_escape(title)}</div>{subtitle_html}</div>',
+        unsafe_allow_html=True,
+    )
+
+
+def risk_bar(score: int) -> None:
+    """Render a bounded risk score bar."""
+    score = clamp_percent(score)
+    cls = "risk-low" if score < 30 else "risk-med" if score < 65 else "risk-high"
+    st.markdown(
+        f'<div class="nb-risk-wrap {cls}"><div class="nb-risk-track">'
+        f'<div class="nb-risk-fill" style="width:{score}%"></div></div>'
+        f'<span class="nb-risk-score">{score}</span></div>',
+        unsafe_allow_html=True,
+    )
 
EOF
)
