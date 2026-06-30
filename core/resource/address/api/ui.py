"""
NRIE · API · Admin UI panel (read-only + intelligence explorer)
===============================================================
Renders the NRIE knowledge foundation AND the Phase-2 intelligence (cognition,
policy, dependencies, decision/operational/prediction history) inside the Admin
area, beside Network Topology. All intelligence is driven by the single
ResourceContextBundle from the Context Builder.
"""
from __future__ import annotations

from .service import get_nrie_service


def _seed_demo(svc) -> str:
    """Create a small, realistic sample so the intelligence is visible."""
    from ..contracts.commands import (
        RegisterEnterpriseEntity, RecordResource, AttachBusinessContext,
        CaptureOrganizationalKnowledge,
    )
    org = svc.register_enterprise_entity(RegisterEnterpriseEntity(level="organization", name="Acme Corp", owner="netops"))
    site = svc.register_enterprise_entity(RegisterEnterpriseEntity(level="site", name="PUNE-MFG-01", parent_id=org, owner="plant-ops"))
    rid = svc.record_resource(RecordResource(resource_type="subnet", name="ot-lan", purpose="ot", hierarchy_ref=site, status="planned"))
    svc.record_resource(RecordResource(resource_type="vlan", name="vlan240", purpose="ot", hierarchy_ref=site))
    svc.attach_business_context(AttachBusinessContext(
        attached_to=site, site_type="manufacturing", business_function="production",
        industry="manufacturing", users=250, criticality="high",
        services={"voice": True, "ot": True, "cctv": True}, compliance=["pci"]))
    svc.capture_knowledge(CaptureOrganizationalKnowledge(kind="address_standard", title="RFC1918 corporate usage"))
    # record some intelligence so history is non-empty
    try:
        from ..api.intelligence_api import get_intelligence_api
        api = get_intelligence_api()
        bundle = svc.build_context_bundle(rid)
        if bundle is not None:
            api.decisions.record(decision_type="resource_classification", bundle=bundle,
                                 alternatives=["dedicated /24", "shared /23"], confidence=0.82,
                                 final_decision="dedicated /24",
                                 reasoning_summary="OT isolation favours a dedicated secure subnet")
            api.operational.record(kind="allocation", bundle=bundle, detail="initial knowledge recorded")
            p = api.predictive.record(kind="capacity", bundle=bundle, predicted_value=80.0, model_confidence=0.7)
            api.predictive.record_outcome(p.prediction_id, actual_value=76.0, feedback="tracking well")
    except Exception:
        pass
    return rid


def render_nrie_panel() -> None:
    import streamlit as st

    svc = get_nrie_service()
    st.markdown("### 🧮 IP Intelligence (NRIE)")
    st.caption("Enterprise resource knowledge + Phase-2 intelligence (cognition, policy, "
               "dependencies, decision/operational/prediction memory). Read-only; allocation "
               "arrives in a later phase.")

    if st.button("➕ Load demo data", key="nrie_seed",
                 help="Seed a sample site/subnet + intelligence records so the panel is populated"):
        try:
            rid = _seed_demo(svc)
            st.success(f"Demo data loaded (sample resource {rid}).")
        except Exception as e:
            st.error(f"Could not seed demo data: {e}")

    foundation, intelligence, planning, autonomy = st.tabs(
        ["📚 Knowledge Foundation", "🧠 Intelligence Explorer",
         "🤖 Autonomous Planning", "🌐 Intent & Autonomy"])

    # ── Foundation (read-only knowledge) ─────────────────────────────────────
    with foundation:
        f1, f2, f3, f4 = st.tabs(["Enterprise Hierarchy", "Resource Hierarchy",
                                  "Business Context", "Knowledge"])
        with f1:
            nodes = svc.enterprise_hierarchy()
            st.dataframe([{"Level": n.level, "Name": n.name, "Parent": n.parent_id or "—",
                           "Owner": n.owner} for n in nodes], use_container_width=True) \
                if nodes else st.info("No enterprise hierarchy yet — click *Load demo data*.")
        with f2:
            res = svc.resource_hierarchy()
            st.dataframe([{"Type": r.resource_type, "Name": r.name, "Purpose": r.purpose,
                           "Status": r.status, "Resource id": r.id} for r in res],
                         use_container_width=True) \
                if res else st.info("No resources recorded yet.")
        with f3:
            target = st.text_input("Hierarchy node / resource id", key="nrie_ctx_target")
            if target:
                bc = svc.business_context(target.strip())
                st.json(bc.__dict__) if bc else st.info("No business context for that id.")
        with f4:
            recs = svc.knowledge()
            st.dataframe([{"Kind": k.kind, "Title": k.title} for k in recs],
                         use_container_width=True) if recs else st.info("No knowledge captured yet.")

    # ── Intelligence Explorer + Autonomous Planning (helpers; local returns) ──
    with intelligence:
        _render_intelligence_tab(st, svc)
    with planning:
        _render_planning_tab(st, svc)
    with autonomy:
        _render_autonomy_tab(st, svc)


def _render_intelligence_tab(st, svc) -> None:
    """PR-002 — cognition, policy, dependencies, history (bundle-driven)."""
    res = svc.resource_hierarchy()
    if not res:
        st.info("Record or *Load demo data* first, then explore intelligence here.")
        return
    labels = {f"{r.resource_type} · {r.name} ({r.id})": r.id for r in res}
    pick = st.selectbox("Resource", list(labels.keys()), key="nrie_pick")
    rid = labels[pick]
    bundle = svc.build_context_bundle(rid)
    if bundle is None:
        st.warning("Could not assemble a context bundle for that resource.")
        return

    from ..api.intelligence_api import get_intelligence_api
    api = get_intelligence_api()

    st.markdown("#### 🧠 Resource Cognition")
    cog = api.resource_context(bundle)
    c1, c2, c3 = st.columns(3)
    c1.metric("Category", cog.classification.get("category", "—"))
    c2.metric("Purpose class", cog.classification.get("purpose_class", "—"))
    c3.metric("Criticality", cog.criticality)
    st.write(f"**Owner (resolved):** {cog.owner or '—'} · **Business service:** {cog.business_service or '—'}")
    if cog.relationships:
        st.caption("Discovered relationships (via ontology)")
        st.dataframe(cog.relationships, use_container_width=True)

    st.markdown("#### 🛡 Policy Evaluation")
    ev = api.policy_evaluation(bundle)
    st.write(f"**Result:** {'✅ PASS' if ev.passed else '❌ ' + str(len(ev.violations)) + ' violation(s)'}"
             f" · {ev.evaluated_rules} rules evaluated")
    for v in ev.violations:
        st.write(f"- {v}")
    if ev.recommendations:
        st.caption("Recommendations")
        for r in ev.recommendations:
            st.write(f"• {r}")

    st.markdown("#### 🔗 Dependency Intelligence")
    st.json(api.dependency_graph(bundle).to_dict())

    st.markdown("#### 🗂 History (Decision · Operational · Prediction)")
    h1, h2, h3 = st.tabs(["Decisions", "Operational", "Predictions"])
    with h1:
        ds = api.decision_history(rid)
        st.dataframe([{"Type": d.decision_type, "Decision": d.final_decision,
                       "Confidence": d.confidence_score, "Outcome": d.outcome_status}
                      for d in ds], use_container_width=True) \
            if ds else st.info("No decisions recorded for this resource.")
    with h2:
        os_ = api.operational_history(rid)
        st.dataframe([{"Kind": e.kind, "Detail": e.detail,
                       "Deployment": e.deployment_ref or "—"} for e in os_],
                     use_container_width=True) if os_ else st.info("No operational history.")
    with h3:
        ps = api.prediction_history(rid)
        st.dataframe([{"Kind": p.kind, "Predicted": p.predicted_value,
                       "Actual": p.actual_value, "Accuracy": p.accuracy} for p in ps],
                     use_container_width=True) if ps else st.info("No predictions recorded.")


def _render_planning_tab(st, svc) -> None:
    """PR-003 — autonomous planning, allocation, validation, explainability."""
    res = svc.resource_hierarchy()
    if not res:
        st.info("Record or *Load demo data* first, then run autonomous planning.")
        return
    labels = {f"{r.resource_type} · {r.name} ({r.id})": r.id for r in res}
    pick = st.selectbox("Plan for resource", list(labels.keys()), key="nrie_plan_pick")
    rid = labels[pick]
    bundle = svc.build_context_bundle(rid)
    if bundle is None:
        st.warning("Could not assemble a context bundle for that resource.")
        return

    intent = st.text_input("Business intent", value="Deploy a 250-user manufacturing site",
                           key="nrie_plan_intent")
    space = st.text_input("Address space (supernet)", value="10.40.0.0/16", key="nrie_plan_space")
    st.caption("Demands (purpose : host count) — NRIE sizes with growth + criticality headroom.")
    default_demands = "user_lan:250, voice:250, ot:128, guest:200, mgmt:32"
    raw = st.text_input("Demands", value=default_demands, key="nrie_plan_demands")

    if st.button("🤖 Generate plan", key="nrie_plan_go"):
        from ..allocation.allocator import AddressDemand
        from ..api.planning_api import get_planning_api
        demands = []
        for part in raw.split(","):
            if ":" in part:
                p, h = part.split(":", 1)
                try:
                    demands.append(AddressDemand(p.strip(), int(h.strip())))
                except ValueError:
                    pass
        api = get_planning_api()
        outcome = api.plan(bundle=bundle, intent=intent, demands=demands, address_space=space)

        st.markdown("#### 📐 Enterprise Resource Plan")
        st.write(f"**Status:** {'✅ complete' if outcome.plan.success else '⚠️ incomplete'} · "
                 f"VRFs: {', '.join(outcome.plan.vrfs) or '—'} · "
                 f"VLANs: {outcome.plan.vlans} · headroom: {outcome.plan.growth_headroom_pct:.0f}%")
        st.dataframe([{"Purpose": s.purpose, "CIDR": s.cidr, "Gateway": s.gateway,
                       "VLAN": s.vlan, "VRF": s.vrf, "Usable hosts": s.usable_hosts}
                      for s in outcome.plan.subnets], use_container_width=True)
        if outcome.plan.dhcp_pools or outcome.plan.dns_zones:
            st.caption(f"DHCP pools: {len(outcome.plan.dhcp_pools)} · "
                       f"DNS zones: {', '.join(outcome.plan.dns_zones) or '—'}")

        st.markdown("#### ✅ Validation")
        v = outcome.validation
        st.write(f"**{'PASS' if v.valid else 'ISSUES'}** — checks: {', '.join(v.checks_run)}")
        for i in v.issues:
            st.write(f"- {i}")

        st.markdown("#### 🏆 Ranked Recommendations")
        st.dataframe([{"Option": r.label, "Confidence": r.confidence, "Risk": r.risk,
                       "Cost": r.cost, "Growth fit": r.growth_suitability,
                       "Business impact": r.business_impact} for r in outcome.recommendations],
                     use_container_width=True)

        st.markdown("#### 💡 Explanation")
        ex = outcome.explanation
        st.write(f"**Why:** {ex.why}")
        st.write(f"**Confidence:** {ex.confidence}")
        st.write(f"**Evidence:** {', '.join(ex.evidence)}")
        st.write(f"**Business requirements:** {', '.join(ex.business_requirements)}")
        st.write(f"**Benefits:** {', '.join(ex.expected_benefits)}")
        if ex.risks:
            st.write(f"**Risks:** {', '.join(ex.risks)}")
        st.write(f"**Future impact:** {ex.future_impact}")

        st.markdown("#### ⚙️ Optimization Opportunities")
        opt = api.optimize(bundle=bundle, address_space=space,
                           allocated_cidrs=[s.cidr for s in outcome.plan.subnets])
        if opt:
            st.dataframe([{"Kind": o["kind"], "Severity": o["severity"],
                           "Detail": o["detail"]} for o in opt], use_container_width=True)
        else:
            st.caption("No optimization opportunities detected for this plan.")

        st.info("NRIE plans and allocates only. Existing deployment components remain "
                "responsible for execution — no configuration was generated.")


def _render_autonomy_tab(st, svc) -> None:
    """AI-native: NL intent → full hierarchy + autonomous plan + live IP scan."""
    from ..ai.assistant import available as ai_available

    st.markdown("#### 🌐 Autonomous, AI-native site design")
    st.caption("Type what you want in plain English. NRIE decides the subnets/VLANs/VRFs, "
               "builds Region → Country → State → City → Campus → Site → Building → Floor → "
               "Subnet → IP, and can scan for active IPs with a description against each.")
    st.write(f"**AI status:** {'🟢 Groq connected' if ai_available() else '🟡 offline — deterministic fallback active'}")

    intent_text = st.text_input("Intent", value="deploy a 20 users site in Mumbai",
                                key="nrie_auto_intent")
    col1, col2 = st.columns(2)
    space = col1.text_input("Address space", value="10.40.0.0/16", key="nrie_auto_space")
    do_scan = col2.checkbox("Scan first subnet for active IPs", value=True, key="nrie_auto_scan")

    if st.button("🚀 Design site autonomously", key="nrie_auto_go"):
        from ..api.autonomy_api import get_autonomy_api
        api = get_autonomy_api()
        with st.spinner("Parsing intent, building hierarchy, planning resources…"):
            res = api.design_site(intent_text, address_space=space, scan=do_scan)

        si, loc = res.intent, res.location
        st.success(f"Parsed: **{si.users} users**, **{si.site_type}**, "
                   f"**{loc.city or '—'}** ({loc.state}, {loc.country}, {loc.region}) "
                   f"· intent via {si.source}, location via {loc.source}")

        st.markdown("##### 🏢 Enterprise hierarchy (auto-built)")
        st.dataframe([{"Level": n["level"].title(), "Name": n["name"]}
                      for n in res.hierarchy.ordered()], use_container_width=True)

        if res.plan and res.plan.plan.subnets:
            st.markdown("##### 📐 Auto-planned subnets")
            st.dataframe([{"Purpose": s.purpose, "CIDR": s.cidr, "Gateway": s.gateway,
                           "VLAN": s.vlan, "VRF": s.vrf, "Hosts": s.usable_hosts}
                          for s in res.plan.plan.subnets], use_container_width=True)
            st.caption(f"VRFs: {', '.join(res.plan.plan.vrfs)} · "
                       f"DHCP pools: {len(res.plan.plan.dhcp_pools)} · "
                       f"DNS zones: {len(res.plan.plan.dns_zones)} · "
                       f"validation: {'✅' if res.plan.validation.valid else '⚠️ ' + str(len(res.plan.validation.issues)) + ' issue(s)'}")

        if res.scanned_ips:
            st.markdown("##### 🔎 Active IPs discovered (with description)")
            st.dataframe([{"IP": d.ip, "Engaged as": d.engaged_as,
                           "Description": d.description, "Hostname": d.hostname or "—",
                           "Vendor": d.vendor or "—", "Ports": ", ".join(map(str, d.open_ports)) or "—"}
                          for d in res.scanned_ips], use_container_width=True)
        elif do_scan:
            st.info("No active IPs harvested in this environment. In production the scanner "
                    "reuses the platform discovery engine (ICMP + GNS3 + range scan).")

        for n in res.notes:
            st.caption(f"• {n}")
        st.info("NRIE planned, allocated and inventoried autonomously. Deployment remains "
                "with the existing platform components — no device configuration was generated.")
