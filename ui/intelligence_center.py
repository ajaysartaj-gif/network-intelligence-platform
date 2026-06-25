"""
ui/intelligence_center.py
=========================
The Intelligence Center — the AI Brain of the platform.

NOT a monitoring dashboard and NOT an "operational memory page": this is the
organization's accumulated operational experience, surfaced as 13 sections,
every one powered by the LIVE Operational Memory in Supabase via the existing
OperationalMemory API. No fabricated data — sections render honest empty
states until real experience accumulates, and fill automatically as the
platform learns from deployments, incidents, verifications and remediations.

Rendered from app.py via render_intelligence_center(). Reuses the existing
memory backend only (no duplicated storage logic).
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st


# ── data access (single source: the existing Operational Memory) ─────────────
def _mem():
    from core.intelligence.operational_memory import get_operational_memory
    return get_operational_memory()


def _ts_human(ts: float) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def _safe(fn, default):
    try:
        return fn()
    except Exception as exc:
        st.caption(f"⚠️ memory read issue: {exc}")
        return default


def _empty(msg: str, sub: str = ""):
    st.markdown(
        f"<div style='padding:34px;border:1px dashed rgba(148,163,184,.35);"
        f"border-radius:14px;text-align:center;color:#94a3b8;'>"
        f"<div style='font-size:1.05rem;margin-bottom:6px;'>🧠 {msg}</div>"
        f"<div style='font-size:.85rem;opacity:.8;'>{sub}</div></div>",
        unsafe_allow_html=True,
    )


def _metric_card(col, label, value, sub=""):
    col.markdown(
        f"<div style='background:linear-gradient(135deg,#1e293b,#0f172a);"
        f"border:1px solid rgba(148,163,184,.18);border-radius:14px;padding:16px 18px;'>"
        f"<div style='color:#94a3b8;font-size:.78rem;text-transform:uppercase;"
        f"letter-spacing:.04em;'>{label}</div>"
        f"<div style='color:#f1f5f9;font-size:1.7rem;font-weight:700;margin-top:4px;'>{value}</div>"
        f"<div style='color:#64748b;font-size:.75rem;margin-top:2px;'>{sub}</div></div>",
        unsafe_allow_html=True,
    )


# Event type constants (mirror operational_memory.EventType values)
ET_DEPLOY = "deployment_outcome"
ET_VERIFY = "verification_result"
ET_REMEDIATION = "remediation"
ET_INCIDENT = "incident"
ET_ROOT_CAUSE = "root_cause"
ET_ROLLBACK = "rollback"
ET_DECISION = "operator_decision"
ET_RECURRING = "recurring_failure"


def _all_events(limit: int = 5000) -> List[Dict[str, Any]]:
    return _safe(lambda: _mem().temporal(limit=limit), [])


def _learning_score(metrics: Dict[str, Any], events: List[Dict[str, Any]]) -> int:
    """A transparent 0-100 'AI Learning Score': breadth of experience +
    success ratio + knowledge volume. Honest, derived from real counts."""
    by_type = metrics.get("by_type", {}) or {}
    total = metrics.get("total_events", 0) or 0
    if not total:
        return 0
    successes = sum(1 for e in events if e.get("outcome") == "success")
    success_ratio = successes / max(1, len([e for e in events if e.get("outcome") in ("success", "failure")]))
    breadth = len(by_type) / 8.0  # 8 event types
    volume = min(total / 200.0, 1.0)  # saturates at 200 events
    score = 0.45 * success_ratio + 0.25 * breadth + 0.30 * volume
    return int(round(score * 100))


# ═══════════════════════════════════════════════════════════════════════════
# 1. INTELLIGENCE DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════
def _section_dashboard():
    st.markdown("### 🧠 Intelligence Dashboard")
    st.caption("The organization's accumulated operational experience, live from Supabase.")
    metrics = _safe(lambda: _mem().metrics(), {})
    events = _all_events()
    by_type = metrics.get("by_type", {}) or {}
    total = metrics.get("total_events", 0) or 0

    if not total:
        _empty("The AI Brain is ready and connected — no experience recorded yet.",
               "As deployments, verifications and remediations run through the platform, "
               "this brain fills automatically and these cards come alive.")
        return

    recurring = _safe(lambda: _mem().recurring_failures(min_count=2, limit=1000), [])
    successes = [e for e in events if e.get("outcome") == "success"]
    root_causes = [e for e in events if e.get("event_type") == ET_ROOT_CAUSE]

    r1 = st.columns(4)
    _metric_card(r1[0], "Total Knowledge Events", f"{total:,}")
    _metric_card(r1[1], "Known Root Causes", f"{len(root_causes):,}")
    _metric_card(r1[2], "Recurring Problems", f"{len(recurring):,}")
    _metric_card(r1[3], "Successful Remediations", f"{by_type.get(ET_REMEDIATION,0):,}")
    r2 = st.columns(4)
    _metric_card(r2[0], "Deployment History", f"{by_type.get(ET_DEPLOY,0):,}")
    _metric_card(r2[1], "Verification History", f"{by_type.get(ET_VERIFY,0):,}")
    span_a, span_b = metrics.get("oldest_ts"), metrics.get("newest_ts")
    growth = "—"
    if span_a and span_b and span_b > span_a:
        days = max(1, (span_b - span_a) / 86400)
        growth = f"{total/days:.1f}/day"
    _metric_card(r2[2], "Knowledge Growth", growth, "events/day")
    _metric_card(r2[3], "AI Learning Score", f"{_learning_score(metrics, events)}", "out of 100")

    st.markdown("#### Trends & leaders")
    c = st.columns(4)
    _top_list(c[0], "Top Sites", events, "site")
    _top_list(c[1], "Top Devices", events, "device")
    _top_list(c[2], "Top Protocols", events, "protocol")
    _top_list(c[3], "Top Engineers", events, "operator")

    st.markdown("#### Recent learning")
    recent = events[:8]
    if recent:
        st.dataframe(
            [{"When": _ts_human(e.get("ts")), "Type": e.get("event_type"),
              "Summary": e.get("summary"), "Outcome": e.get("outcome")} for e in recent],
            use_container_width=True, hide_index=True)
    _knowledge_growth_chart(events)


def _top_list(col, label, events, field, n=5):
    counts = Counter((e.get(field) or "—") for e in events if e.get(field))
    col.markdown(f"**{label}**")
    if not counts:
        col.caption("— none yet —")
        return
    for name, cnt in counts.most_common(n):
        col.markdown(f"<div style='display:flex;justify-content:space-between;"
                     f"padding:3px 0;border-bottom:1px solid rgba(148,163,184,.1);'>"
                     f"<span style='color:#cbd5e1;'>{name}</span>"
                     f"<span style='color:#38bdf8;font-weight:600;'>{cnt}</span></div>",
                     unsafe_allow_html=True)


def _knowledge_growth_chart(events):
    if len(events) < 2:
        return
    buckets = defaultdict(int)
    for e in events:
        ts = e.get("ts")
        if ts:
            day = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
            buckets[day] += 1
    if len(buckets) < 2:
        return
    days = sorted(buckets)
    cum, running = [], 0
    for d in days:
        running += buckets[d]
        cum.append(running)
    try:
        import pandas as pd
        st.line_chart(pd.DataFrame({"Cumulative knowledge": cum}, index=days))
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 2. AI EXPERIENCE SEARCH
# ═══════════════════════════════════════════════════════════════════════════
def _section_search():
    st.markdown("### 🔎 AI Experience Search")
    st.caption("Ask the brain: “Have we seen this before?” — semantic search over all experience.")
    examples = ["Have we seen this issue before?", "Show all OSPF incidents",
                "Show BGP failures", "Show VLAN deployment history",
                "Show successful remediations", "Show MPLS issues"]
    st.caption("Try: " + " · ".join(f"_{e}_" for e in examples[:4]))

    q = st.text_input("Search operational experience", key="ic_search",
                      placeholder="e.g. OSPF neighbor stuck, BGP flap, VLAN change on core…")
    with st.expander("Filters"):
        fc = st.columns(3)
        f_device = fc[0].text_input("Device", key="ic_f_dev")
        f_site = fc[1].text_input("Site", key="ic_f_site")
        f_proto = fc[2].text_input("Protocol", key="ic_f_proto")
        fc2 = st.columns(3)
        f_engineer = fc2[0].text_input("Engineer", key="ic_f_eng")
        f_type = fc2[1].selectbox("Type", ["any", ET_DEPLOY, ET_VERIFY, ET_REMEDIATION,
                                           ET_INCIDENT, ET_ROOT_CAUSE, ET_RECURRING], key="ic_f_type")
        f_outcome = fc2[2].selectbox("Outcome", ["any", "success", "failure"], key="ic_f_out")

    if not q and not any([f_device, f_site, f_proto, f_engineer]):
        _empty("Search the entire operational history.",
               "Natural-language + semantic search across every remembered event.")
        return

    if q:
        hits = _safe(lambda: _mem().similar(
            q, top_k=40, event_type=(None if f_type == "any" else f_type)), [])
    else:
        hits = _all_events()

    def keep(e):
        if f_device and f_device.lower() not in (e.get("device") or ""): return False
        if f_site and f_site.lower() not in (e.get("site") or ""): return False
        if f_proto and f_proto.lower() not in (e.get("protocol") or ""): return False
        if f_engineer and f_engineer.lower() not in (e.get("operator") or ""): return False
        if f_type != "any" and e.get("event_type") != f_type: return False
        if f_outcome != "any" and e.get("outcome") != f_outcome: return False
        return True

    results = [e for e in hits if keep(e)]
    st.caption(f"{len(results)} result(s)")
    if not results:
        _empty("No matching experience found.", "Either nothing like this has happened yet, or adjust the filters.")
        return
    for e in results[:50]:
        score = e.get("score")
        badge = f" · similarity {score:.2f}" if score is not None else ""
        with st.expander(f"{_outcome_icon(e)} {e.get('summary','(event)')}  ·  {_ts_human(e.get('ts'))}{badge}"):
            _render_event_detail(e)


def _outcome_icon(e):
    return {"success": "✅", "failure": "⚠️"}.get(e.get("outcome"), "•")


def _render_event_detail(e):
    meta = st.columns(4)
    meta[0].caption(f"**Type:** {e.get('event_type','—')}")
    meta[1].caption(f"**Device:** {e.get('device') or '—'}")
    meta[2].caption(f"**Site:** {e.get('site') or '—'}")
    meta[3].caption(f"**Protocol:** {e.get('protocol') or '—'}")
    meta2 = st.columns(4)
    meta2[0].caption(f"**Engineer:** {e.get('operator') or '—'}")
    meta2[1].caption(f"**Outcome:** {e.get('outcome') or '—'}")
    meta2[2].caption(f"**Intent:** {e.get('intent') or '—'}")
    meta2[3].caption(f"**When:** {_ts_human(e.get('ts'))}")
    if e.get("detail"):
        st.code(e["detail"][:4000])


# ═══════════════════════════════════════════════════════════════════════════
# 3. ROOT CAUSE LIBRARY
# ═══════════════════════════════════════════════════════════════════════════
def _section_root_cause():
    st.markdown("### 📚 Root Cause Library")
    st.caption("Permanent, self-merging knowledge base of why things break.")
    events = _all_events()
    rcs = [e for e in events if e.get("event_type") == ET_ROOT_CAUSE]
    recurring = _safe(lambda: _mem().recurring_failures(min_count=1, limit=1000), [])

    if not rcs and not recurring:
        _empty("No root causes recorded yet.",
               "Root causes accumulate as failures are diagnosed and recurring patterns emerge.")
        return

    # Merge recorded root causes with derived recurring-failure signatures.
    rows = []
    for rc in rcs:
        sig = rc.get("signature") or ""
        related = _safe(lambda s=sig: _mem().by_signature(s, limit=50) if s else [], [])
        succ = sum(1 for r in related if r.get("outcome") == "success")
        rows.append({
            "Root Cause": rc.get("summary"),
            "Occurrences": len(related) or 1,
            "Devices": len({r.get("device") for r in related if r.get("device")}),
            "Sites": len({r.get("site") for r in related if r.get("site")}),
            "Protocol": rc.get("protocol") or "—",
            "First Seen": _ts_human(min((r.get("ts") for r in related), default=rc.get("ts"))),
            "Last Seen": _ts_human(max((r.get("ts") for r in related), default=rc.get("ts"))),
            "Success Rate": f"{(succ/len(related)*100):.0f}%" if related else "—",
        })
    for rf in recurring:
        rows.append({
            "Root Cause": f"[recurring] {rf.get('intent') or rf.get('signature')}",
            "Occurrences": rf.get("count"),
            "Devices": "—", "Sites": "—", "Protocol": rf.get("protocol") or "—",
            "First Seen": "—", "Last Seen": _ts_human(rf.get("last_ts")),
            "Success Rate": "—",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption("Similar root causes are auto-merged by signature (protocol + normalized intent + failure set).")


# ═══════════════════════════════════════════════════════════════════════════
# 4. RECURRING FAILURE INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════
def _section_recurring():
    st.markdown("### 🔁 Recurring Failure Intelligence")
    st.caption("Patterns that keep happening — the problems worth fixing permanently.")
    recurring = _safe(lambda: _mem().recurring_failures(min_count=2, limit=200), [])
    if not recurring:
        _empty("No recurring failures detected.",
               "When the same failure signature occurs ≥2 times, it surfaces here automatically.")
        return

    for rf in recurring:
        sig = rf.get("signature")
        related = _safe(lambda s=sig: _mem().by_signature(s, limit=100), [])
        succ_fix = [r for r in related if r.get("event_type") == ET_REMEDIATION and r.get("outcome") == "success"]
        with st.expander(f"🔁 {rf.get('intent') or sig}  ·  {rf.get('count')}× failures  ·  "
                         f"protocol={rf.get('protocol') or '—'}"):
            cc = st.columns(4)
            _metric_card(cc[0], "Frequency", f"{rf.get('count')}×")
            _metric_card(cc[1], "Devices", f"{len({r.get('device') for r in related if r.get('device')})}")
            _metric_card(cc[2], "Sites", f"{len({r.get('site') for r in related if r.get('site')})}")
            _metric_card(cc[3], "Last Seen", _ts_human(rf.get("last_ts")))
            if succ_fix:
                st.success(f"**Most successful resolution:** {succ_fix[0].get('summary')}")
                if succ_fix[0].get("detail"):
                    st.code(succ_fix[0]["detail"][:1500])
            else:
                st.warning("No verified successful resolution recorded yet for this pattern.")
            # AI recommendation hook (uses memory; honest if no fix exists)
            st.caption("**AI recommendation:** "
                       + ("reuse the verified remediation above." if succ_fix
                          else "no proven fix in memory yet — first successful resolution will be remembered here."))


# ═══════════════════════════════════════════════════════════════════════════
# 5. DEPLOYMENT INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════
def _section_deployment():
    st.markdown("### 🚀 Deployment Intelligence")
    st.caption("Every change the platform has made, with its verified outcome.")
    deps = _safe(lambda: _mem().temporal(event_type=ET_DEPLOY, limit=500), [])
    if not deps:
        _empty("No deployments recorded yet.", "Each verified deploy is remembered here with its outcome.")
        return
    q = st.text_input("Filter deployments", key="ic_dep_q", placeholder="intent, device, site…")
    rows = []
    for d in deps:
        if q and q.lower() not in (d.get("summary","")+d.get("device","")+d.get("site","")).lower():
            continue
        rows.append({
            "When": _ts_human(d.get("ts")), "Intent": d.get("intent") or d.get("summary"),
            "Device": d.get("device") or "—", "Site": d.get("site") or "—",
            "Protocol": d.get("protocol") or "—", "Outcome": d.get("outcome") or "—",
            "Engineer": d.get("operator") or "—",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(f"{len(rows)} deployment(s) · click a row’s device in Device Intelligence for full history.")


# ═══════════════════════════════════════════════════════════════════════════
# 6. VERIFICATION INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════
def _section_verification():
    st.markdown("### ✅ Verification Intelligence")
    st.caption("Proof, not assumption — every post-deploy verification the platform ran.")
    vers = _safe(lambda: _mem().temporal(event_type=ET_VERIFY, limit=500), [])
    if not vers:
        _empty("No verification results yet.", "Outcome contracts write verification proof here after each deploy.")
        return
    passed = sum(1 for v in vers if v.get("outcome") == "success")
    failed = len(vers) - passed
    c = st.columns(3)
    _metric_card(c[0], "Verifications", f"{len(vers):,}")
    _metric_card(c[1], "Passed", f"{passed:,}")
    _metric_card(c[2], "Failed", f"{failed:,}")
    for v in vers[:50]:
        with st.expander(f"{_outcome_icon(v)} {v.get('summary')}  ·  {_ts_human(v.get('ts'))}"):
            _render_event_detail(v)


# ═══════════════════════════════════════════════════════════════════════════
# 7. REMEDIATION LIBRARY
# ═══════════════════════════════════════════════════════════════════════════
def _section_remediation():
    st.markdown("### 🛠 Remediation Library")
    st.caption("Reusable, verified fixes — what worked before, ready to reuse.")
    rems = _safe(lambda: _mem().temporal(event_type=ET_REMEDIATION, limit=500), [])
    rems = [r for r in rems if r.get("outcome") == "success"]
    if not rems:
        _empty("No verified remediations yet.",
               "Every successful, verified fix is stored here automatically for reuse.")
        return
    # reuse-count by signature
    sig_counts = Counter(r.get("signature") for r in rems if r.get("signature"))
    for r in rems[:60]:
        reuse = sig_counts.get(r.get("signature"), 1)
        with st.expander(f"✅ {r.get('intent') or r.get('summary')}  ·  {r.get('protocol') or '—'}  ·  seen {reuse}×"):
            _render_event_detail(r)
            st.caption(f"**Recommendation score:** {min(100, 60 + reuse*8)} / 100  ·  "
                       f"reused/seen {reuse}× · verified success")


# ═══════════════════════════════════════════════════════════════════════════
# 8. DEVICE INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════
def _section_device():
    st.markdown("### 🖧 Device Intelligence")
    st.caption("Everything the brain knows about one device.")
    events = _all_events()
    devices = sorted({e.get("device") for e in events if e.get("device")})
    if not devices:
        _empty("No device experience yet.", "Per-device history appears as deployments and incidents accumulate.")
        return
    dev = st.selectbox("Select device", devices, key="ic_dev_sel")
    hist = _safe(lambda: _mem().device_history(dev, limit=500), [])
    _dimensional_view(dev, hist)


# ═══════════════════════════════════════════════════════════════════════════
# 9. SITE INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════
def _section_site():
    st.markdown("### 🏢 Site Intelligence")
    st.caption("Operational health and history per site.")
    events = _all_events()
    sites = sorted({e.get("site") for e in events if e.get("site")})
    if not sites:
        _empty("No site experience yet.", "Per-site intelligence appears as operations run across sites.")
        return
    site = st.selectbox("Select site", sites, key="ic_site_sel")
    hist = _safe(lambda: _mem().site_history(site, limit=1000), [])
    _dimensional_view(site, hist, extra_scores=True)


# ═══════════════════════════════════════════════════════════════════════════
# 10. ENGINEER INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════
def _section_engineer():
    st.markdown("### 👷 Engineer Intelligence")
    st.caption("Each engineer's operational footprint and success profile.")
    events = _all_events()
    engineers = sorted({e.get("operator") for e in events if e.get("operator")})
    if not engineers:
        _empty("No engineer activity recorded yet.",
               "Engineer profiles build as operators run verified changes (set operator on deploy).")
        return
    eng = st.selectbox("Select engineer", engineers, key="ic_eng_sel")
    ev = [e for e in events if e.get("operator") == eng]
    deps = [e for e in ev if e.get("event_type") == ET_DEPLOY]
    vers = [e for e in ev if e.get("event_type") == ET_VERIFY]
    rbs = [e for e in ev if e.get("event_type") == ET_ROLLBACK]
    succ = sum(1 for e in deps if e.get("outcome") == "success")
    c = st.columns(4)
    _metric_card(c[0], "Deployments", f"{len(deps)}")
    _metric_card(c[1], "Verifications", f"{len(vers)}")
    _metric_card(c[2], "Success Rate", f"{(succ/len(deps)*100):.0f}%" if deps else "—")
    _metric_card(c[3], "Rollbacks", f"{len(rbs)}")
    st.markdown("**Preferred technologies**")
    _top_list(st.columns(1)[0], "Protocols", ev, "protocol")
    st.dataframe([{"When": _ts_human(e.get("ts")), "Type": e.get("event_type"),
                   "Summary": e.get("summary"), "Outcome": e.get("outcome")} for e in ev[:50]],
                 use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════
# 11. PROTOCOL INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════
def _section_protocol():
    st.markdown("### 🌐 Protocol Intelligence")
    st.caption("Operational intelligence per technology.")
    known = ["ospf", "bgp", "mpls", "vlan", "vxlan", "stp", "hsrp", "vrrp"]
    events = _all_events()
    present = sorted({e.get("protocol") for e in events if e.get("protocol")})
    protos = [p for p in known if p in present] + [p for p in present if p not in known]
    if not protos:
        _empty("No protocol experience yet.", "Protocol intelligence appears as protocol-specific changes run.")
        return
    proto = st.selectbox("Select protocol", protos, key="ic_proto_sel")
    hist = _safe(lambda: _mem().protocol_history(proto, limit=1000), [])
    deps = [e for e in hist if e.get("event_type") == ET_DEPLOY]
    incs = [e for e in hist if e.get("event_type") in (ET_INCIDENT, ET_RECURRING)]
    succ = sum(1 for e in deps if e.get("outcome") == "success")
    c = st.columns(4)
    _metric_card(c[0], "Deployments", f"{len(deps)}")
    _metric_card(c[1], "Incidents", f"{len(incs)}")
    _metric_card(c[2], "Success Rate", f"{(succ/len(deps)*100):.0f}%" if deps else "—")
    _metric_card(c[3], "AI Confidence", f"{min(95, 40 + len(hist))}%", "grows with experience")
    st.dataframe([{"When": _ts_human(e.get("ts")), "Type": e.get("event_type"),
                   "Device": e.get("device"), "Summary": e.get("summary"),
                   "Outcome": e.get("outcome")} for e in hist[:60]],
                 use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════
# 12. INTELLIGENCE ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════
def _section_analytics():
    st.markdown("### 📊 Intelligence Analytics")
    st.caption("How the brain is growing and where risk concentrates.")
    events = _all_events()
    if not events:
        _empty("No analytics yet.", "Charts populate as operational events accumulate.")
        return
    try:
        import pandas as pd
    except Exception:
        st.caption("pandas unavailable for charts.")
        return

    # Knowledge growth + event mix over time
    by_day_type = defaultdict(lambda: defaultdict(int))
    for e in events:
        ts = e.get("ts")
        if ts:
            day = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
            by_day_type[day][e.get("event_type")] += 1
    if len(by_day_type) >= 2:
        days = sorted(by_day_type)
        df = pd.DataFrame([{**{"day": d}, **by_day_type[d]} for d in days]).set_index("day").fillna(0)
        st.markdown("**Knowledge growth (events/day by type)**")
        st.bar_chart(df)

    cc = st.columns(2)
    with cc[0]:
        st.markdown("**Outcome mix**")
        mix = Counter(e.get("outcome") for e in events if e.get("outcome"))
        if mix:
            st.bar_chart(pd.DataFrame({"count": dict(mix)}))
    with cc[1]:
        st.markdown("**Events by protocol**")
        pm = Counter(e.get("protocol") for e in events if e.get("protocol"))
        if pm:
            st.bar_chart(pd.DataFrame({"count": dict(pm)}))


# ═══════════════════════════════════════════════════════════════════════════
# 13. EXECUTIVE INSIGHTS
# ═══════════════════════════════════════════════════════════════════════════
def _section_executive():
    st.markdown("### 📈 Executive Insights")
    st.caption("AI-generated operational summary for leadership — grounded in real memory.")
    metrics = _safe(lambda: _mem().metrics(), {})
    events = _all_events()
    total = metrics.get("total_events", 0) or 0
    if not total:
        _empty("No executive insight yet.", "Summaries generate once the brain has operational experience.")
        return
    recurring = _safe(lambda: _mem().recurring_failures(min_count=2, limit=100), [])
    by_type = metrics.get("by_type", {}) or {}
    succ = sum(1 for e in events if e.get("outcome") == "success")
    fail = sum(1 for e in events if e.get("outcome") == "failure")

    c = st.columns(4)
    _metric_card(c[0], "Knowledge Events", f"{total:,}")
    _metric_card(c[1], "Verified Successes", f"{succ:,}")
    _metric_card(c[2], "Recurring Risks", f"{len(recurring):,}")
    _metric_card(c[3], "AI Learning Score", f"{_learning_score(metrics, events)}/100")

    st.markdown("#### Top operational risks")
    if recurring:
        for rf in recurring[:5]:
            st.markdown(f"- **{rf.get('intent') or rf.get('signature')}** — failed {rf.get('count')}× "
                        f"(protocol: {rf.get('protocol') or '—'})")
    else:
        st.caption("No recurring risks — no failure pattern has repeated yet.")

    if st.button("🧠 Generate AI executive summary", key="ic_exec_gen"):
        summary = _ai_exec_summary(metrics, events, recurring, succ, fail)
        st.markdown(summary)


def _ai_exec_summary(metrics, events, recurring, succ, fail) -> str:
    """Use the platform AI to narrate the REAL numbers (grounded, not invented)."""
    try:
        from app import call_ai  # reuse the existing Groq client
    except Exception:
        call_ai = None
    facts = (f"Total events={metrics.get('total_events')}, by_type={metrics.get('by_type')}, "
             f"successes={succ}, failures={fail}, recurring_failures={len(recurring)}, "
             f"top_recurring={[r.get('intent') for r in recurring[:5]]}")
    if not call_ai:
        return f"**Summary (from memory):** {facts}"
    prompt = ("You are briefing network operations leadership. Using ONLY these real "
              "operational-memory facts, write a concise executive summary covering "
              "operational risk, knowledge growth, automation success and a recommendation. "
              "Do not invent numbers.\n\nFACTS:\n" + facts)
    try:
        return call_ai(prompt) or f"**Summary:** {facts}"
    except Exception:
        return f"**Summary (from memory):** {facts}"


# ── shared dimensional view (device/site) ────────────────────────────────────
def _dimensional_view(name, hist, extra_scores=False):
    if not hist:
        _empty(f"No history for {name} yet.", "")
        return
    deps = [e for e in hist if e.get("event_type") == ET_DEPLOY]
    incs = [e for e in hist if e.get("event_type") in (ET_INCIDENT, ET_RECURRING)]
    vers = [e for e in hist if e.get("event_type") == ET_VERIFY]
    rcs = [e for e in hist if e.get("event_type") == ET_ROOT_CAUSE]
    succ = sum(1 for e in deps if e.get("outcome") == "success")
    c = st.columns(4)
    _metric_card(c[0], "Deployments", f"{len(deps)}")
    _metric_card(c[1], "Incidents", f"{len(incs)}")
    _metric_card(c[2], "Verifications", f"{len(vers)}")
    _metric_card(c[3], "Root Causes", f"{len(rcs)}")
    if extra_scores:
        c2 = st.columns(3)
        _metric_card(c2[0], "Knowledge Score", f"{min(100, len(hist))}")
        _metric_card(c2[1], "Automation Score",
                     f"{(succ/len(deps)*100):.0f}%" if deps else "—")
        _metric_card(c2[2], "Health Trend",
                     "improving" if succ >= (len(deps)-succ) else "watch")
    st.markdown("**Timeline**")
    st.dataframe([{"When": _ts_human(e.get("ts")), "Type": e.get("event_type"),
                   "Protocol": e.get("protocol"), "Summary": e.get("summary"),
                   "Outcome": e.get("outcome")} for e in hist[:80]],
                 use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════
_SECTIONS = [
    ("Dashboard", _section_dashboard),
    ("Experience Search", _section_search),
    ("Root Cause Library", _section_root_cause),
    ("Recurring Failures", _section_recurring),
    ("Deployments", _section_deployment),
    ("Verification", _section_verification),
    ("Remediation Library", _section_remediation),
    ("Device", _section_device),
    ("Site", _section_site),
    ("Engineer", _section_engineer),
    ("Protocol", _section_protocol),
    ("Analytics", _section_analytics),
    ("Executive Insights", _section_executive),
]


def render_intelligence_center():
    """Single entry point, called from app.py for the 'intelligence' workspace."""
    st.markdown("## 🧠 Intelligence Center")
    st.caption("The AI Brain of the platform — living operational experience, "
               "powered by Operational Memory in Supabase.")

    # connection / status banner (honest about backend + volume)
    try:
        m = _mem()
        be = m._be.kind().upper()
        total = m.count()
        st.markdown(
            f"<div style='display:inline-block;padding:4px 12px;border-radius:999px;"
            f"background:rgba(56,189,248,.12);border:1px solid rgba(56,189,248,.35);"
            f"color:#7dd3fc;font-size:.8rem;'>● Brain online · {be} · {total:,} events remembered</div>",
            unsafe_allow_html=True)
    except Exception as exc:
        st.warning(f"Memory backend not reachable: {exc}")
        return

    st.write("")
    labels = [s[0] for s in _SECTIONS]
    tabs = st.tabs(labels)
    for tab, (_label, fn) in zip(tabs, _SECTIONS):
        with tab:
            try:
                fn()
            except Exception as exc:
                st.error(f"Section error: {exc}")
