"""
NRIE · API · Read-only UI panel
===============================
A thin Streamlit panel that renders the foundation's READ-ONLY views
(enterprise hierarchy, resource hierarchy, business context, organizational
knowledge). It calls only the read API — no allocation, planning, or writes from
here. Designed to sit next to the Network Topology workspace.
"""
from __future__ import annotations

from .service import get_nrie_service


def render_nrie_panel() -> None:
    import streamlit as st

    svc = get_nrie_service()
    st.markdown("## 🧮 IP Intelligence (NRIE) — Knowledge Foundation")
    st.caption("Read-only enterprise resource knowledge. Allocation & planning arrive in later phases.")

    tabs = st.tabs(["Enterprise Hierarchy", "Resource Hierarchy",
                    "Business Context", "Organizational Standards", "Knowledge"])

    with tabs[0]:
        nodes = svc.enterprise_hierarchy()
        if not nodes:
            st.info("No enterprise hierarchy recorded yet.")
        else:
            st.dataframe([{"Level": n.level, "Name": n.name, "Parent": n.parent_id or "—",
                           "Lifecycle": n.lifecycle, "Owner": n.owner} for n in nodes],
                         use_container_width=True)

    with tabs[1]:
        res = svc.resource_hierarchy()
        if not res:
            st.info("No resource knowledge recorded yet.")
        else:
            st.dataframe([{"Type": r.resource_type, "Name": r.name, "Purpose": r.purpose,
                           "Status": r.status, "Lifecycle": r.lifecycle,
                           "Utilization %": r.utilization_pct, "Hierarchy": r.hierarchy_ref or "—"}
                          for r in res], use_container_width=True)

    with tabs[2]:
        st.caption("Business context is attached per hierarchy node / resource id.")
        target = st.text_input("Target id", key="nrie_ctx_target")
        if target:
            bc = svc.business_context(target.strip())
            if bc:
                st.json({"site_type": bc.site_type, "function": bc.business_function,
                         "industry": bc.industry, "users": bc.users,
                         "criticality": bc.criticality, "services": bc.services,
                         "compliance": bc.compliance})
            else:
                st.info("No business context attached to that id.")

    with tabs[3]:
        from ..knowledge.standards import ORGANIZATIONAL_STANDARD_KINDS
        st.write("Recognised standard kinds:")
        st.write(", ".join(ORGANIZATIONAL_STANDARD_KINDS))

    with tabs[4]:
        records = svc.knowledge()
        if not records:
            st.info("No organizational knowledge captured yet.")
        else:
            st.dataframe([{"Kind": k.kind, "Title": k.title, "Lifecycle": k.lifecycle}
                          for k in records], use_container_width=True)
