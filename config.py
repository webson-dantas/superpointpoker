import streamlit as st
import threading


FIBONACCI = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]
DEFAULT_VOTE_BUTTONS = "0;1;2;3;5;8;13;21;X"


@st.cache_resource
def get_shared_state():
    return {
        "sessions": {},
        "lock": threading.Lock(),
        "heartbeat_lock": threading.Lock(),
    }


def get_client_ip():
    """Get the client's IP address from Streamlit request headers."""
    try:
        headers = st.context.headers
        # Check common proxy headers first
        for header in ("Cf-Connecting-Ip", "X-Forwarded-For", "X-Real-Ip"):
            val = headers.get(header)
            if val:
                # X-Forwarded-For can be comma-separated; take the first (client) IP
                return val.split(",")[0].strip()
        # Fall back to Host header as last resort (not ideal but unique enough)
        return headers.get("Host", "unknown")
    except Exception:
        return "unknown"


def get_cookies():
    """Parse cookies from Streamlit request headers."""
    try:
        cookie_header = st.context.headers.get("Cookie", "")
        cookies = {}
        for item in cookie_header.split(";"):
            item = item.strip()
            if "=" in item:
                key, _, value = item.partition("=")
                cookies[key.strip()] = value.strip()
        return cookies
    except Exception:
        return {}
