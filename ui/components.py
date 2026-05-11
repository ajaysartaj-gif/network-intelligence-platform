"""Reusable Streamlit UI components."""

import streamlit as st
from typing import Optional, List, Dict


def ai_insight_card(
    label: str,
    text: str,
    confidence: Optional[int] = None,
    sources: Optional[List[str]] = None,
):
    """Render AI insight card with confidence score."""
    conf_html = ""
    if confidence is not None:
        cls = (
            "conf-high"
            if confidence >= 80
            else "conf-med"
            if confidence >= 60
            else "conf-low"
        )
        conf_html = f'<div class="nb-conf {cls}"><span>{confidence}%</span></div>'

    src_html = ""
    if sources:
        src_html = "<div>" + "".join(
            f'<span style="font-size:10px;padding:2px 6px;border-radius:5px;background:rgba(57,211,83,.1);color:#39d353;margin:2px">{s}</span>'
            for s in sources
            if s
        ) + "</div>"

    st.markdown(
        f'''<div class="nb-ai-insight">
        <div class="nb-ai-hdr">🧠 {label}</div>
        <div class="nb-ai-body">{text}</div>
        {conf_html}{src_html}
    </div>''',
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str = ""):
    """Render section header with optional subtitle."""
    sub = (
        f'<div style="font-size:12px;color:var(--text-tertiary);margin-top:2px">{subtitle}</div>'
        if subtitle
        else ""
    )
    st.markdown(
        f'<div style="margin-bottom:14px"><div style="font-family:Fraunces,serif;font-size:18px;font-weight:700;color:var(--text-primary)">{title}</div>{sub}</div>',
        unsafe_allow_html=True,
    )


def metric_grid(metrics: List[Dict]):
    """Render grid of metric cards."""
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        with col:
            st.metric(m["label"], m["value"], delta=m.get("delta"))


def render_device_card(device: Dict):
    """Render device status card."""
    status_class = f"dev-{device['status']}"
    cpu = device.get("cpu", 0)
    mem = device.get("memory", 0)
    cpu_cls = "mv-crit" if cpu >= 80 else "mv-warn" if cpu >= 60 else "mv-ok"
    mem_cls = "mv-crit" if mem >= 80 else "mv-warn" if mem >= 60 else "mv-ok"

    st.markdown(
        f'''<div class="nb-dev {status_class}">
        <div class="nb-dev-hn">{device['hostname']}</div>
        <div class="nb-dev-role">{device.get('role', '')}</div>
        <div class="nb-dev-site">📍 {device.get('site', '')}</div>
        <div class="nb-dev-metrics">
            <div class="nb-dev-m"><div class="nb-dev-mv {cpu_cls}">{cpu}%</div><div class="nb-dev-ml">CPU</div></div>
            <div class="nb-dev-m"><div class="nb-dev-mv {mem_cls}">{mem}%</div><div class="nb-dev-ml">MEM</div></div>
        </div>
    </div>''',
        unsafe_allow_html=True,
    )


def render_warroom_card(
    title: str,
    severity: str,
    description: str,
    root_cause: str,
    confidence: int,
):
    """Render war room incident card."""
    sev_class = "critical" if severity == "critical" else "major"
    st.markdown(
        f'''<div class="nb-warroom nb-warroom-{sev_class}">
        <h3>{title}</h3>
        <p>{description}</p>
        <p><strong>Root Cause:</strong> {root_cause}</p>
        <div class="nb-conf">Confidence: {confidence}%</div>
    </div>''',
        unsafe_allow_html=True,
    )


def risk_bar(score: int):
    """Render risk score bar chart."""
    cls = "risk-low" if score < 30 else "risk-med" if score < 65 else "risk-high"
    st.markdown(
        f'<div class="nb-risk-wrap {cls}"><div class="nb-risk-track"><div class="nb-risk-fill" style="width:{score}%"></div></div><span class="nb-risk-score">{score}</span></div>',
        unsafe_allow_html=True,
    )
