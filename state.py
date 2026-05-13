import time
import secrets
from datetime import datetime

from config import DEFAULT_VOTE_BUTTONS, MAX_PARTICIPANTS_PER_SESSION, MAX_USERNAME_LENGTH
from logic import calculate_averages


def create_session(state, session_name, host_name, host_id, client_ip=None):
    session_id = secrets.token_hex(6)  # 48 bits of entropy
    with state["lock"]:
        state["sessions"][session_id] = {
            "name": session_name,
            "host_id": host_id,
            "participants": {
                host_id: {"name": host_name, "role": "Hoster", "vote": None, "heartbeat": time.time(), "client_ip": client_ip}
            },
            "votes_revealed": False,
            "ticket_label": "",
            "separate_qa": False,
            "hoster_votes": False,
            "anyone_can_reveal": False,
            "block_vote_after_reveal": False,
            "vote_buttons": DEFAULT_VOTE_BUTTONS,
            "host_heartbeat": time.time(),
            "last_vote_time": time.time(),
            "history": [],
            "created_at": datetime.now(),
        }
    return session_id


def join_session(state, session_id, user_id, user_name, role, client_ip=None):
    # Enforce name length limit
    user_name = user_name[:MAX_USERNAME_LENGTH]
    with state["lock"]:
        if session_id in state["sessions"]:
            session = state["sessions"][session_id]
            # Easter egg: only when hoster is "Webson"
            hoster_info = session["participants"].get(session["host_id"], {})
            if "webson" in hoster_info.get("name", "").lower():
                if "rafael" in user_name.lower() or "leafar" in user_name.lower():
                    user_name = "🤓🤓Nerd Detected🤓🤓"
            existing = session["participants"].get(user_id)
            if existing:
                # Reconnect with same user_id: update name/role/heartbeat, preserve vote
                existing["name"] = user_name
                existing["role"] = role
                existing["heartbeat"] = time.time()
                if client_ip:
                    existing["client_ip"] = client_ip
                session["last_activity"] = time.time()
            else:
                # Check for duplicate by name + IP (user reconnected with new session state)
                old_uid = None
                old_data = None
                if client_ip and client_ip != "unknown":
                    for pid, pinfo in session["participants"].items():
                        if pinfo.get("client_ip") == client_ip and pinfo["name"] == user_name:
                            old_uid = pid
                            old_data = pinfo
                            break

                if old_uid and old_data:
                    # Take over old slot: preserve vote, update identity
                    del session["participants"][old_uid]
                    session["participants"][user_id] = {
                        "name": user_name,
                        "role": role,
                        "vote": old_data["vote"],
                        "heartbeat": time.time(),
                        "client_ip": client_ip,
                    }
                    # If the old uid was the host, update host_id
                    if session["host_id"] == old_uid:
                        session["host_id"] = user_id
                    # Un-reveal votes so returning joiner can't see results
                    if session["votes_revealed"]:
                        session["votes_revealed"] = False
                else:
                    # Enforce participant limit
                    if len(session["participants"]) >= MAX_PARTICIPANTS_PER_SESSION:
                        return False
                    session["participants"][user_id] = {
                        "name": user_name,
                        "role": role,
                        "vote": None,
                        "heartbeat": time.time(),
                        "client_ip": client_ip,
                    }
                    # Un-reveal votes so the new joiner can vote without seeing results
                    if session["votes_revealed"]:
                        session["votes_revealed"] = False
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
            voting_roles = ("Dev", "QA", "PO")
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
                is_voter = p["role"] in ("Dev", "QA", "PO") or (p["role"] == "Hoster" and hoster_votes_on)
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


SESSION_TIMEOUT = 30 * 60  # 30 minutes


def cleanup_stale_sessions(state):
    """Remove sessions with no activity for more than 30 minutes."""
    now = time.time()
    with state["lock"]:
        stale = [
            sid for sid, s in state["sessions"].items()
            if now - s.get("last_activity", s.get("last_vote_time", now)) > SESSION_TIMEOUT
        ]
        for sid in stale:
            del state["sessions"][sid]
