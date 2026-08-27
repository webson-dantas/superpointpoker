import time
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from config import (
    get_shared_state, DEFAULT_VOTE_BUTTONS, get_client_ip,
    MAX_USERNAME_LENGTH, MAX_SESSION_NAME_LENGTH, MAX_TICKET_LABEL_LENGTH,
    MAX_VOTE_BUTTONS_LENGTH, MAX_PARTICIPANTS_PER_SESSION, MAX_SESSIONS_PER_USER,
    VOTE_MODE_POINTS, VOTE_MODE_HOURS,
)
from logic import calculate_averages, calculate_hours
from state import (
    cast_vote, reveal_votes, clear_votes, set_voting_mode,
    leave_session, close_session, kick_participant,
    join_session, create_session,
)
from components import (
    inject_localstorage_reader, inject_localstorage_writer,
    cleanup_turtles, inject_turtle_animation,
    clear_session_storage,
)


shared = get_shared_state()


def _render_hours_range_chart(session):
    """Horizontal MIN-MAX range bars per voter with the average band highlighted."""
    import html as _h
    hoster_votes = session.get("hoster_votes", False)

    def is_voter(p):
        return p["role"] in ("Dev", "QA", "PO") or (p["role"] == "Hoster" and hoster_votes)

    role_emoji = {"Dev": "💻", "QA": "🧪", "PO": "📊", "Observer": "👀", "Hoster": "👑"}

    rows = [(f"{role_emoji.get(p['role'], '')} {p['name']}".strip(), p["vote"]["min"], p["vote"]["max"])
            for p in session["participants"].values()
            if is_voter(p) and isinstance(p["vote"], dict)]
    if not rows:
        return

    avg_min, avg_max, min_low, max_high, _ = calculate_hours(session)
    domain = (max_high * 1.05) or 1  # small right padding so the last label fits
    band_left = avg_min / domain * 100
    band_width = max((avg_max - avg_min) / domain * 100, 0.4)

    row_html = []
    for name, vmin, vmax in rows:
        left = vmin / domain * 100
        width = max((vmax - vmin) / domain * 100, 0.6)
        esc = _h.escape(name)
        # Bar tinted toward the extremes it owns (blue=lowest MIN, red=highest MAX).
        min_cls = " spp-rc-lowest" if vmin == min_low else ""
        max_cls = " spp-rc-highest" if vmax == max_high else ""
        row_html.append(
            f'<div class="spp-rc-row"><div class="spp-rc-name">{esc}</div>'
            f'<div class="spp-rc-track">'
            f'<div class="spp-rc-avg" style="left:{band_left:.2f}%;width:{band_width:.2f}%;"></div>'
            f'<div class="spp-rc-bar" style="left:{left:.2f}%;width:{width:.2f}%;"></div>'
            f'<div class="spp-rc-lbl spp-rc-min{min_cls}" style="left:{left:.2f}%;">{vmin}h</div>'
            f'<div class="spp-rc-lbl spp-rc-max{max_cls}" style="left:{(left + width):.2f}%;">{vmax}h</div>'
            f'</div></div>'
        )

    # Prominent summary bar for the average MIN-MAX range.
    summary = (
        f'<div class="spp-rc-row spp-rc-srow"><div class="spp-rc-name spp-rc-sname">AVERAGE</div>'
        f'<div class="spp-rc-track spp-rc-strack">'
        f'<div class="spp-rc-sbar" style="left:{band_left:.2f}%;width:{band_width:.2f}%;"></div>'
        f'<div class="spp-rc-lbl spp-rc-slbl spp-rc-min" style="left:{band_left:.2f}%;">{avg_min:.1f}h</div>'
        f'<div class="spp-rc-lbl spp-rc-slbl spp-rc-max" style="left:{(band_left + band_width):.2f}%;">{avg_max:.1f}h</div>'
        f'</div></div>'
    )

    # Box plot + dot strip over all endpoint values (mins + maxs pooled).
    mins = [r[1] for r in rows]
    maxs = [r[2] for r in rows]
    pool = sorted(mins + maxs)

    def _pct(sv, q):
        if len(sv) == 1:
            return sv[0]
        pos = (len(sv) - 1) * q
        i = int(pos)
        frac = pos - i
        return sv[i] + (sv[i + 1] - sv[i]) * frac if i + 1 < len(sv) else sv[i]

    q1, med, q3 = _pct(pool, 0.25), _pct(pool, 0.5), _pct(pool, 0.75)
    lo, hi = pool[0], pool[-1]

    def _p(v):
        return v / domain * 100

    dots = []
    for j, (val, kind) in enumerate([(m, "min") for m in mins] + [(x, "max") for x in maxs]):
        jit = ((j * 37) % 13) - 6  # vertical jitter so overlapping points stay visible
        dots.append(f'<div class="spp-bp-dot spp-bp-dot-{kind}" style="left:{_p(val):.2f}%;top:{60 + jit}px;"></div>')

    qlabels = (
        f'<div class="spp-bp-qlbl" style="left:{_p(q1):.2f}%;">Q1 {q1:g}h</div>'
        f'<div class="spp-bp-qlbl" style="left:{_p(med):.2f}%;">Q2 {med:g}h</div>'
        f'<div class="spp-bp-qlbl" style="left:{_p(q3):.2f}%;">Q3 {q3:g}h</div>'
    )

    boxplot = (
        f'<div class="spp-rc-row spp-bp-topgap"><div class="spp-rc-name">SPREAD</div>'
        f'<div class="spp-bp-track">'
        f'{qlabels}'
        f'<div class="spp-bp-whisker" style="left:{_p(lo):.2f}%;width:{(_p(hi) - _p(lo)):.2f}%;"></div>'
        f'<div class="spp-bp-cap" style="left:{_p(lo):.2f}%;"></div>'
        f'<div class="spp-bp-cap" style="left:{_p(hi):.2f}%;"></div>'
        f'<div class="spp-bp-box" style="left:{_p(q1):.2f}%;width:{(_p(q3) - _p(q1)):.2f}%;"></div>'
        f'<div class="spp-bp-median" style="left:{_p(med):.2f}%;"></div>'
        f'{"".join(dots)}'
        f'</div></div>'
    )

    try:
        _theme = getattr(st.context, "theme", None)
        _is_dark = (getattr(_theme, "type", None) or st.get_option("theme.base") or "dark") != "light"
    except Exception:
        _is_dark = True
    if _is_dark:
        wrap_style = "--rc-txt:#e5e7eb;--rc-muted:#bbb;--rc-track:transparent;--rc-strack:transparent;--rc-border:rgba(255,255,255,0.08);--rc-q:#cbd5e1;--rc-median:#fff;"
    else:
        wrap_style = "--rc-txt:#1f2937;--rc-muted:#555;--rc-track:transparent;--rc-strack:transparent;--rc-border:rgba(0,0,0,0.14);--rc-q:#374151;--rc-median:#4c1d95;"

    css = """<style>
.spp-rc-wrap { margin:0.25rem 0 0.5rem; }
.spp-rc-row { display:flex; align-items:center; margin:7px 0; }
.spp-rc-name { flex:0 0 108px; width:108px; font-size:0.8rem; color:var(--rc-muted); text-align:right; padding-right:10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.spp-rc-track { position:relative; flex:1; height:26px; background:var(--rc-track); border-radius:6px; overflow:visible; }
.spp-rc-avg { position:absolute; top:0; bottom:0; background:rgba(148,163,184,0.16); border-left:1px dashed rgba(148,163,184,0.55); border-right:1px dashed rgba(148,163,184,0.55); }
.spp-rc-bar { position:absolute; top:6px; height:14px; border-radius:7px; background:linear-gradient(90deg,#60a5fa,#f87171); box-shadow:0 1px 4px rgba(0,0,0,0.35); }
.spp-rc-lbl { position:absolute; top:3px; font-size:0.95rem; font-weight:700; color:var(--rc-txt); white-space:nowrap; pointer-events:none; }
.spp-rc-min { transform:translateX(-100%); padding-right:7px; }
.spp-rc-max { transform:translateX(0); padding-left:7px; }
.spp-rc-lowest { color:#3b82f6; }
.spp-rc-highest { color:#ef4444; }
.spp-rc-axis { flex:1; display:flex; justify-content:space-between; font-size:0.72rem; color:#888; }
.spp-rc-srow { margin-bottom:12px; padding-bottom:10px; border-bottom:1px solid var(--rc-border); }
.spp-rc-sname { color:var(--rc-txt); font-weight:800; font-size:0.85rem; }
.spp-rc-strack { height:38px; background:var(--rc-strack); border-radius:8px; }
.spp-rc-sbar { position:absolute; top:7px; height:24px; border-radius:9px; background:linear-gradient(90deg,#3b82f6,#8b5cf6,#ef4444); box-shadow:0 0 14px 2px rgba(139,92,246,0.6); border:1px solid rgba(255,255,255,0.25); }
.spp-rc-slbl { top:9px; font-size:1.05rem; font-weight:800; color:#fff; text-shadow:0 1px 3px rgba(0,0,0,0.6); }
.spp-bp-topgap { margin-top:12px; padding-top:12px; border-top:1px solid var(--rc-border); }
.spp-bp-track { position:relative; flex:1; height:76px; background:var(--rc-track); border-radius:6px; }
.spp-bp-qlbl { position:absolute; top:0; transform:translateX(-50%); font-size:0.88rem; font-weight:800; color:var(--rc-q); white-space:nowrap; pointer-events:none; }
.spp-bp-whisker { position:absolute; top:32px; height:2px; background:#9aa4b2; }
.spp-bp-cap { position:absolute; top:25px; height:16px; width:2px; margin-left:-1px; background:#9aa4b2; }
.spp-bp-box { position:absolute; top:20px; height:26px; background:rgba(139,92,246,0.28); border:1.5px solid #8b5cf6; border-radius:4px; }
.spp-bp-median { position:absolute; top:20px; height:26px; width:3px; margin-left:-1.5px; background:var(--rc-median); border-radius:2px; }
.spp-bp-dot { position:absolute; width:9px; height:9px; border-radius:50%; transform:translate(-50%,-50%); box-shadow:0 0 0 1px rgba(0,0,0,0.35); }
.spp-bp-dot-min { background:#3b82f6; }
.spp-bp-dot-max { background:#ef4444; }
</style>"""
    st.markdown(css + f'<div class="spp-rc-wrap" style="{wrap_style}">{summary}{"".join(row_html)}{boxplot}</div>', unsafe_allow_html=True)


def _render_participants_and_results(session, session_id, user_id, is_host):
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
                if pinfo["vote"] == "null":
                    vote_display = "☕"
                elif isinstance(pinfo["vote"], dict):
                    vote_display = f"{pinfo['vote']['min']}–{pinfo['vote']['max']} h"
                else:
                    vote_display = pinfo["vote"]
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


def _render_welcome(code):
    """First-join welcome: highlight the rejoin code, auto-advance after 3s or Skip."""
    import html as _h
    if "welcome_start" not in st.session_state:
        st.session_state.welcome_start = time.time()
    st_autorefresh(interval=1000, key="welcome_refresh")
    elapsed = time.time() - st.session_state.welcome_start

    st.markdown(
        f'''<div style="text-align:center;padding:2.2rem 1rem 1rem;">
        <div style="font-size:2rem;font-weight:800;margin-bottom:0.4rem;">🎉 You're in!</div>
        <div style="color:#999;max-width:520px;margin:0 auto 1.3rem;">Save your <b>Rejoin Code</b> — type it on the join screen to reclaim your seat (and your vote) if the tab closes or refreshes.</div>
        <div style="display:inline-block;font-size:2.4rem;font-weight:800;letter-spacing:1px;padding:0.8rem 1.8rem;border-radius:14px;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#ef4444);color:#fff;box-shadow:0 6px 22px rgba(139,92,246,0.5);">{_h.escape(code)}</div>
        </div>''',
        unsafe_allow_html=True,
    )
    st.code(code, language=None)  # native copy button

    remaining = max(0, 3 - int(elapsed))
    _c1, _c2, _c3 = st.columns([2, 1, 2])
    with _c2:
        label = "Continue →" if remaining == 0 else f"Skip ({remaining}s)"
        if st.button(label, type="primary", use_container_width=True) or elapsed >= 3:
            st.session_state.show_welcome = False
            st.session_state.pop("welcome_start", None)
            st.rerun()


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

    # Keep session alive while anyone is viewing it (throttled to every 5 min)
    import time as _time
    _now = _time.time()
    if _now - session.get("last_activity", 0) > 300:
        session["last_activity"] = _now

    # Auto-refresh every 2 seconds (reduces server load with many users)
    st_autorefresh(interval=2000, key="session_refresh")

    user_id = st.session_state.user_id
    is_host = session["host_id"] == user_id
    my_info = session["participants"].get(user_id)

    if not my_info:
        # Auto-rejoin: try URL rejoin code first, then name/IP dedup fallback.
        _rc = st.query_params.get("rc")
        if _rc or st.session_state.user_name.strip():
            join_session(
                shared, session_id,
                user_id,
                st.session_state.user_name.strip() or "Guest",
                "Dev",  # default role on rejoin
                client_ip=get_client_ip(),
                rejoin_code=_rc,
            )
            my_info = session["participants"].get(user_id)

    if not my_info:
        st.error("You are no longer in this session.")
        st.session_state.current_session = None
        clear_session_storage()
        st.rerun()
        return

    my_role = my_info["role"]

    # First-join welcome: show the rejoin code prominently, then auto-advance.
    if st.session_state.get("show_welcome"):
        _render_welcome(st.session_state.get("welcome_code", my_info.get("rejoin_code", "")))
        return

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
        _mycode = my_info.get("rejoin_code", "")
        _show_rc = st.session_state.get("show_rc", False)
        _code_disp = _mycode if _show_rc else "••••••"
        st.caption(f"Session ID: `{session_id}` • Your role: **{my_role}** • Rejoin code: `{_code_disp}`")
        if st.button("🙈 Hide code" if _show_rc else "👁️ Reveal my rejoin code", key="toggle_rc"):
            st.session_state.show_rc = not _show_rc
            st.rerun()
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
                st.query_params.clear()
                st.rerun()
        with col_close:
            if st.button("❌ Close"):
                close_session(shared, session_id)
                st.session_state.current_session = None
                clear_session_storage()
                st.query_params.clear()
                st.rerun()
    else:
        col_leave, _ = st.columns([1, 5])
        with col_leave:
            if st.button("🚪 Leave"):
                leave_session(shared, session_id, user_id)
                st.session_state.current_session = None
                clear_session_storage()
                st.query_params.clear()
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

            # Voting mode selector
            current_mode = session.get("voting_mode", VOTE_MODE_POINTS)
            mode_labels = {VOTE_MODE_POINTS: "🃏 Story Points", VOTE_MODE_HOURS: "⏱️ Min/Max Hours"}
            mode_options = [VOTE_MODE_POINTS, VOTE_MODE_HOURS]
            chosen_mode = st.radio(
                "Voting Mode",
                mode_options,
                index=mode_options.index(current_mode) if current_mode in mode_options else 0,
                format_func=lambda m: mode_labels[m],
                key="voting_mode_radio",
                horizontal=True,
            )
            if chosen_mode != current_mode:
                set_voting_mode(shared, session_id, chosen_mode)
                st.rerun()

            is_hours_mode = current_mode == VOTE_MODE_HOURS

            # Averaging mode toggle (points mode only)
            if not is_hours_mode:
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

            # Vote buttons customization (points mode only)
            if not is_hours_mode:
                st.markdown("---")
                st.markdown("**Vote buttons** (semicolon-separated, use `X` for null/coffee vote)")
                current_buttons = session.get("vote_buttons", DEFAULT_VOTE_BUTTONS)
                # Use a version counter to force widget reset on revert
                vb_version = st.session_state.get("_vb_version", 0)
                btn_col1, btn_col2 = st.columns([4, 1])
                with btn_col1:
                    new_buttons = st.text_input("Vote options", value=current_buttons, key=f"vote_buttons_input_{vb_version}", label_visibility="collapsed", max_chars=MAX_VOTE_BUTTONS_LENGTH)
                with btn_col2:
                    if st.button("↩️ Default", key="revert_vote_buttons"):
                        with shared["lock"]:
                            session["vote_buttons"] = DEFAULT_VOTE_BUTTONS
                        st.session_state._vb_version = vb_version + 1
                        st.rerun()
                if new_buttons != current_buttons:
                    with shared["lock"]:
                        session["vote_buttons"] = new_buttons[:MAX_VOTE_BUTTONS_LENGTH]

    # --- Host Controls ---
    if is_host:
        st.subheader("Host Controls")

        # Ticket label
        current_label = session.get("ticket_label", "")
        new_label = st.text_input("🎫 Current Ticket / Story", value=current_label, key="ticket_label_input", placeholder="e.g. JIRA-1234: User login flow", max_chars=MAX_TICKET_LABEL_LENGTH)
        if new_label != current_label:
            with shared["lock"]:
                session["ticket_label"] = new_label[:MAX_TICKET_LABEL_LENGTH]

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

    # Attention highlight extremes (only after reveal): blue = lowest, red = highest.
    voting_mode = session.get("voting_mode", VOTE_MODE_POINTS)
    _hl_lo = _hl_hi = None  # points: lowest/highest numeric vote
    _hl_min = _hl_max = None  # hours: lowest MIN / highest MAX
    if session["votes_revealed"]:
        if voting_mode == VOTE_MODE_HOURS:
            _, _, _hl_min, _hl_max, _ = calculate_hours(session)
        else:
            _nums = [p["vote"] for p in _voters
                     if isinstance(p["vote"], (int, float)) and not isinstance(p["vote"], bool)]
            if _nums and min(_nums) != max(_nums):
                _hl_lo, _hl_hi = min(_nums), max(_nums)

    card_parts = []
    for pid, pinfo in session["participants"].items():
        prole = pinfo['role']
        if prole == "Observer" or (prole == "Hoster" and not hoster_votes):
            continue
        esc_name = html_mod.escape(pinfo['name'])
        vote = pinfo['vote']
        has_voted = vote is not None
        if has_voted:
            if vote == "null":
                vd = "☕"
            elif isinstance(vote, dict):
                vd = f"{html_mod.escape(str(vote['min']))}h<br>{html_mod.escape(str(vote['max']))}h"
            else:
                vd = html_mod.escape(str(vote))
        else:
            vd = ""
        voted_cls = "" if has_voted else " spp-pending"
        flip_cls = " spp-card-flipped" if (has_voted and session["votes_revealed"]) else ""
        # Attention highlight classes (revealed only)
        hl_cls = ""
        if session["votes_revealed"] and has_voted:
            if voting_mode == VOTE_MODE_HOURS and isinstance(vote, dict):
                if _hl_min is not None and vote["min"] == _hl_min:
                    hl_cls += " spp-min"
                if _hl_max is not None and vote["max"] == _hl_max:
                    hl_cls += " spp-max"
            elif voting_mode == VOTE_MODE_POINTS and isinstance(vote, (int, float)) and not isinstance(vote, bool):
                if _hl_lo is not None and vote == _hl_lo:
                    hl_cls += " spp-min"
                if _hl_hi is not None and vote == _hl_hi:
                    hl_cls += " spp-max"
        back_emoji = "🐢" if (_shame and not has_voted) else "❓"
        card_parts.append(
            f'<div class="spp-cw"><div class="spp-card{voted_cls}{flip_cls}{hl_cls}" data-vote="{1 if has_voted else 0}">'
            f'<div class="spp-cf spp-cb">{back_emoji}</div>'
            f'<div class="spp-cf spp-cfr">{vd}</div>'
            f'</div><div class="spp-cn">{esc_name}</div></div>'
        )

    # Average card (hours mode): always visible, face-down until reveal.
    if voting_mode == VOTE_MODE_HOURS:
        _amin, _amax, _aml, _amh, _acnt = calculate_hours(session)
        _rev = session["votes_revealed"]
        _aflip = " spp-card-flipped" if _rev else ""
        _adv = 1 if _rev else 0
        _afront = f"{round(_amin, 1):g}h<br>{round(_amax, 1):g}h" if _acnt else "—"
        card_parts.append(
            f'<div class="spp-cw spp-cw-avg"><div class="spp-card spp-avg{_aflip}" data-vote="{_adv}">'
            f'<div class="spp-cf spp-cb">∑</div>'
            f'<div class="spp-cf spp-cfr">{_afront}</div>'
            f'</div><div class="spp-cn">Average</div></div>'
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
.spp-min .spp-cfr { border-color:#60a5fa; box-shadow:0 0 14px 3px rgba(96,165,250,0.65); }
.spp-max .spp-cfr { border-color:#f87171; box-shadow:0 0 14px 3px rgba(248,113,113,0.65); }
.spp-min.spp-max .spp-cfr { border-color:#c084fc; box-shadow:0 0 14px 3px rgba(96,165,250,0.6),0 0 14px 3px rgba(248,113,113,0.6); }
.spp-cn { font-size:.8rem; margin-top:.5rem; max-width:100px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#aaa; }
.spp-cw-avg { margin-left:2.4rem; position:relative; }
.spp-cw-avg::before { content:''; position:absolute; left:-1.2rem; top:8%; height:84%; width:2px; background:rgba(150,150,150,0.35); border-radius:1px; }
.spp-avg .spp-cb { background:linear-gradient(135deg,#3b82f6,#8b5cf6,#ef4444); color:#fff; font-size:2rem; }
.spp-avg .spp-cfr { background:linear-gradient(135deg,#3b82f6,#8b5cf6,#ef4444); color:#fff; border:none; font-size:1.45rem; line-height:1.2; text-shadow:0 1px 2px rgba(0,0,0,0.4); }
.spp-avg .spp-cfr::before { content:none !important; }
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
    elif can_vote and session.get("voting_mode", VOTE_MODE_POINTS) == VOTE_MODE_HOURS:
        st.subheader("Cast Your Vote")
        st.caption("Estimate the effort range in hours.")
        # MIN/MAX boxes + Submit/Coffee on one centered row; number steppers hidden.
        st.markdown("""<style>
div[data-testid="stHorizontalBlock"]:has(input[aria-label="MIN hours"]) {
    justify-content:center !important; align-items:flex-end !important; gap:1rem !important; flex-wrap:nowrap !important;
}
div[data-testid="stHorizontalBlock"]:has(input[aria-label="MIN hours"]) > div[data-testid="stColumn"] {
    width:auto !important; flex:0 0 auto !important; min-width:0 !important;
}
div[data-testid="stNumberInput"]:has(input[aria-label="MIN hours"]),
div[data-testid="stNumberInput"]:has(input[aria-label="MAX hours"]) { width:130px !important; }
div[data-testid="stNumberInput"]:has(input[aria-label="MIN hours"]) [data-baseweb="input"],
div[data-testid="stNumberInput"]:has(input[aria-label="MAX hours"]) [data-baseweb="input"] { height:120px !important; }
div[data-testid="stNumberInput"]:has(input[aria-label="MIN hours"]) input,
div[data-testid="stNumberInput"]:has(input[aria-label="MAX hours"]) input {
    height:120px !important; font-size:2.6rem !important; text-align:center !important; font-weight:700 !important; padding:0 !important;
}
div[data-testid="stNumberInput"]:has(input[aria-label="MIN hours"]) button,
div[data-testid="stNumberInput"]:has(input[aria-label="MAX hours"]) button { display:none !important; }
</style>""", unsafe_allow_html=True)
        cur_vote = my_info["vote"]
        cur_min = cur_vote["min"] if isinstance(cur_vote, dict) else None
        cur_max = cur_vote["max"] if isinstance(cur_vote, dict) else None
        c_min, c_max, c_sub, c_coffee = st.columns(4, vertical_alignment="bottom")
        with c_min:
            min_hours = st.number_input("MIN hours", min_value=0, max_value=999, value=cur_min, step=1, key="hours_min_input")
        with c_max:
            max_hours = st.number_input("MAX hours", min_value=0, max_value=999, value=cur_max, step=1, key="hours_max_input")
        with c_sub:
            _cloud_msg = None
            if st.button("✅ Submit vote", key="hours_submit", type="primary"):
                if min_hours is None or max_hours is None:
                    _cloud_msg = "Enter both MIN and MAX hours."
                elif min_hours > max_hours:
                    _cloud_msg = "MIN can't exceed MAX."
                else:
                    cast_vote(shared, session_id, user_id, {"min": int(min_hours), "max": int(max_hours)})
                    st.rerun()
            if _cloud_msg:
                # Transient hovering bubble that fades out (cleared on next autorefresh).
                st.markdown(
                    """<style>
.spp-cloud-wrap { position:relative; height:0; }
.spp-cloud { position:absolute; top:8px; left:0; white-space:nowrap; background:#b91c1c; color:#fff; padding:8px 12px; border-radius:10px; font-size:0.85rem; font-weight:600; box-shadow:0 6px 18px rgba(0,0,0,0.35); z-index:1000; animation:spp-cloud-fade 2.2s ease forwards; }
.spp-cloud::before { content:''; position:absolute; top:-6px; left:22px; border-left:6px solid transparent; border-right:6px solid transparent; border-bottom:6px solid #b91c1c; }
@keyframes spp-cloud-fade { 0%{opacity:0;transform:translateY(-5px);} 12%{opacity:1;transform:translateY(0);} 80%{opacity:1;} 100%{opacity:0;} }
</style>""" + f'<div class="spp-cloud-wrap"><div class="spp-cloud">⚠️ {_cloud_msg}</div></div>',
                    unsafe_allow_html=True,
                )
        with c_coffee:
            is_coffee = my_info["vote"] == "null"
            if st.button("☕", key="hours_coffee", type="primary" if is_coffee else "secondary", help="Abstain / coffee break"):
                cast_vote(shared, session_id, user_id, "null")
                st.rerun()

        if my_info["vote"] == "null":
            st.success("Your vote: **☕**")
        elif isinstance(my_info["vote"], dict):
            st.success(f"Your vote: **{my_info['vote']['min']}–{my_info['vote']['max']} h**")
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

    # --- Hours range chart (hours mode, after reveal) ---
    if session.get("voting_mode", VOTE_MODE_POINTS) == VOTE_MODE_HOURS and session["votes_revealed"]:
        _render_hours_range_chart(session)

    # --- Participants & Votes + Results (hidden in hours mode) ---
    if session.get("voting_mode", VOTE_MODE_POINTS) != VOTE_MODE_HOURS:
        _render_participants_and_results(session, session_id, user_id, is_host)

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
                if entry.get("mode") == VOTE_MODE_HOURS:
                    cols = st.columns(3)
                    with cols[0]:
                        st.write(f"Avg MIN: **{entry['avg_min']:.1f} h**" if entry.get('avg_min') is not None else "Avg MIN: —")
                    with cols[1]:
                        st.write(f"Avg MAX: **{entry['avg_max']:.1f} h**" if entry.get('avg_max') is not None else "Avg MAX: —")
                    with cols[2]:
                        if entry.get('min_low') is not None:
                            st.write(f"Range: **{entry['min_low']}–{entry['max_high']} h**")
                        else:
                            st.write("Range: —")
                else:
                    cols = st.columns(4)
                    with cols[0]:
                        st.write(f"Dev Avg: **{entry['dev_avg']:.1f}**" if entry.get('dev_avg') is not None else "Dev Avg: —")
                    with cols[1]:
                        st.write(f"QA Avg: **{entry['qa_avg']:.1f}**" if entry.get('qa_avg') is not None else "QA Avg: —")
                    with cols[2]:
                        st.write(f"Sum: **{entry['combined']:.1f}**" if entry.get('combined') is not None else "Sum: —")
                    with cols[3]:
                        st.write(f"Fibonacci: **{entry['fibonacci']}**" if entry.get('fibonacci') is not None else "Fibonacci: —")

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
        max_chars=MAX_USERNAME_LENGTH,
    )
    if name != st.session_state.user_name:
        st.session_state.user_name = name[:MAX_USERNAME_LENGTH]

    # Save state to cookies whenever name is set
    if st.session_state.user_name.strip():
        inject_localstorage_writer(st.session_state.user_name)

    if not st.session_state.user_name.strip():
        st.warning("Please enter your name to continue.")
        return

    st.divider()

    # --- Create Session ---
    st.subheader("Create a New Session")
    session_name = st.text_input("Session name", placeholder="Sprint 42 Planning", max_chars=MAX_SESSION_NAME_LENGTH)
    if st.button("🎉 Create Session", type="primary"):
        if not session_name.strip():
            st.error("Please enter a session name.")
        else:
            # Rate limit: max sessions per user
            user_sessions = sum(1 for s in shared["sessions"].values() if s["host_id"] == st.session_state.user_id)
            if user_sessions >= MAX_SESSIONS_PER_USER:
                st.error(f"You can host at most {MAX_SESSIONS_PER_USER} sessions at a time.")
            else:
                sid = create_session(
                    shared, session_name.strip()[:MAX_SESSION_NAME_LENGTH],
                    st.session_state.user_name.strip(),
                    st.session_state.user_id,
                    client_ip=get_client_ip(),
                )
                st.session_state.current_session = sid
                _host_code = shared["sessions"][sid]["participants"][st.session_state.user_id].get("rejoin_code", "")
                st.query_params["session"] = sid
                st.query_params["rc"] = _host_code
                st.session_state.show_welcome = True
                st.session_state.welcome_code = _host_code
                st.rerun()


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

    # Auto-rejoin from URL rejoin code (survives F5 on hosts that lose session_state).
    rc = st.query_params.get("rc")
    if rc:
        code_exists = any(p.get("rejoin_code", "").lower() == rc.strip().lower()
                          for p in session["participants"].values())
        if code_exists:
            res = join_session(
                shared, session_id, st.session_state.user_id,
                st.session_state.user_name.strip() or "Guest", "Dev",
                client_ip=get_client_ip(), rejoin_code=rc,
            )
            if res["ok"]:
                st.session_state.current_session = session_id
                st.query_params["session"] = session_id
                st.query_params["rc"] = res["rejoin_code"]
                st.rerun()
                return
        else:
            # Stale/invalid code in URL: drop it and show the join form.
            try:
                del st.query_params["rc"]
            except Exception:
                pass

    st.title("🃏 Super Point Poker")
    st.subheader(f"Join session: **{session['name']}**")
    st.caption(f"Session ID: `{session_id}` • {len(session['participants'])} participant(s)")

    st.divider()

    name = st.text_input("Your display name (emojis welcome!)", value=st.session_state.user_name, key="join_link_name", placeholder="e.g. 🚀 Carlos", max_chars=MAX_USERNAME_LENGTH)
    role = st.selectbox("Your role", ["Dev", "QA", "PO", "Observer"], index=0, key="join_link_role")
    rejoin_in = st.text_input("Rejoin code (optional)", key="join_link_rejoin", placeholder="e.g. SoggyWaffle — leave blank if it's your first time", max_chars=40)

    if st.button("🎉 Join Session", type="primary"):
        code = rejoin_in.strip() or None
        if not name.strip() and not code:
            st.error("Please enter your name (or a rejoin code).")
        else:
            if name.strip():
                st.session_state.user_name = name.strip()
            res = join_session(
                shared, session_id, st.session_state.user_id,
                st.session_state.user_name.strip() or "Guest", role,
                client_ip=get_client_ip(), rejoin_code=code,
            )
            if res["ok"]:
                st.session_state.current_session = session_id
                st.query_params["session"] = session_id
                st.query_params["rc"] = res["rejoin_code"]
                if res["is_new"]:
                    st.session_state.show_welcome = True
                    st.session_state.welcome_code = res["rejoin_code"]
                st.rerun()
            else:
                st.error("This session is full.")

    st.divider()
    if st.button("Go to Lobby instead"):
        st.query_params.clear()
        st.rerun()
