import streamlit as st
import threading
import uuid
import sys
import logging
import time
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# Suppress harmless Windows ProactorEventLoop connection-reset noise
if sys.platform == "win32":
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# ---------------------------------------------------------------------------
# Shared State (singleton across all sessions in the same server process)
# ---------------------------------------------------------------------------

@st.cache_resource
def get_shared_state():
    return {
        "sessions": {},
        "lock": threading.Lock(),
        "heartbeat_lock": threading.Lock(),
        "last_cleanup_time": 0,
    }


FIBONACCI = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]


def closest_fibonacci(value):
    """Return the Fibonacci number closest to value. If equidistant, pick higher."""
    if value is None or value == 0:
        return None
    best = FIBONACCI[0]
    for f in FIBONACCI:
        if abs(f - value) < abs(best - value):
            best = f
        elif abs(f - value) == abs(best - value) and f > best:
            best = f
    return best


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def create_session(state, session_name, host_name, host_id):
    session_id = str(uuid.uuid4())[:8]
    with state["lock"]:
        state["sessions"][session_id] = {
            "name": session_name,
            "host_id": host_id,
            "participants": {
                host_id: {"name": host_name, "role": "Hoster", "vote": None, "heartbeat": time.time()}
            },
            "votes_revealed": False,
            "ticket_label": "",
            "separate_qa": False,
            "hoster_votes": False,
            "anyone_can_reveal": False,
            "block_vote_after_reveal": False,
            "host_heartbeat": time.time(),
            "last_vote_time": time.time(),
            "history": [],
            "created_at": datetime.now(),
        }
    return session_id


def join_session(state, session_id, user_id, user_name, role):
    with state["lock"]:
        if session_id in state["sessions"]:
            state["sessions"][session_id]["participants"][user_id] = {
                "name": user_name,
                "role": role,
                "vote": None,
                "heartbeat": time.time(),
            }
            return True
    return False


def cast_vote(state, session_id, user_id, vote_value):
    with state["lock"]:
        session = state["sessions"].get(session_id)
        if session and user_id in session["participants"]:
            # Block vote change after reveal if setting is enabled
            if session.get("block_vote_after_reveal", False) and session["votes_revealed"]:
                return
            session["participants"][user_id]["vote"] = vote_value
            session["last_vote_time"] = time.time()
            # Auto-reveal: check if all eligible voters have voted
            hoster_votes = session.get("hoster_votes", False)
            voting_roles = ("Dev", "QA")
            all_voted = all(
                p["vote"] is not None
                for p in session["participants"].values()
                if p["role"] in voting_roles or (p["role"] == "Hoster" and hoster_votes)
            )
            # Only auto-reveal if there's at least one voter
            has_voters = any(
                p["role"] in voting_roles or (p["role"] == "Hoster" and hoster_votes)
                for p in session["participants"].values()
            )
            all_voted = all_voted and has_voters
            if all_voted:
                session["votes_revealed"] = True


def reveal_votes(state, session_id):
    with state["lock"]:
        session = state["sessions"].get(session_id)
        if session:
            session["votes_revealed"] = True


def clear_votes(state, session_id):
    with state["lock"]:
        session = state["sessions"].get(session_id)
        if session:
            # Save current round to history before clearing
            label = session["ticket_label"] or "(No label)"
            votes = {}
            hoster_votes_on = session.get("hoster_votes", False)
            for p in session["participants"].values():
                is_voter = p["role"] in ("Dev", "QA") or (p["role"] == "Hoster" and hoster_votes_on)
                if is_voter and p["vote"] is not None:
                    vote_display = "Null" if p["vote"] == "null" else str(p["vote"])
                    votes[p["name"]] = vote_display
            if votes:  # Only save if at least one vote was cast
                separate_qa = session.get("separate_qa", False)
                dev_avg, qa_avg, combined, fib = calculate_averages(session, separate_qa)
                session["history"].append({
                    "label": label,
                    "votes": votes,
                    "dev_avg": dev_avg,
                    "qa_avg": qa_avg,
                    "combined": combined,
                    "fibonacci": fib,
                    "separate_qa": separate_qa,
                })
            # Clear current round
            session["votes_revealed"] = False
            session["ticket_label"] = ""
            session["last_vote_time"] = time.time()
            for p in session["participants"].values():
                p["vote"] = None


def calculate_averages(session, separate_qa=False):
    """Return (dev_avg, qa_avg, combined_avg, closest_fib) or Nones if no votes."""
    hoster_votes = session.get("hoster_votes", False)

    def is_voter(p):
        return p["role"] in ("Dev", "QA") or (p["role"] == "Hoster" and hoster_votes)

    if separate_qa:
        dev_votes = [
            p["vote"] for p in session["participants"].values()
            if (p["role"] == "Dev" or (p["role"] == "Hoster" and hoster_votes))
            and p["vote"] is not None and p["vote"] != "null"
        ]
        qa_votes = [
            p["vote"] for p in session["participants"].values()
            if p["role"] == "QA" and p["vote"] is not None and p["vote"] != "null"
        ]

        dev_avg = sum(dev_votes) / len(dev_votes) if dev_votes else None
        qa_avg = sum(qa_votes) / len(qa_votes) if qa_votes else None

        if dev_avg is not None and qa_avg is not None:
            combined = dev_avg + qa_avg
        elif dev_avg is not None:
            combined = dev_avg
        elif qa_avg is not None:
            combined = qa_avg
        else:
            combined = None

        fib = closest_fibonacci(combined) if combined else None
        return dev_avg, qa_avg, combined, fib
    else:
        # Single average: all eligible voters combined
        all_votes = [
            p["vote"] for p in session["participants"].values()
            if is_voter(p) and p["vote"] is not None and p["vote"] != "null"
        ]
        avg = sum(all_votes) / len(all_votes) if all_votes else None
        fib = closest_fibonacci(avg) if avg else None
        return avg, None, avg, fib


def leave_session(state, session_id, user_id):
    with state["lock"]:
        session = state["sessions"].get(session_id)
        if session and user_id in session["participants"]:
            del session["participants"][user_id]
            # If no participants left, remove session
            if not session["participants"]:
                del state["sessions"][session_id]


def close_session(state, session_id):
    with state["lock"]:
        if session_id in state["sessions"]:
            del state["sessions"][session_id]


def kick_participant(state, session_id, target_user_id):
    with state["lock"]:
        session = state["sessions"].get(session_id)
        if session and target_user_id in session["participants"]:
            del session["participants"][target_user_id]


def cleanup_stale_participants(state, session_id):
    """Remove participants who haven't sent a heartbeat in 60+ seconds (except host)."""
    now = time.time()
    with state["lock"]:
        session = state["sessions"].get(session_id)
        if not session:
            return
        host_id = session["host_id"]
        stale = [
            pid for pid, p in session["participants"].items()
            if pid != host_id and now - p.get("heartbeat", now) > 60
        ]
        for pid in stale:
            del session["participants"][pid]


def cleanup_stale_sessions(state):
    """Remove sessions where the hoster hasn't sent a heartbeat in 60+ seconds."""
    now = time.time()
    with state["lock"]:
        stale = [
            sid for sid, s in state["sessions"].items()
            if now - s.get("host_heartbeat", now) > 60
        ]
        for sid in stale:
            del state["sessions"][sid]


# ---------------------------------------------------------------------------
# Streamlit App
# ---------------------------------------------------------------------------

st.set_page_config(page_title="SuperPoint Poker", page_icon="🃏", layout="centered")

# Fixed-width centered layout
st.markdown("""
<style>
    .block-container {
        max-width: 1100px;
        padding-top: 2rem;
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

shared = get_shared_state()


# ---------------------------------------------------------------------------
# SESSION VIEW
# ---------------------------------------------------------------------------

def render_session_view():
    session_id = st.session_state.current_session
    session = shared["sessions"].get(session_id)

    if not session:
        st.error("Session no longer exists.")
        st.session_state.current_session = None
        st.rerun()
        return

    # Auto-refresh every 2 seconds (reduces server load with many users)
    st_autorefresh(interval=2000, key="session_refresh")

    # Throttled cleanup: only run every 10 seconds instead of every render
    now = time.time()
    if now - shared["last_cleanup_time"] > 10:
        shared["last_cleanup_time"] = now
        cleanup_stale_sessions(shared)
        cleanup_stale_participants(shared, session_id)

    user_id = st.session_state.user_id
    is_host = session["host_id"] == user_id
    my_info = session["participants"].get(user_id)

    if not my_info:
        st.error("You are no longer in this session.")
        st.session_state.current_session = None
        st.rerun()
        return

    # Heartbeat update (uses separate lock to avoid contention with votes/state)
    if is_host:
        with shared["heartbeat_lock"]:
            session["host_heartbeat"] = time.time()
            my_info["heartbeat"] = time.time()
    else:
        with shared["heartbeat_lock"]:
            my_info["heartbeat"] = time.time()

    my_role = my_info["role"]

    # Header
    st.title(f"🃏 {session['name']}")
    col_info, col_link = st.columns([3, 2])
    with col_info:
        st.caption(f"Session ID: `{session_id}` • Your role: **{my_role}**")
    with col_link:
        join_url = f"?session={session_id}"
        st.markdown(f'<a href="{join_url}" target="_blank">🔗 Link to this session</a>', unsafe_allow_html=True)

    # Leave / Close buttons
    if is_host:
        col_leave, col_close, _ = st.columns([1, 1, 4])
        with col_leave:
            if st.button("🚪 Leave"):
                leave_session(shared, session_id, user_id)
                st.session_state.current_session = None
                st.rerun()
        with col_close:
            if st.button("❌ Close"):
                close_session(shared, session_id)
                st.session_state.current_session = None
                st.rerun()
    else:
        col_leave, _ = st.columns([1, 5])
        with col_leave:
            if st.button("🚪 Leave"):
                leave_session(shared, session_id, user_id)
                st.session_state.current_session = None
                st.rerun()

    st.divider()

    # --- Host Controls ---
    if is_host:
        st.subheader("Host Controls")

        # Ticket label
        current_label = session.get("ticket_label", "")
        new_label = st.text_input("🎫 Current Ticket / Story", value=current_label, key="ticket_label_input", placeholder="e.g. JIRA-1234: User login flow")
        if new_label != current_label:
            with shared["lock"]:
                session["ticket_label"] = new_label

        col1, col2 = st.columns(2)
        with col1:
            if st.button("👁️ Reveal Votes", type="primary"):
                reveal_votes(shared, session_id)
                st.rerun()
        with col2:
            if st.button("🗑️ Clear Votes", type="secondary"):
                clear_votes(shared, session_id)
                st.rerun()

        # Session configuration (collapsible)
        with st.expander("⚙️ Session configuration", expanded=False):
            # Averaging mode toggle
            current_separate = session.get("separate_qa", False)
            separate = st.checkbox("Separate Dev & QA averages", value=current_separate, key="separate_qa_checkbox")
            if separate != current_separate:
                with shared["lock"]:
                    session["separate_qa"] = separate

            # Hoster votes toggle
            current_hoster_votes = session.get("hoster_votes", False)
            hoster_votes_toggle = st.checkbox("Hoster votes?", value=current_hoster_votes, key="hoster_votes_checkbox")
            if hoster_votes_toggle != current_hoster_votes:
                with shared["lock"]:
                    session["hoster_votes"] = hoster_votes_toggle
                    # Clear hoster vote if disabling
                    if not hoster_votes_toggle:
                        host_id = session["host_id"]
                        session["participants"][host_id]["vote"] = None

            # Anyone can reveal toggle
            current_anyone_reveal = session.get("anyone_can_reveal", False)
            anyone_reveal_toggle = st.checkbox("Anyone can reveal votes", value=current_anyone_reveal, key="anyone_reveal_checkbox")
            if anyone_reveal_toggle != current_anyone_reveal:
                with shared["lock"]:
                    session["anyone_can_reveal"] = anyone_reveal_toggle

            # Block vote change after reveal toggle
            current_block_vote = session.get("block_vote_after_reveal", False)
            block_vote_toggle = st.checkbox("Block vote change after reveal", value=current_block_vote, key="block_vote_checkbox")
            if block_vote_toggle != current_block_vote:
                with shared["lock"]:
                    session["block_vote_after_reveal"] = block_vote_toggle

        st.divider()

    # --- Reveal button for non-host if "anyone can reveal" is enabled ---
    if not is_host and session.get("anyone_can_reveal", False) and not session["votes_revealed"]:
        if st.button("👁️ Reveal Votes", key="anyone_reveal_btn", type="primary"):
            reveal_votes(shared, session_id)
            st.rerun()

    # --- Voting UI (Dev/QA only, or Hoster if hoster_votes enabled) ---
    hoster_votes = session.get("hoster_votes", False)
    can_vote = my_role in ("Dev", "QA") or (my_role == "Hoster" and hoster_votes)

    # Block voting UI if votes are revealed and block setting is on
    votes_blocked = session.get("block_vote_after_reveal", False) and session["votes_revealed"]

    if can_vote and votes_blocked:
        st.subheader("Cast Your Vote")
        st.warning("🔒 Voting is locked — votes have been revealed.")
    elif can_vote:
        st.subheader("Cast Your Vote")
        vote_options = [0, 1, 2, 3, 5, 8, 13, 21, "Null Vote"]
        cols = st.columns(len(vote_options))
        for i, option in enumerate(vote_options):
            with cols[i]:
                label = "☕" if option == "Null Vote" else str(option)
                vote_val = "null" if option == "Null Vote" else option
                is_selected = my_info["vote"] == vote_val
                btn_type = "primary" if is_selected else "secondary"
                if st.button(label, key=f"vote_{option}", type=btn_type):
                    cast_vote(shared, session_id, user_id, vote_val)
                    st.rerun()

        # Custom vote input (numbers only)
        custom_col1, custom_col2 = st.columns([2, 1])
        with custom_col1:
            custom_vote = st.number_input("Custom Vote:", min_value=0, max_value=999, value=None, step=1, key="custom_vote_input", placeholder="Any number")
        with custom_col2:
            st.write("")  # spacing
            st.write("")
            if st.button("Submit", key="custom_vote_btn"):
                if custom_vote is not None:
                    cast_vote(shared, session_id, user_id, int(custom_vote))
                    st.rerun()

        if my_info["vote"] is not None:
            display_vote = "Null Vote" if my_info["vote"] == "null" else my_info["vote"]
            st.success(f"Your vote: **{display_vote}**")
    elif my_role == "Hoster":
        st.info("👑 You are the Hoster — you manage the session but do not vote.")
    else:
        st.info("👀 You are an Observer — you cannot vote.")

    st.divider()

    # --- Participants & Votes + Averages side by side ---
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("Participants & Votes")

        # Show ticket label if set
        ticket_label = session.get("ticket_label", "")
        if ticket_label:
            st.info(f"🎫 **{ticket_label}**")

        votes_revealed = session["votes_revealed"]

        # Calculate pending percentage for the shame animation
        hoster_votes_enabled = session.get("hoster_votes", False)
        voters = [p for p in session["participants"].values()
                  if p["role"] in ("Dev", "QA") or (p["role"] == "Hoster" and hoster_votes_enabled)]
        total_voters = len(voters)
        pending_voters = [p for p in voters if p["vote"] is None]
        pending_count = len(pending_voters)
        pending_ratio = pending_count / total_voters if total_voters > 0 else 1.0
        shame_mode = 0 < pending_ratio <= 0.3 and not votes_revealed

        # Inject RGB animation CSS if shame mode active
        if shame_mode:
            st.markdown("""
            <style>
            @keyframes rgb-shame {
                0%   { color: #ff0000; text-shadow: 0 0 8px #ff0000; }
                16%  { color: #ff8800; text-shadow: 0 0 8px #ff8800; }
                33%  { color: #ffff00; text-shadow: 0 0 8px #ffff00; }
                50%  { color: #00ff00; text-shadow: 0 0 8px #00ff00; }
                66%  { color: #0088ff; text-shadow: 0 0 8px #0088ff; }
                83%  { color: #8800ff; text-shadow: 0 0 8px #8800ff; }
                100% { color: #ff0000; text-shadow: 0 0 8px #ff0000; }
            }
            .shame-highlight {
                animation: rgb-shame 1.5s linear infinite;
                font-weight: bold;
                font-size: 1.1em;
            }
            </style>
            """, unsafe_allow_html=True)

        for pid, pinfo in session["participants"].items():
            role_emoji = {"Dev": "💻", "QA": "🧪", "Observer": "👀", "Hoster": "👑"}.get(pinfo["role"], "")
            name_display = f"{role_emoji} {pinfo['name']} ({pinfo['role']})"

            is_non_voter = pinfo["role"] == "Observer" or (pinfo["role"] == "Hoster" and not hoster_votes_enabled)

            # Build vote status text
            if is_non_voter:
                status = f"*{pinfo['role']}*"
            elif pinfo["vote"] is None:
                if shame_mode:
                    if is_host and pid != user_id:
                        p_col1, p_col2 = st.columns([8, 1])
                        with p_col1:
                            st.markdown(f'<span class="shame-highlight">🐢 {name_display} — ⏳ Pending</span>', unsafe_allow_html=True)
                        with p_col2:
                            if st.button("👢", key=f"kick_{pid}", help=f"Kick {pinfo['name']}"):
                                kick_participant(shared, session_id, pid)
                                st.rerun()
                    else:
                        st.markdown(f'<span class="shame-highlight">🐢 {name_display} — ⏳ Pending</span>', unsafe_allow_html=True)
                    continue
                else:
                    status = "⏳ Pending"
            elif votes_revealed:
                vote_display = "Null Vote" if pinfo["vote"] == "null" else pinfo["vote"]
                status = f"✅ Voted **{vote_display}**"
            else:
                status = "✅ Voted"

            # Render participant line with optional kick button
            if is_host and pid != user_id:
                p_col1, p_col2 = st.columns([8, 1])
                with p_col1:
                    st.write(f"{name_display} — {status}")
                with p_col2:
                    if st.button("👢", key=f"kick_{pid}", help=f"Kick {pinfo['name']}"):
                        kick_participant(shared, session_id, pid)
                        st.rerun()
            else:
                st.write(f"{name_display} — {status}")

    with col_right:
        st.subheader("📊 Results")
        if votes_revealed:
            separate_qa = session.get("separate_qa", False)
            dev_avg, qa_avg, combined, fib = calculate_averages(session, separate_qa)

            if separate_qa:
                st.metric("Dev Average", f"{dev_avg:.1f}" if dev_avg is not None else "—")
                st.metric("QA Average", f"{qa_avg:.1f}" if qa_avg is not None else "—")
                st.metric("Sum of Averages", f"{combined:.1f}" if combined is not None else "—")
                st.metric("Closest Fibonacci", str(fib) if fib is not None else "—")
            else:
                st.metric("Overall Average", f"{combined:.1f}" if combined is not None else "—")
                st.metric("Closest Fibonacci", str(fib) if fib is not None else "—")
        else:
            st.info("Votes not revealed yet.")

    # --- History ---
    history = session.get("history", [])
    if history:
        st.divider()
        st.subheader("📜 Voting History")
        for i, entry in enumerate(reversed(history), 1):
            with st.expander(f"#{len(history) - i + 1} — {entry['label']}", expanded=False):
                # Votes
                for name, vote in entry["votes"].items():
                    st.write(f"• {name}: **{vote}**")
                # Averages
                cols = st.columns(4)
                with cols[0]:
                    st.write(f"Dev Avg: **{entry['dev_avg']:.1f}**" if entry['dev_avg'] is not None else "Dev Avg: —")
                with cols[1]:
                    st.write(f"QA Avg: **{entry['qa_avg']:.1f}**" if entry['qa_avg'] is not None else "QA Avg: —")
                with cols[2]:
                    st.write(f"Sum: **{entry['combined']:.1f}**" if entry['combined'] is not None else "Sum: —")
                with cols[3]:
                    st.write(f"Fibonacci: **{entry['fibonacci']}**" if entry['fibonacci'] is not None else "Fibonacci: —")

    # --- DVD Bouncing Turtle (appears after 5 min of inactivity) ---
    idle_seconds = time.time() - session.get("last_vote_time", time.time())
    if idle_seconds > 300:  # 5 minutes
        st.markdown("""
        <style>
        @keyframes dvd-bounce-x {
            0%   { left: 0%; }
            50%  { left: calc(100% - 60px); }
            100% { left: 0%; }
        }
        @keyframes dvd-bounce-y {
            0%   { top: 0%; }
            50%  { top: calc(100% - 60px); }
            100% { top: 0%; }
        }
        @keyframes dvd-color {
            0%   { filter: hue-rotate(0deg); }
            100% { filter: hue-rotate(360deg); }
        }
        .dvd-turtle {
            position: fixed;
            font-size: 50px;
            z-index: 9999;
            pointer-events: none;
            animation:
                dvd-bounce-x 7.3s linear infinite,
                dvd-bounce-y 5.1s linear infinite,
                dvd-color 4s linear infinite;
        }
        </style>
        <div class="dvd-turtle">🐢</div>
        """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# LOBBY VIEW
# ---------------------------------------------------------------------------

def render_lobby():
    st.title("🃏 SuperPoint Poker")
    st.caption("Planning Poker for agile teams - with love, by Webson <3")

    # Auto-refresh every 2 seconds
    st_autorefresh(interval=2000, key="lobby_refresh")

    # --- User Name ---
    st.subheader("Your Name")
    name = st.text_input(
        "Display name (emojis welcome! e.g. 🚀 Carlos)",
        value=st.session_state.user_name,
        key="name_input",
    )
    if name != st.session_state.user_name:
        st.session_state.user_name = name

    if not st.session_state.user_name.strip():
        st.warning("Please enter your name to continue.")
        return

    st.divider()

    # --- Join Existing Session ---
    st.subheader("Join an Existing Session")

    sessions = shared["sessions"]
    if not sessions:
        st.info("No active sessions yet.")
    else:
        role = st.selectbox("Your role", ["Dev", "QA", "Observer"], index=0)

        for sid, sdata in list(sessions.items()):
            participant_count = len(sdata["participants"])
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**{sdata['name']}** — {participant_count} participant(s)")
            with col2:
                if st.button("Join", key=f"join_{sid}"):
                    success = join_session(
                        shared, sid,
                        st.session_state.user_id,
                        st.session_state.user_name.strip(),
                        role,
                    )
                    if success:
                        st.session_state.current_session = sid
                        st.rerun()
                    else:
                        st.error("Failed to join session.")

    st.divider()

    # --- Create Session ---
    st.subheader("Create a New Session")
    session_name = st.text_input("Session name", placeholder="Sprint 42 Planning")
    if st.button("🎉 Create Session", type="primary"):
        if session_name.strip():
            sid = create_session(
                shared, session_name.strip(),
                st.session_state.user_name.strip(),
                st.session_state.user_id,
            )
            st.session_state.current_session = sid
            st.rerun()
        else:
            st.error("Please enter a session name.")


# ---------------------------------------------------------------------------
# JOIN VIA LINK VIEW
# ---------------------------------------------------------------------------

def render_join_via_link(session_id):
    session = shared["sessions"].get(session_id)
    if not session:
        st.error("This session no longer exists.")
        st.info("Redirecting to lobby...")
        st.query_params.clear()
        st.rerun()
        return

    st.title("🃏 SuperPoint Poker")
    st.subheader(f"Join session: **{session['name']}**")
    st.caption(f"Session ID: `{session_id}` • {len(session['participants'])} participant(s)")

    st.divider()

    name = st.text_input("Your display name (emojis welcome!)", value=st.session_state.user_name, key="join_link_name", placeholder="e.g. 🚀 Carlos")
    role = st.selectbox("Your role", ["Dev", "QA", "Observer"], index=0, key="join_link_role")

    if st.button("🎉 Join Session", type="primary"):
        if not name.strip():
            st.error("Please enter your name.")
        else:
            st.session_state.user_name = name.strip()
            success = join_session(
                shared, session_id,
                st.session_state.user_id,
                name.strip(),
                role,
            )
            if success:
                st.session_state.current_session = session_id
                st.query_params.clear()
                st.rerun()
            else:
                st.error("Failed to join session.")

    st.divider()
    if st.button("Go to Lobby instead"):
        st.query_params.clear()
        st.rerun()


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
