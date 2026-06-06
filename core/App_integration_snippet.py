"""
app_integration_snippet.py
===========================
Paste the sections below into the correct places in your existing app.py.
Search for each ── PASTE LOCATION ── comment to find the right spot.
"""

# ══════════════════════════════════════════════════════════════════════════
# [1] ADD NEAR THE TOP OF app.py (after your existing imports)
# ══════════════════════════════════════════════════════════════════════════

from local_router_access import (
    get_manager,
    render_local_access_ui,
    LocalLinkGenerator,
    Device,
    DeviceCredentials,
)

# ── Print access links to terminal when app starts ────────────────────────
LocalLinkGenerator.print_links()   # shows localhost + LAN URL in terminal


# ══════════════════════════════════════════════════════════════════════════
# [2] ADD INSIDE YOUR SIDEBAR (wherever you define navigation)
#     Paste inside the `with st.sidebar:` block
# ══════════════════════════════════════════════════════════════════════════

# --- inside your existing sidebar block ---
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔗 Access Links")

_links = LocalLinkGenerator.generate_links()
for _name, _url in _links.items():
    _icon = {"localhost": "🖥️", "local_lan": "🌐", "pinggy_fallback": "☁️"}.get(_name, "🔗")
    _label = {"localhost": "Localhost", "local_lan": "Local LAN",
              "pinggy_fallback": "Pinggy Fallback"}.get(_name, _name)
    st.sidebar.markdown(f"{_icon} [{_label}]({_url})")

# Local LAN link as a highlighted box
_lan_url = _links.get("local_lan", "")
if _lan_url:
    st.sidebar.markdown(f"""
    <div style='background:#0f172a;border:1px solid #22d3ee;border-radius:8px;
                padding:.5rem .8rem;font-size:.82rem;color:#22d3ee;
                font-family:monospace;word-break:break-all;'>
    🌐 {_lan_url}
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# [3] ADD A NEW WORKSPACE TAB
#     Paste inside your tab/workspace routing logic.
#     Example — if you use st.tabs() or if/elif for workspace selection:
# ══════════════════════════════════════════════════════════════════════════

# --- wherever you handle workspace/tab content ---

elif workspace == "Local Router Access":          # adjust to your tab label
    render_local_access_ui(get_manager())

# ── OR if you use st.tabs() ──────────────────────────────────────────────

# tab_labels = [..., "🔌 Local Router Access"]    # add to your tab list
# tabs = st.tabs(tab_labels)
# with tabs[-1]:                                  # last tab = local access
#     render_local_access_ui(get_manager())


# ══════════════════════════════════════════════════════════════════════════
# [4] OPTIONAL: Pre-load devices from your existing topology DB
#     Call once at startup (outside any tab/page function)
# ══════════════════════════════════════════════════════════════════════════

def preload_devices_from_db(db_session):
    """
    If your NetBrainDB already has a devices/topology table,
    load them into the LocalRouterAccessManager at startup.
    Replace the query below with your actual ORM model.
    """
    mgr = get_manager()
    try:
        # Example — adjust to your actual model:
        # from models import NetworkDevice
        # rows = db_session.query(NetworkDevice).all()
        # for row in rows:
        #     mgr.register_device(Device(
        #         hostname=row.hostname,
        #         ip=row.management_ip,
        #         device_type=row.device_type or "cisco_ios",
        #         site=row.site or "",
        #     ))
        pass
    except Exception as e:
        print(f"[LocalAccess] Could not preload devices: {e}")


# ══════════════════════════════════════════════════════════════════════════
# [5] ENVIRONMENT VARIABLES — add to your .env or Streamlit secrets
# ══════════════════════════════════════════════════════════════════════════
"""
# .env
PINGGY_FALLBACK_URL=https://your-pinggy-tunnel.a.pinggy.io   # optional fallback
STREAMLIT_PORT=8501                                           # default port

# Run app (generates local + LAN links automatically):
# streamlit run app.py --server.address 0.0.0.0 --server.port 8501
"""
