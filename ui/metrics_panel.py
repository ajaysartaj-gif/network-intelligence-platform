"""
Metrics Panel — real-time device metrics visualization.
Renders CPU, memory, latency, and packet loss with color-coded status badges.
"""
import streamlit as st
import pandas as pd
from typing import Dict, Any, Optional
from datetime import datetime


def _badge(value: float, warn_threshold: float, crit_threshold: float, unit: str = "%") -> str:
    """Return a color-coded badge string for a metric value."""
    if value >= crit_threshold:
        return f"🔴 {value:.1f}{unit}"
    elif value >= warn_threshold:
        return f"🟡 {value:.1f}{unit}"
    return f"🟢 {value:.1f}{unit}"


def render_fleet_health_kpis(state_manager, telemetry_engine) -> None:
    """Top row: fleet-wide health KPIs."""
    health = telemetry_engine.get_health_metrics()
    if health.get("status") == "no_data":
        st.info("⏳ Collecting telemetry data...")
        return

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric(
        "Avg CPU",
        f"{health['cpu']['average']:.1f}%",
        delta=f"Max {health['cpu']['max']:.0f}%",
        delta_color="inverse" if health["cpu"]["max"] > 80 else "off",
    )
    c2.metric(
        "Avg Memory",
        f"{health['memory']['average']:.1f}%",
        delta=f"Max {health['memory']['max']:.0f}%",
        delta_color="inverse" if health["memory"]["max"] > 80 else "off",
    )
    c3.metric(
        "Avg Latency",
        f"{health['latency_ms']['average']:.1f}ms",
        delta=f"Max {health['latency_ms']['max']:.0f}ms",
        delta_color="inverse" if health["latency_ms"]["max"] > 100 else "off",
    )
    c4.metric(
        "Avg Pkt Loss",
        f"{health['packet_loss_pct']['average']:.2f}%",
        delta=f"Max {health['packet_loss_pct']['max']:.1f}%",
        delta_color="inverse" if health["packet_loss_pct"]["max"] > 3 else "off",
    )
    c5.metric(
        "BGP Sessions Down",
        health.get("bgp_down_sessions", 0),
        delta_color="inverse" if health.get("bgp_down_sessions", 0) > 0 else "off",
    )
    c6.metric(
        "Unreachable",
        health.get("unreachable_devices", 0),
        delta_color="inverse" if health.get("unreachable_devices", 0) > 0 else "off",
    )


def render_device_sparklines(state_manager) -> None:
    """Render per-device CPU/Memory/Latency metrics as a compact color-coded table."""
    all_metrics = state_manager.get_all_device_metrics()
    if not all_metrics:
        return

    rows = []
    for hostname, m in sorted(all_metrics.items()):
        rows.append({
            "Device":   hostname,
            "CPU":      _badge(m.cpu,             80,  90,  "%"),
            "Memory":   _badge(m.memory,          80,  90,  "%"),
            "Latency":  _badge(m.latency_ms,      80,  100, "ms"),
            "Pkt Loss": _badge(m.packet_loss_pct,  3,    5,  "%"),
            "Reachable": "✅" if getattr(m, "reachable", True) else "❌",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, height=320)


def render_telemetry_history_chart(state_manager, hostname: str) -> None:
    """Render CPU/memory history line chart for a specific device."""
    history = state_manager.get_telemetry_history(hostname, limit=50)
    if not history:
        st.info(f"No history yet for {hostname}")
        return

    df = pd.DataFrame([
        {
            "time":     h.get("last_updated", "")[-8:],
            "CPU %":    h.get("cpu",        0),
            "Memory %": h.get("memory",     0),
            "Latency":  h.get("latency_ms", 0),
        }
        for h in history
    ])

    if not df.empty:
        st.line_chart(df.set_index("time")[["CPU %", "Memory %"]])


def render_anomaly_summary(anomalies: list) -> None:
    """Render current anomaly summary badges."""
    if not anomalies:
        st.success("✅ No anomalies detected — all metrics within normal thresholds")
        return

    st.markdown(f"**⚠️ {len(anomalies)} active anomaly(ies):**")
    for a in anomalies[:10]:
        severity_icon = {
            "critical": "🔴",
            "high":     "🟠",
            "medium":   "🟡",
        }.get(a.get("severity", ""), "⚪")
        atype   = a.get("type",   "unknown").replace("_", " ").title()
        device  = a.get("device", "unknown")
        val     = a.get("value") or a.get("latency_ms") or a.get("loss_pct") or ""
        val_str = f" ({val:.1f})" if isinstance(val, (int, float)) else ""
        st.markdown(f"  {severity_icon} **{atype}** on `{device}`{val_str}")
