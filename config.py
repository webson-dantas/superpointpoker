import streamlit as st
import threading
from urllib.parse import unquote


FIBONACCI = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]
DEFAULT_VOTE_BUTTONS = "0;1;2;3;5;8;13;21;X"

# Voting modes
VOTE_MODE_POINTS = "points"
VOTE_MODE_HOURS = "hours"
DEFAULT_VOTE_MODE = VOTE_MODE_POINTS

# Security limits
MAX_USERNAME_LENGTH = 14
MAX_SESSION_NAME_LENGTH = 100
MAX_TICKET_LABEL_LENGTH = 500
MAX_VOTE_BUTTONS_LENGTH = 500
MAX_PARTICIPANTS_PER_SESSION = 50
MAX_SESSIONS_PER_USER = 10


@st.cache_resource
def get_shared_state():
    return {
        "sessions": {},
        "lock": threading.Lock(),
        "heartbeat_lock": threading.Lock(),
    }


def get_client_ip():
    """Get a hashed version of the client's IP address for dedup without storing real IPs."""
    import hashlib
    try:
        headers = st.context.headers
        raw_ip = None
        # Check common proxy headers first
        for header in ("Cf-Connecting-Ip", "X-Forwarded-For", "X-Real-Ip"):
            val = headers.get(header)
            if val:
                raw_ip = val.split(",")[0].strip()
                break
        if not raw_ip:
            raw_ip = headers.get("Host", "unknown")
        if raw_ip == "unknown":
            return "unknown"
        # Hash the IP so we can still deduplicate without storing real addresses
        return hashlib.sha256(raw_ip.encode()).hexdigest()[:16]
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
                cookies[key.strip()] = unquote(value.strip())
        return cookies
    except Exception:
        return {}
