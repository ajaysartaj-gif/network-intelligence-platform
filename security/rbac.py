"""Role-based access control."""

import streamlit as st
from typing import Set
from config import PERMISSIONS


def get_current_role() -> str:
    """Get current user role from session state."""
    return st.session_state.get("user_role", "admin")


def has_permission(permission: str) -> bool:
    """Check if current user has permission."""
    role = get_current_role()
    return permission in PERMISSIONS.get(role, set())


def require_permission(permission: str) -> bool:
    """Show warning and return False if permission denied."""
    if not has_permission(permission):
        st.warning(
            f"🔒 Access denied — your role ({get_current_role()}) cannot perform: `{permission}`"
        )
        return False
    return True


def get_role_label() -> str:
    """Get human-readable role label."""
    role_labels = {
        "admin": "👑 Admin",
        "architect": "🏗 Architect",
        "noc": "🖥 NOC Engineer",
        "security": "🔒 Security Engineer",
        "readonly": "👁 Read Only",
        "executive": "📊 Executive",
    }
    return role_labels.get(get_current_role(), "Unknown")
