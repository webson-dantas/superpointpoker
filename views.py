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

    # Keep session alive while anyone is viewing it
    import time as _time
    session["last_activity"] = _time.time()

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
            session["last_vote_time"] = session.get("last_vote_time", time.time()) - 300
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
    _inject_egg_click(session_id)
    col_info, col_link = st.columns([3, 2])
    with col_info:
        st.caption(f"Session ID: `{session_id}` • Your role: **{my_role}**")
    with col_link:
        if st.button("🔗 Copy session link", key="copy_link_btn"):
            pass  # JS handles the clipboard copy

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
        st.number_input("🐢 Max Turtles", min_value=1, max_value=500, step=1, key="max_turtles")

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

    # --- 3D Vote Cards ---
    ticket_label = session.get("ticket_label", "")
    if ticket_label:
        import re as _re
        jira_match = _re.search(r'[A-Z][A-Z0-9]+-\d+', ticket_label)
        jira_link = ""
        if jira_match:
            jira_key = jira_match.group(0)
            jira_url = f"https://hexagon-mining.atlassian.net/browse/{jira_key}"
            jira_link = f' <a href="{jira_url}" target="_blank" style="font-size:0.9rem;margin-left:0.8rem;vertical-align:middle;text-decoration:none;">🔗 View in Jira</a>'
        st.markdown(
            f'<div style="text-align:center;font-size:1.4rem;font-weight:600;margin-bottom:0.5rem;color:#ccc;">🎫 {html_mod.escape(ticket_label)}{jira_link}</div>',
            unsafe_allow_html=True,
        )
    # Calculate shame mode for cards (pending voters ≤ 30%)
    _voters = [p for p in session["participants"].values()
               if p["role"] in ("Dev", "QA", "PO") or (p["role"] == "Hoster" and hoster_votes)]
    _total = len(_voters)
    _pending = [p for p in _voters if p["vote"] is None]
    _pending_ratio = len(_pending) / _total if _total > 0 else 1.0
    _shame = 0 < _pending_ratio <= 0.3 and not session["votes_revealed"]

    card_parts = []
    for pid, pinfo in session["participants"].items():
        prole = pinfo['role']
        if prole == "Observer" or (prole == "Hoster" and not hoster_votes):
            continue
        esc_name = html_mod.escape(pinfo['name'])
        vote = pinfo['vote']
        has_voted = vote is not None
        if has_voted:
            vd = "☕" if vote == "null" else html_mod.escape(str(vote))
        else:
            vd = ""
        voted_cls = "" if has_voted else " spp-pending"
        flip_cls = " spp-card-flipped" if (has_voted and session["votes_revealed"]) else ""
        back_emoji = "🐢" if (_shame and not has_voted) else "❓"
        card_parts.append(
            f'<div class="spp-cw"><div class="spp-card{voted_cls}{flip_cls}" data-vote="{1 if has_voted else 0}">'
            f'<div class="spp-cf spp-cb">{back_emoji}</div>'
            f'<div class="spp-cf spp-cfr">{vd}</div>'
            f'</div><div class="spp-cn">{esc_name}</div></div>'
        )

    if card_parts:
        _CARD_CSS = """<style>
.spp-cards-row { display:flex; flex-wrap:wrap; gap:1.2rem; justify-content:center; margin:1.5rem 0; perspective:1200px; }
.spp-cw { text-align:center; }
.spp-card { width:90px; height:130px; position:relative; transform-style:preserve-3d; transition:transform 0.8s ease; margin:0 auto; }
.spp-card-flipped { transform:rotateY(180deg); }
.spp-cf { position:absolute; width:100%; height:100%; backface-visibility:hidden; -webkit-backface-visibility:hidden; border-radius:10px; display:flex; align-items:center; justify-content:center; font-weight:bold; box-shadow:0 4px 12px rgba(0,0,0,0.4); }
.spp-cb { background:repeating-linear-gradient(45deg,transparent,transparent 5px,rgba(255,255,255,0.04) 5px,rgba(255,255,255,0.04) 10px), linear-gradient(135deg,#667eea,#764ba2); color:#fff; font-size:1.8rem; }
.spp-cb::before { content:''; position:absolute; inset:8px; border:2px solid rgba(255,255,255,0.2); border-radius:6px; pointer-events:none; }
.spp-pending .spp-cb { background:linear-gradient(135deg,#3a3a5a,#2a2a4a); opacity:.7; }
.spp-pending .spp-cb::before { border-color:rgba(255,255,255,0.1); }
.spp-cfr { background:linear-gradient(145deg,#fafafa,#e0e0e0); color:#222; transform:rotateY(180deg); font-size:2rem; border:2px solid #bbb; }
.spp-card[data-vote="0"] .spp-cfr { background:repeating-linear-gradient(45deg,transparent,transparent 5px,rgba(255,255,255,0.04) 5px,rgba(255,255,255,0.04) 10px), linear-gradient(135deg,#667eea,#764ba2); color:#fff; font-size:1.8rem; border:none; }
.spp-card[data-vote="0"] .spp-cfr::before { content:'❓'; }
.spp-pending .spp-cfr { background:linear-gradient(135deg,#3a3a5a,#2a2a4a); opacity:.7; border:none; }
.spp-pending .spp-cfr::before { content:'❓'; }
.spp-cn { font-size:.8rem; margin-top:.5rem; max-width:100px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#aaa; }
@keyframes spp-green-flash { 0%{box-shadow:0 0 0 0 rgba(34,197,94,0.7)} 50%{box-shadow:0 0 20px 8px rgba(34,197,94,0.5)} 100%{box-shadow:0 0 0 0 rgba(34,197,94,0)} }
.spp-card-voted .spp-cb { animation:spp-green-flash 0.8s ease; border-radius:10px; }
</style>"""
        rev_attr = "true" if session["votes_revealed"] else "false"
        st.markdown(
            _CARD_CSS + f'\n<div class="spp-cards-row" data-revealed="{rev_attr}">{"".join(card_parts)}</div>',
            unsafe_allow_html=True,
        )
        _revealed_js = "true" if session["votes_revealed"] else "false"
        st.iframe(f"""<script>
(function() {{
    var d = window.parent.document;
    var isRev = {_revealed_js};
    setTimeout(function() {{
        var c = d.querySelector('.spp-cards-row');
        if (!c) return;
        var wasRev = d._sppCardsRevealed || false;
        var votedCards = c.querySelectorAll('.spp-card[data-vote="1"]');
        var allCards = c.querySelectorAll('.spp-card');
        // Track previously voted cards to detect new votes (green flash)
        var prev = d._sppVotedSet || {{}};
        var cur = {{}};
        allCards.forEach(function(el, i) {{
            var name = el.parentElement.querySelector('.spp-cn');
            var key = name ? name.textContent : i;
            if (el.dataset.vote === '1') {{
                cur[key] = true;
                if (!prev[key]) el.classList.add('spp-card-voted');
            }}
        }});
        d._sppVotedSet = cur;
        c.querySelectorAll('.spp-card-voted').forEach(function(el) {{
            el.addEventListener('animationend', function() {{ el.classList.remove('spp-card-voted'); }}, {{once:true}});
        }});
        if (isRev && !wasRev) {{
            // First reveal: cards already have spp-card-flipped from HTML.
            // Remove it instantly, then stagger-add for animation.
            votedCards.forEach(function(el) {{
                el.style.transition = 'none';
                el.classList.remove('spp-card-flipped');
            }});
            // Force reflow
            c.offsetHeight;
            votedCards.forEach(function(el) {{
                el.style.transition = '';
            }});
            votedCards.forEach(function(el, i) {{
                setTimeout(function() {{ el.classList.add('spp-card-flipped'); }}, i * 150);
            }});
            d._sppCardsRevealed = true;
        }} else if (isRev) {{
            // Already revealed (autorefresh): HTML already has spp-card-flipped, nothing to do
        }} else if (wasRev) {{
            // Just cleared: cards come without spp-card-flipped from HTML.
            // Add it instantly (so they appear still flipped), then stagger-remove for animation.
            allCards.forEach(function(el) {{
                el.style.transition = 'none';
                el.classList.add('spp-card-flipped');
            }});
            c.offsetHeight;
            allCards.forEach(function(el) {{
                el.style.transition = '';
            }});
            allCards.forEach(function(el, i) {{
                setTimeout(function() {{ el.classList.remove('spp-card-flipped'); }}, i * 150);
            }});
            d._sppCardsRevealed = false;
            d._sppVotedSet = {{}};
        }}
    }}, 50);
}})();
</script>""", height=1)

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

        # Inject CSS for larger vote buttons (via components.html to reach parent document)
        st.iframe("""
        <script>
        (function() {
            const doc = window.parent.document;
            // Inject style once
            if (!doc.getElementById('spp-vote-btn-style')) {
                const style = doc.createElement('style');
                style.id = 'spp-vote-btn-style';
                style.textContent = `
                    .spp-vote-row [data-testid="stColumn"] [data-testid="stButton"] > button {
                        font-size: 2rem !important;
                        padding: 1.5rem 2rem !important;
                        min-height: 5rem !important;
                        min-width: 5rem !important;
                        width: 100% !important;
                        line-height: 1 !important;
                    }
                    .spp-vote-row [data-testid="stColumn"] [data-testid="stButton"] > button p {
                        font-size: 2rem !important;
                        white-space: nowrap !important;
                    }
                `;
                doc.head.appendChild(style);
            }
            // Tag the vote button row by finding buttons with keys starting with "vote_"
            const allBtns = doc.querySelectorAll('button');
            for (const b of allBtns) {
                const key = b.closest('[data-testid="stButton"]');
                if (!key) continue;
                const wrapper = b.closest('[data-testid="stHorizontalBlock"]');
                if (wrapper && b.textContent.match(/^(\\d+|☕)$/)) {
                    wrapper.classList.add('spp-vote-row');
                }
            }
        })();
        </script>
        """, height=1)

        cols = st.columns(len(vote_options)) if vote_options else []
        for i, option in enumerate(vote_options):
            with cols[i]:
                label = "☕" if option == "Null Vote" else str(option)
                vote_val = "null" if option == "Null Vote" else option
                is_selected = my_info["vote"] == vote_val
                btn_type = "primary" if is_selected else "secondary"
                if st.button(label, key=f"vote_{i}_{option}", type=btn_type):
                    cast_vote(shared, session_id, user_id, vote_val)
                    st.session_state.custom_vote_input = None
                    st.rerun()

        # Custom vote input (numbers only) — applied in real time via on_change
        def _on_custom_vote():
            val = st.session_state.custom_vote_input
            if val is not None:
                cast_vote(shared, session_id, user_id, int(val))

        st.number_input("Custom Vote:", min_value=0, max_value=999, value=None, step=1, key="custom_vote_input", placeholder="Any number", on_change=_on_custom_vote)

        if my_info["vote"] is not None:
            display_vote = "Null Vote" if my_info["vote"] == "null" else my_info["vote"]
            st.success(f"Your vote: **{display_vote}**")
    elif my_role == "Hoster":
        st.info("👑 You are the Hoster — you manage the session but do not vote.")
    else:
        st.info("👀 You are an Observer — you cannot vote.")

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
    if idle_seconds > 300 and max_turtles > 0:
        turtle_count = min(int(idle_seconds // 300), max_turtles)
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

    # --- Usage Statistics ---
    total_sessions = len(shared["sessions"])
    total_users = sum(len(s["participants"]) for s in shared["sessions"].values())
    st.markdown(f"📊 **{total_sessions}** active session{'s' if total_sessions != 1 else ''} · **{total_users}** user{'s' if total_users != 1 else ''} online")

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
