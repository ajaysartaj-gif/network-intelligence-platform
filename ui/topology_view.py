"""
Topology View — renders network topology with device health status.
Uses device metrics from state manager to color-code health.
"""
import streamlit as st
import pandas as pd
from typing import Dict, List, Any, Optional


def _health_color(status: str) -> str:
    return {"healthy": "🟢", "warning": "🟡", "critical": "🔴", "unknown": "⚫"}.get(status, "⚫")


def _reachable_icon(reachable: bool) -> str:
    return "✅" if reachable else "❌"


def render_topology_kpis(state_manager, simulator) -> None:
    """Render top KPI row for topology workspace."""
    all_metrics = state_manager.get_all_device_metrics()
    total = len(all_metrics)
    healthy = sum(
        1 for m in all_metrics.values()
        if getattr(m, "reachable", True) and m.cpu < 80 and m.memory < 80
    )
    critical    = len(state_manager.get_critical_devices())
    unreachable = sum(1 for m in all_metrics.values() if not getattr(m, "reachable", True))
    links_total = len(getattr(simulator, "links", []))
    links_down  = sum(
        1 for lnk in getattr(simulator, "links", [])
        if getattr(lnk, "status", "up") != "up"
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Devices", total)
    c2.metric(
        "Healthy",
        healthy,
        delta=f"{total - healthy} issues" if total > healthy else "All green",
    )
    c3.metric("Critical",    critical,    delta_color="inverse" if critical    else "off")
    c4.metric("Unreachable", unreachable, delta_color="inverse" if unreachable else "off")
    c5.metric("Links Down",  links_down,  delta_color="inverse" if links_down  else "off")


def render_device_health_table(state_manager, telemetry_engine) -> None:
    """Render the main device health matrix table."""
    all_metrics = state_manager.get_all_device_metrics()
    if not all_metrics:
        st.info("No device telemetry yet — polling in progress...")
        return

    rows = []
    for hostname, metrics in all_metrics.items():
        health    = telemetry_engine.get_device_health_score(hostname)
        score     = health.get("score", 0)
        status    = health.get("status", "unknown")
        reachable = getattr(metrics, "reachable", True)
        issues    = health.get("issues", [])

        rows.append({
            "Status":    _health_color(status),
            "Device":    hostname,
            "Reachable": _reachable_icon(reachable),
            "Health %":  f"{score:.0f}%",
            "CPU":       f"{metrics.cpu:.1f}%",
            "Memory":    f"{metrics.memory:.1f}%",
            "Latency":   f"{metrics.latency_ms:.1f}ms",
            "Pkt Loss":  f"{metrics.packet_loss_pct:.2f}%",
            "BGP↓":      str(metrics.bgp_sessions_down) if metrics.bgp_sessions_down else "—",
            "Issues":    ", ".join(issues[:2]) if issues else "None",
        })

    df = pd.DataFrame(rows)
    # Sort: critical first, then warning, then healthy
    order_map = {"🔴": 0, "🟡": 1, "🟢": 2, "⚫": 3}
    df["_sort"] = df["Status"].map(order_map)
    df = df.sort_values("_sort").drop(columns=["_sort"])

    st.dataframe(df, use_container_width=True, height=400)


def render_site_summary(simulator) -> None:
    """Render per-site device health summary."""
    if not hasattr(simulator, "devices"):
        return

    sites: Dict[str, Dict[str, int]] = {}
    for dev in simulator.devices.values():
        site = getattr(dev, "site", "unknown")
        if site not in sites:
            sites[site] = {"total": 0, "healthy": 0, "warning": 0, "critical": 0}
        sites[site]["total"] += 1
        status = getattr(dev, "status", "healthy")
        if status == "healthy":
            sites[site]["healthy"] += 1
        elif status == "critical":
            sites[site]["critical"] += 1
        else:
            sites[site]["warning"] += 1

    if not sites:
        return

    st.markdown("### Site Health Overview")
    cols = st.columns(min(len(sites), 6))
    for col, (site, counts) in zip(cols, sites.items()):
        total    = counts["total"]
        healthy  = counts["healthy"]
        critical = counts["critical"]
        color = "🔴" if critical > 0 else "🟡" if counts["warning"] > 0 else "🟢"
        with col:
            st.markdown(
                f"""
                <div style="background:#161b22; border:1px solid #30363d; border-radius:8px;
                            padding:12px; text-align:center;">
                    <div style="font-size:20px;">{color}</div>
                    <div style="font-weight:600; font-size:13px; color:#cdd9e5;">{site.upper()}</div>
                    <div style="font-size:12px; color:#8b949e;">
                        {healthy}/{total} healthy
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_link_status(simulator) -> None:
    """Render network link status table."""
    links = getattr(simulator, "links", [])
    if not links:
        st.info("No link data available.")
        return

    rows = []
    for link in links:
        status = getattr(link, "status", "up")
        icon = "🟢" if status == "up" else "🟡" if status == "warning" else "🔴"
        rows.append({
            "Status":    icon,
            "From":      getattr(link, "source",           "?"),
            "To":        getattr(link, "destination",      "?"),
            "Type":      getattr(link, "link_type",        "?"),
            "Bandwidth": f"{getattr(link, 'bandwidth_mbps',      0):.0f} Mbps",
            "Latency":   f"{getattr(link, 'current_latency_ms',  0):.1f}ms",
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, height=300)


def render_gns3_topology(gns3_engine) -> None:
    """Render GNS3 topology if available."""
    if not gns3_engine or not gns3_engine.available:
        return

    summary = gns3_engine.get_topology_summary()
    st.markdown("### GNS3 Live Topology")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("GNS3 Version", summary.get("version",     "?"))
    c2.metric("Total Nodes",  summary.get("total_nodes", 0))
    c3.metric("Running",      summary.get("running_nodes", 0))
    c4.metric("Links",        summary.get("total_links", 0))

    nodes = summary.get("nodes", [])
    if nodes:
        rows = []
        for n in nodes:
            status_icon = (
                "🟢" if n["status"] == "started"
                else "🔴" if n["status"] == "stopped"
                else "🟡"
            )
            rows.append({
                "Status":      status_icon,
                "Node":        n["name"],
                "Type":        n["type"],
                "Console":     str(n.get("console_port", "—")),
                "GNS3 Status": n["status"],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
