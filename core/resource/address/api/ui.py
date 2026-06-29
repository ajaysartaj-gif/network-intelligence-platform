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

    foundation, intelligence = st.tabs(["📚 Knowledge Foundation", "🧠 Intelligence Explorer"])

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

    # ── Intelligence Explorer (consumes the Context Builder bundle) ──────────
    with intelligence:
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
        if ev.violations:
            for v in ev.violations:
                st.write(f"- {v}")
        if ev.recommendations:
            st.caption("Recommendations")
            for r in ev.recommendations:
                st.write(f"• {r}")

        st.markdown("#### 🔗 Dependency Intelligence")
        dep = api.dependency_graph(bundle).to_dict()
        st.json(dep)

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
