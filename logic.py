from config import FIBONACCI


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


def calculate_averages(session, separate_qa=False):
    """Return (dev_avg, qa_avg, combined_avg, closest_fib) or Nones if no votes."""
    hoster_votes = session.get("hoster_votes", False)

    def is_voter(p):
        return p["role"] in ("Dev", "QA", "PO") or (p["role"] == "Hoster" and hoster_votes)

    if separate_qa:
        dev_votes = [
            p["vote"] for p in session["participants"].values()
            if (p["role"] in ("Dev", "PO") or (p["role"] == "Hoster" and hoster_votes))
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


def calculate_hours(session):
    """Return (avg_min, avg_max, min_low, max_high, count) for Min/Max hours votes.

    Only counts eligible voters whose vote is a {"min", "max"} dict; excludes
    coffee ("null") and unvoted (None). Returns Nones/0 when no numeric votes.
    """
    hoster_votes = session.get("hoster_votes", False)

    def is_voter(p):
        return p["role"] in ("Dev", "QA", "PO") or (p["role"] == "Hoster" and hoster_votes)

    pairs = [
        p["vote"] for p in session["participants"].values()
        if is_voter(p) and isinstance(p["vote"], dict)
    ]
    if not pairs:
        return None, None, None, None, 0

    mins = [pair["min"] for pair in pairs]
    maxs = [pair["max"] for pair in pairs]
    avg_min = sum(mins) / len(mins)
    avg_max = sum(maxs) / len(maxs)
    return avg_min, avg_max, min(mins), max(maxs), len(pairs)
