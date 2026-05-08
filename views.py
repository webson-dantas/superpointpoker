import time
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from config import get_shared_state, DEFAULT_VOTE_BUTTONS, get_client_ip
from logic import calculate_averages
from state import (
    cast_vote, reveal_votes, clear_votes,
    leave_session, close_session, kick_participant,
    join_session, create_session,
)
from components import (
    inject_localstorage_reader, inject_localstorage_writer,
    cleanup_turtles, inject_turtle_animation,
    clear_session_storage,
)


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

    user_id = st.session_state.user_id
    is_host = session["host_id"] == user_id
    my_info = session["participants"].get(user_id)

    if not my_info:
        # Auto-rejoin: user refreshed and got a new session state but was previously in this session
        # The IP-based dedup in join_session will merge with their old slot if possible
        if st.session_state.user_name.strip():
            join_session(
                shared, session_id,
                user_id,
                st.session_state.user_name.strip(),
                "Dev",  # default role on rejoin
                client_ip=get_client_ip(),
            )
            my_info = session["participants"].get(user_id)

    if not my_info:
        st.error("You are no longer in this session.")
        st.session_state.current_session = None
        clear_session_storage()
        st.rerun()
        return

    my_role = my_info["role"]

    # Persist state to cookies so F5 restores the session
    if st.session_state.user_name.strip():
        inject_localstorage_writer(st.session_state.user_name)

    # Header — clickable 🃏 advances idle timer by 2 min (spawns a turtle)
    # Hidden button triggered by clicking the emoji via JS
    if st.button("spawn_turtle", key="spawn_turtle_btn"):
        with shared["lock"]:
            session["last_vote_time"] = session.get("last_vote_time", time.time()) - 120
    import html as html_mod
    safe_name = html_mod.escape(session['name'])
    st.markdown(f"""
    <style>
    div[data-testid="stButton"]:has(button p:only-child) {{}}
    #spp-spawn-btn-wrap {{ display: none; }}
    </style>
    <h1 style="margin:0;padding:0;">
        <span id="spp-egg" style="cursor:default;user-select:none;">🃏</span> {safe_name}
    </h1>
    """, unsafe_allow_html=True)
    # Inject JS via components.html so it runs in parent context
    from components import _inject_egg_click
    _inject_egg_click()
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
                clear_session_storage()
                st.rerun()
        with col_close:
            if st.button("❌ Close"):
                close_session(shared, session_id)
                st.session_state.current_session = None
                clear_session_storage()
                st.rerun()
    else:
        col_leave, _ = st.columns([1, 5])
        with col_leave:
            if st.button("🚪 Leave"):
                leave_session(shared, session_id, user_id)
                st.session_state.current_session = None
                clear_session_storage()
                st.rerun()

    # --- Session configuration (visible to all, host-only options gated) ---
    with st.expander("⚙️ Session configuration", expanded=False):
        # Role picker (all users)
        available_roles = ["Dev", "QA", "PO", "Observer"]
        if is_host:
            available_roles = ["Hoster"] + available_roles
        current_index = available_roles.index(my_role) if my_role in available_roles else 0
        col_role, _ = st.columns([2, 4])
        with col_role:
            new_role = st.selectbox("Your role", available_roles, index=current_index, key="role_picker")
        if new_role != my_role:
            with shared["lock"]:
                session["participants"][user_id]["role"] = new_role
                # Clear vote if switching to a non-voting role
                if new_role == "Observer":
                    session["participants"][user_id]["vote"] = None
            st.rerun()

        # Max turtles (per-user preference)
        if "max_turtles" not in st.session_state:
            st.session_state.max_turtles = 5
        st.number_input("🐢 Max Turtles", min_value=0, max_value=500, step=1, key="max_turtles")

        # Host-only configuration options
        if is_host:
            st.markdown("---")

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

            # Vote buttons customization
            st.markdown("---")
            st.markdown("**Vote buttons** (semicolon-separated, use `X` for null/coffee vote)")
            current_buttons = session.get("vote_buttons", DEFAULT_VOTE_BUTTONS)
            # Use a version counter to force widget reset on revert
            vb_version = st.session_state.get("_vb_version", 0)
            btn_col1, btn_col2 = st.columns([4, 1])
            with btn_col1:
                new_buttons = st.text_input("Vote options", value=current_buttons, key=f"vote_buttons_input_{vb_version}", label_visibility="collapsed")
            with btn_col2:
                if st.button("↩️ Default", key="revert_vote_buttons"):
                    with shared["lock"]:
                        session["vote_buttons"] = DEFAULT_VOTE_BUTTONS
                    st.session_state._vb_version = vb_version + 1
                    st.rerun()
            if new_buttons != current_buttons:
                with shared["lock"]:
                    session["vote_buttons"] = new_buttons

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

        st.divider()

    # --- Reveal button for non-host if "anyone can reveal" is enabled ---
    if not is_host and session.get("anyone_can_reveal", False) and not session["votes_revealed"]:
        if st.button("👁️ Reveal Votes", key="anyone_reveal_btn", type="primary"):
            reveal_votes(shared, session_id)
            st.rerun()

    # --- Voting UI (Dev/QA only, or Hoster if hoster_votes enabled) ---
    hoster_votes = session.get("hoster_votes", False)
    can_vote = my_role in ("Dev", "QA", "PO") or (my_role == "Hoster" and hoster_votes)

    # Block voting UI if votes are revealed and block setting is on
    votes_blocked = session.get("block_vote_after_reveal", False) and session["votes_revealed"]

    if can_vote and votes_blocked:
        st.subheader("Cast Your Vote")
        st.warning("🔒 Voting is locked — votes have been revealed.")
    elif can_vote:
        st.subheader("Cast Your Vote")
        # Parse vote buttons from session config
        button_str = session.get("vote_buttons", DEFAULT_VOTE_BUTTONS)
        raw_options = [s.strip() for s in button_str.split(";") if s.strip()]
        vote_options = []
        for opt in raw_options:
            if opt.upper() == "X":
                vote_options.append("Null Vote")
            else:
                try:
                    vote_options.append(int(opt))
                except ValueError:
                    try:
                        vote_options.append(float(opt))
                    except ValueError:
                        pass  # skip invalid entries

        cols = st.columns(len(vote_options)) if vote_options else []
        for i, option in enumerate(vote_options):
            with cols[i]:
                label = "☕" if option == "Null Vote" else str(option)
                vote_val = "null" if option == "Null Vote" else option
                is_selected = my_info["vote"] == vote_val
                btn_type = "primary" if is_selected else "secondary"
                if st.button(label, key=f"vote_{i}_{option}", type=btn_type):
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
                  if p["role"] in ("Dev", "QA", "PO") or (p["role"] == "Hoster" and hoster_votes_enabled)]
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
            role_emoji = {"Dev": "💻", "QA": "🧪", "PO": "📊", "Observer": "👀", "Hoster": "👑"}.get(pinfo["role"], "")
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

    # --- DVD Bouncing Turtle (appears after 2 min of inactivity, multiplies every 2 min up to max) ---
    max_turtles = st.session_state.get("max_turtles", 5)
    idle_seconds = time.time() - session.get("last_vote_time", time.time())
    if idle_seconds > 120 and max_turtles > 0:
        turtle_count = min(int(idle_seconds // 120), max_turtles)
        inject_turtle_animation(turtle_count)
    else:
        cleanup_turtles()


# ---------------------------------------------------------------------------
# LOBBY VIEW
# ---------------------------------------------------------------------------

def render_lobby():
    # Clean up any leftover turtles from session view
    cleanup_turtles()

    st.title("🃏 Super Point Poker")
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

    # Save state to cookies whenever name is set
    if st.session_state.user_name.strip():
        inject_localstorage_writer(st.session_state.user_name)

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
        role = st.selectbox("Your role", ["Dev", "QA", "PO", "Observer"], index=0)

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
                        client_ip=get_client_ip(),
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
                client_ip=get_client_ip(),
            )
            st.session_state.current_session = sid
            st.rerun()
        else:
            st.error("Please enter a session name.")


# ---------------------------------------------------------------------------
# JOIN VIA LINK VIEW
# ---------------------------------------------------------------------------

def render_join_via_link(session_id):
    # Clean up any leftover turtles
    cleanup_turtles()

    session = shared["sessions"].get(session_id)
    if not session:
        st.error("This session no longer exists.")
        st.info("Redirecting to lobby...")
        st.query_params.clear()
        st.rerun()
        return

    st.title("🃏 Super Point Poker")
    st.subheader(f"Join session: **{session['name']}**")
    st.caption(f"Session ID: `{session_id}` • {len(session['participants'])} participant(s)")

    st.divider()

    name = st.text_input("Your display name (emojis welcome!)", value=st.session_state.user_name, key="join_link_name", placeholder="e.g. 🚀 Carlos")
    role = st.selectbox("Your role", ["Dev", "QA", "PO", "Observer"], index=0, key="join_link_role")

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
                client_ip=get_client_ip(),
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
