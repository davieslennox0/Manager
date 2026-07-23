"""Household Gigs — the meeting layer for recurring household work.

A household posts a gig (utilities, subscriptions), one agent claims it, and the
agent reports a status each cycle. That is the whole of it. ManagerX does not
hold, move, or route money, does not verify that the agent did anything, and has
no escrow, bond, or settlement path here — budget_amount and agent_payment_address
are display fields the two parties act on themselves, off-platform.

This module owns the cycle clock: cadence arithmetic and the background loop that
opens the next cycle when its date arrives. It follows the existing loop pattern
(scanner/funding) rather than introducing a queue — a tick is idempotent, so a
missed or repeated tick costs nothing.
"""
import asyncio
import calendar
import datetime
import decimal
import uuid

import config
from db import get_conn, j

BILL_TYPES = ("gas", "electricity", "water", "broadband", "tv_subscription",
              "streaming", "mobile", "waste", "other")
CADENCES = ("monthly", "weekly", "one_time")
GIG_STATUSES = ("open", "claimed", "active", "paused", "cancelled")
CYCLE_STATUSES = ("pending", "done", "not_done", "skipped")

# Statuses whose gigs the cycle clock runs on. A gig goes claimed -> active the
# moment its first cycle opens, so 'claimed' means "an agent is on it, nothing
# has come due yet" and 'active' means "cycles are running".
LIVE_STATUSES = ("claimed", "active")

# Agent-settable cycle outcomes. 'skipped' is deliberately not here: it's the
# household's word (via cancel/pause), not the agent's.
AGENT_CYCLE_STATUSES = ("done", "not_done")


# ManagerX's cut, quoted to the household while they are still typing the budget.
#
# It mirrors the fulfilment rail's own schedule at exactly double it. Pocket
# Bills charges max(NGN 100, 2.5%) — measured off eleven unpaid 402 quotes on
# 2026-07-23, flat below the ~NGN 4,000 crossover and 2.5% above. We charge
# double because the rail's fee is paid out of ours: half covers what we owe
# them, half is the margin. Mirroring their shape rather than picking a flat
# rate is what keeps that true at every ticket size — a percentage alone would
# lose money on small bills, and a flat fee alone would overcharge large ones.
#
# It is added ON TOP of the bill budget rather than skimmed out of it, and that
# direction is the whole point: a bill paid short is a bill the provider
# rejects, and the household ends up disconnected while believing the gig was
# funded. The agent must receive the full bill amount, so the fee is the
# household's cost, disclosed before they commit rather than discovered after.
PLATFORM_FEE_RATE = decimal.Decimal("0.05")        # 5% = 2x the rail's 2.5%
PLATFORM_FEE_FLOOR_NGN = decimal.Decimal("200")    # 2x the rail's NGN 100 floor

# The floor is a naira figure, so it only applies to naira. Quoting NGN 200
# against a dollar budget would be a 200-dollar fee on a 100-dollar bill.
FLOOR_CURRENCIES = ("ngn", "naira", "₦")


def fee_breakdown(budget_amount: str, currency: str = "") -> dict:
    """Split a household's bill budget into what the agent needs and what
    ManagerX charges on top. Money is text everywhere else in this module; this
    is the one place it is arithmetic, so it uses Decimal — binary floats would
    round a naira the wrong way often enough to matter over a year of cycles."""
    try:
        bill = decimal.Decimal(str(budget_amount).strip().replace(",", ""))
    except (decimal.InvalidOperation, AttributeError):
        return {}
    if bill <= 0:
        return {}
    cents = decimal.Decimal("0.01")
    fee = bill * PLATFORM_FEE_RATE
    floor = (PLATFORM_FEE_FLOOR_NGN
             if str(currency).strip().lower() in FLOOR_CURRENCIES
             else decimal.Decimal(0))
    fee = max(fee, floor).quantize(cents, rounding=decimal.ROUND_HALF_UP)
    return {
        "bill_budget": str(bill.quantize(cents, rounding=decimal.ROUND_HALF_UP)),
        "platform_fee": str(fee),
        "total": str((bill + fee).quantize(cents, rounding=decimal.ROUND_HALF_UP)),
        "rate": str(PLATFORM_FEE_RATE),
        "floor": str(floor) if floor else "",
        "at_floor": fee == floor and floor > 0,
        "note": "The agent receives the full bill budget — the ManagerX fee is "
                "added on top so the bill is never paid short. The fee covers "
                "what the agent pays the billing rail to fulfil the work. Both "
                "figures are listed information; ManagerX does not collect either "
                "one — you settle with the agent directly.",
    }


def today() -> datetime.date:
    return datetime.date.today()


def parse_date(value: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def advance(date: datetime.date, cadence: str) -> datetime.date | None:
    """Next cycle date for a cadence, or None when the gig doesn't recur.
    Monthly is calendar-aware and clamps: the 31st becomes the 30th, or the 28th
    in February, rather than overflowing into the next month."""
    if cadence == "weekly":
        return date + datetime.timedelta(days=7)
    if cadence == "monthly":
        year, month = (date.year + 1, 1) if date.month == 12 else (date.year, date.month + 1)
        return datetime.date(year, month, min(date.day, calendar.monthrange(year, month)[1]))
    return None  # one_time never recurs


def shape_gig(row, cycles: list | None = None) -> dict:
    """Row -> API dict. The disclaimer travels with the money fields so no client
    can render a budget or a payment address without the context that ManagerX
    isn't in the middle of it."""
    out = {**dict(row), "bill_types": j(row["bill_types"], [])}
    out["fee"] = fee_breakdown(row["budget_amount"], row["budget_currency"])
    out["settlement"] = {
        "processed_by_managerx": False,
        "note": "Budget and payment address are listed information only. The "
                "household pays the agent directly; ManagerX never holds, moves, "
                "or verifies this payment.",
    }
    if cycles is not None:
        out["cycles"] = [dict(c) for c in cycles]
    return out


def _next_index(conn, gig_id: str) -> int:
    row = conn.execute("SELECT MAX(cycle_index) m FROM household_gig_cycles WHERE gig_id = ?",
                       (gig_id,)).fetchone()
    return (row["m"] or 0) + 1


def open_cycle(conn, gig: dict, cycle_date: str) -> dict | None:
    """Insert the next pending cycle for a gig. Returns None if it already exists
    — the unique (gig_id, cycle_index) index is what makes a repeated tick safe."""
    index = _next_index(conn, gig["gig_id"])
    cycle_id = "hcy_" + uuid.uuid4().hex[:12]
    try:
        conn.execute(
            "INSERT INTO household_gig_cycles (cycle_id, gig_id, cycle_index, cycle_date) "
            "VALUES (?, ?, ?, ?)", (cycle_id, gig["gig_id"], index, cycle_date))
    except Exception:
        return None  # collided with a concurrent tick; that tick's cycle stands
    return {"cycle_id": cycle_id, "gig_id": gig["gig_id"], "cycle_index": index,
            "cycle_date": cycle_date, "status": "pending"}


def generate_due_cycles() -> list[tuple[dict, dict]]:
    """Open a cycle on every live gig whose next_cycle_date has arrived, and roll
    that date forward. Returns [(gig, cycle)] for notification.

    A gig that fell behind (paused for months, say) opens ONE cycle and its date
    is rolled forward past today in a single pass — it does not backfill a cycle
    per missed period, which would bury both sides in alerts for work nobody did.
    """
    now = today()
    conn = get_conn()
    qmarks = ",".join("?" * len(LIVE_STATUSES))
    rows = conn.execute(
        f"SELECT * FROM household_gigs WHERE status IN ({qmarks}) "
        f"AND next_cycle_date != '' AND next_cycle_date <= ?",
        (*LIVE_STATUSES, now.isoformat())).fetchall()
    conn.close()

    opened = []
    for row in rows:
        gig = dict(row)
        due = parse_date(gig["next_cycle_date"])
        if not due:
            continue
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cycle = open_cycle(conn, gig, due.isoformat())
            if cycle is None:
                conn.rollback()
                conn.close()
                continue
            # Roll forward past today so a lapsed gig catches up in one step.
            nxt = advance(due, gig["cadence"])
            while nxt and nxt <= now:
                nxt = advance(nxt, gig["cadence"])
            conn.execute(
                "UPDATE household_gigs SET status='active', next_cycle_date=? WHERE gig_id=?",
                (nxt.isoformat() if nxt else "", gig["gig_id"]))
            conn.commit()
        except Exception:
            conn.rollback()
            conn.close()
            continue
        conn.close()
        opened.append((gig, cycle))
    return opened


async def household_tick() -> dict:
    """One pass of the cycle clock. Notifications are best-effort and are never
    allowed to roll back a cycle that was already committed."""
    from mailer import notify_cycle_open

    opened = await asyncio.to_thread(generate_due_cycles)
    for gig, cycle in opened:
        try:
            await asyncio.to_thread(notify_cycle_open, gig, cycle)
        except Exception:
            pass
    if opened:
        from notify import send_telegram
        await asyncio.to_thread(
            send_telegram,
            f"ManagerX household gigs: {len(opened)} cycle(s) opened\n"
            + "\n".join(f"· {g['title']} → cycle #{c['cycle_index']} ({c['cycle_date']})"
                        for g, c in opened[:10]))
    return {"cycles_opened": len(opened)}


async def household_loop():
    """Background task started by main.py, same shape as scanner/funding."""
    while True:
        try:
            await household_tick()
        except Exception:
            pass  # a failing tick must never kill the loop; next tick retries
        await asyncio.sleep(config.HOUSEHOLD_TICK_SECONDS)
