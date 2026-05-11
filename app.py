import streamlit as st
import uuid
import sys
import logging

from config import get_shared_state, get_cookies
from state import cleanup_stale_sessions
from views import render_session_view, render_lobby, render_join_via_link

# Suppress harmless Windows ProactorEventLoop connection-reset noise
if sys.platform == "win32":
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# ---------------------------------------------------------------------------
# Streamlit App
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Super Point Poker", page_icon="🃏", layout="centered")

# Fixed-width centered layout
st.markdown("""
<style>
    .block-container {
        max-width: 1100px;
        padding-top: 0.5rem;
        padding-bottom: 2rem;
    }
    [data-testid="stAppViewContainer"] {
        max-width: 100%;
    }
</style>
""", unsafe_allow_html=True)

# Initialize per-client session state
if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())
if "current_session" not in st.session_state:
    st.session_state.current_session = None
if "user_name" not in st.session_state:
    st.session_state.user_name = ""

# Restore nickname, user_id, and session from cookies (instant, no redirect needed)
if "state_restored" not in st.session_state:
    st.session_state.state_restored = True
    cookies = get_cookies()
    if cookies.get("spp_nickname") and not st.session_state.user_name:
        st.session_state.user_name = cookies["spp_nickname"]
    if cookies.get("spp_user_id"):
        st.session_state.user_id = cookies["spp_user_id"]
    if cookies.get("spp_session"):
        st.session_state.current_session = cookies["spp_session"]
    if cookies.get("spp_max_turtles"):
        try:
            st.session_state.max_turtles = int(cookies["spp_max_turtles"])
        except ValueError:
            pass

shared = get_shared_state()

# Auto-close sessions idle for more than 20 minutes
cleanup_stale_sessions(shared)

# Validate restored session still exists; clear if not
if st.session_state.current_session:
    if st.session_state.current_session not in shared["sessions"]:
        st.session_state.current_session = None

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

if st.session_state.current_session:
    render_session_view()
else:
    # Check for session link in query params
    query_session = st.query_params.get("session")
    if query_session and query_session in shared["sessions"]:
        render_join_via_link(query_session)
    else:
        if query_session:
            st.query_params.clear()
        render_lobby()
