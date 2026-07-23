"""Household Gigs — discovery, claim, and status tracking for recurring household
work. ManagerX is the meeting layer: it lists the gig, records which agent took
it, and relays the status that agent reports each cycle.

What this deliberately is NOT, anywhere below: a payment rail, an escrow, or a
verifier. `budget_amount` is what the household says they'll pay and
`agent_payment_address` is where the agent says to send it — both are listed
information, like a salary and an application address on a career posting. The
two parties settle between themselves. Cycle outcomes are the agent's own word;
nothing here checks them, and `household_ack` is the household saying they looked,
not the platform saying it's true.
"""
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import household
from auth import current_actor
from db import get_conn, j

router = APIRouter(prefix="/v1/household-gigs", tags=["household-gigs"])

MAX_ADDRESS_LEN = 200
MAX_NOTE_LEN = 2000
MAX_DETAILS_LEN = 4000


class GigCreate(BaseModel):
    title: str = ""
    bill_types: list[str] = []
    cadence: str = "monthly"
    budget_amount: str = ""
    budget_currency: str = ""
    service_details: str = ""    # meter no., phone for the token, account ref — private
    first_cycle_date: str = ""   # ISO date; defaults to today (starts once claimed)


class GigPatch(BaseModel):
    title: str | None = None
    budget_amount: str | None = None
    budget_currency: str | None = None
    service_details: str | None = None   # operational, not a term: editable at any time
    status: str | None = None    # active <-> paused only


class ClaimBody(BaseModel):
    agent_payment_address: str = ""


class CycleStatusBody(BaseModel):
    status: str = ""
    agent_note: str = ""


# ── validation ───────────────────────────────────────────────────────────────

def _clean_amount(value: str) -> str:
    """Money is stored numeric-as-text (the agent_jobs.reward convention): it is
    only ever displayed, never computed on, and text keeps large NGN figures and
    minor units exactly as the household typed them."""
    text = str(value).strip().replace(",", "")
    if not text:
        return ""
    try:
        if float(text) <= 0:
            raise HTTPException(422, "Budget must be greater than zero")
    except ValueError:
        raise HTTPException(422, "Budget must be a number (the currency goes in "
                                 "budget_currency)")
    return text


def _clean_bill_types(values: list[str]) -> str:
    cleaned = []
    for v in values:
        s = str(v).strip().lower().replace(" ", "_")
        if s and s not in cleaned:
            cleaned.append(s if s in household.BILL_TYPES else "other")
    if not cleaned:
        raise HTTPException(422, "Pick at least one bill type "
                                 f"({', '.join(household.BILL_TYPES)})")
    return json.dumps(cleaned)


def _gig_or_404(conn, gig_id: str):
    row = conn.execute("SELECT * FROM household_gigs WHERE gig_id = ?", (gig_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "No such household gig")
    return row


def _owned(conn, gig_id: str, user_id: str):
    row = _gig_or_404(conn, gig_id)
    if row["household_user_id"] != user_id:
        conn.close()
        raise HTTPException(403, "This gig belongs to another household")
    return row


def _claimed_by(conn, gig_id: str, user_id: str):
    row = _gig_or_404(conn, gig_id)
    if row["claimed_by_agent_id"] != user_id:
        conn.close()
        raise HTTPException(403, "You are not the agent on this gig")
    return row


def _public(row) -> dict:
    """Board shape: the household's identity never leaves the dashboard, and
    neither does service_details — that field holds a meter number, the phone the
    prepaid token is sent to, an account or smartcard reference. Publishing it
    would hand anyone browsing the board enough to impersonate the household to
    its own utility. Browsing agents get only whether it has been filled in."""
    d = household.shape_gig(row)
    d["has_service_details"] = bool((row["service_details"] or "").strip())
    for private in ("household_user_id", "claimed_by_agent_id",
                    "agent_payment_address", "service_details"):
        d.pop(private, None)
    return d


# ── create / browse ──────────────────────────────────────────────────────────

@router.post("")
async def create_gig(body: GigCreate, user: dict = Depends(current_actor)):
    """Post a recurring household gig. Starts `open` — visible on the board until
    an agent claims it."""
    title = body.title.strip()
    if len(title) < 3:
        raise HTTPException(422, "Give the gig a title (e.g. “Flat 4 — utilities bundle”)")
    if body.cadence not in household.CADENCES:
        raise HTTPException(422, f"cadence must be one of {', '.join(household.CADENCES)}")
    bill_types = _clean_bill_types(body.bill_types)
    amount = _clean_amount(body.budget_amount)
    start = household.parse_date(body.first_cycle_date) or household.today()

    gig_id = "hgig_" + uuid.uuid4().hex[:12]
    conn = get_conn()
    conn.execute(
        """INSERT INTO household_gigs (gig_id, household_user_id, title, bill_types,
           cadence, budget_amount, budget_currency, service_details, next_cycle_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (gig_id, user["user_id"], title, bill_types, body.cadence, amount,
         body.budget_currency.strip()[:24],
         body.service_details.strip()[:MAX_DETAILS_LEN], start.isoformat()))
    conn.commit()
    row = conn.execute("SELECT * FROM household_gigs WHERE gig_id = ?", (gig_id,)).fetchone()
    conn.close()
    return household.shape_gig(row)


@router.get("")
async def browse_gigs(bill_type: str = "", cadence: str = "", q: str = "",
                      limit: int = Query(100, le=500), offset: int = 0):
    """Public board — open gigs only. No auth, same as the agent-jobs board: an
    agent polls this to find work."""
    where, args = ["status = 'open'"], []
    if bill_type:
        where.append("bill_types LIKE ?")
        args.append(f'%"{bill_type.strip().lower()}"%')
    if cadence:
        where.append("cadence = ?")
        args.append(cadence)
    if q:
        where.append("title LIKE ?")
        args.append(f"%{q}%")
    clause = " AND ".join(where)
    conn = get_conn()
    rows = conn.execute(f"SELECT * FROM household_gigs WHERE {clause} "
                        f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
                        args + [limit, offset]).fetchall()
    total = conn.execute(f"SELECT COUNT(*) c FROM household_gigs WHERE {clause}",
                         args).fetchone()["c"]
    open_rows = conn.execute("SELECT bill_types, cadence FROM household_gigs "
                             "WHERE status = 'open'").fetchall()
    conn.close()

    bill_counts, cadence_counts = {}, {}
    for r in open_rows:
        for bt in j(r["bill_types"], []):
            bill_counts[bt] = bill_counts.get(bt, 0) + 1
        cadence_counts[r["cadence"]] = cadence_counts.get(r["cadence"], 0) + 1
    return {
        "total": total,
        # One source of truth for the posting form's live fee quote — the browser
        # should never carry its own copy of the rate and drift from the server.
        "platform_fee_rate": str(household.PLATFORM_FEE_RATE),
        "platform_fee_floor_ngn": str(household.PLATFORM_FEE_FLOOR_NGN),
        "facets": {
            "bill_types": [{"name": k, "count": v} for k, v in
                           sorted(bill_counts.items(), key=lambda x: -x[1])],
            "cadences": [{"name": k, "count": v} for k, v in
                         sorted(cadence_counts.items(), key=lambda x: -x[1])],
        },
        "note": "Recurring household work — utilities and subscriptions a household "
                "wants an agent to handle each cycle. Claim one, settle directly with "
                "the household, and report each cycle's status. ManagerX lists and "
                "tracks; it does not hold, move, or verify any payment.",
        "household_gigs": [_public(r) for r in rows],
    }


# Literal paths before /{gig_id}: FastAPI matches in declaration order.
@router.get("/summary")
async def summary(user: dict = Depends(current_actor)):
    """What is waiting on this user, on both sides. Email is a convenience layer —
    a provider outage, an unverified sender, or a household that never opens its
    inbox must not mean nobody ever learns a cycle came due. These counts drive
    the in-app badges, so the app is self-sufficient without a single email."""
    conn = get_conn()
    review = conn.execute(
        """SELECT COUNT(*) c FROM household_gig_cycles cy
           JOIN household_gigs g ON g.gig_id = cy.gig_id
           WHERE g.household_user_id = ? AND cy.household_ack = 0
             AND cy.status != 'pending'""", (user["user_id"],)).fetchone()["c"]
    action = conn.execute(
        """SELECT COUNT(*) c FROM household_gig_cycles cy
           JOIN household_gigs g ON g.gig_id = cy.gig_id
           WHERE g.claimed_by_agent_id = ? AND cy.status = 'pending'
             AND g.status != 'cancelled'""", (user["user_id"],)).fetchone()["c"]
    conn.close()
    return {"awaiting_your_review": review, "awaiting_your_action": action}


@router.get("/mine")
async def my_gigs(user: dict = Depends(current_actor)):
    """Household's own posted gigs, with a pending-cycle count each."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM household_gigs WHERE household_user_id = ? "
                        "ORDER BY created_at DESC", (user["user_id"],)).fetchall()
    out = []
    for row in rows:
        gig = household.shape_gig(row)
        gig["unacked_cycles"] = conn.execute(
            "SELECT COUNT(*) c FROM household_gig_cycles WHERE gig_id = ? "
            "AND household_ack = 0", (row["gig_id"],)).fetchone()["c"]
        out.append(gig)
    conn.close()
    return {"total": len(out), "household_gigs": out}


@router.get("/claimed")
async def claimed_gigs(user: dict = Depends(current_actor)):
    """Agent's side: gigs this user claimed, each with its open (pending) cycles —
    the work queue the agent acts on."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM household_gigs WHERE claimed_by_agent_id = ? "
                        "ORDER BY claimed_at DESC", (user["user_id"],)).fetchall()
    out = []
    for row in rows:
        cycles = conn.execute(
            "SELECT * FROM household_gig_cycles WHERE gig_id = ? "
            "ORDER BY cycle_index DESC", (row["gig_id"],)).fetchall()
        gig = household.shape_gig(row, cycles)
        gig["pending_cycles"] = [c for c in gig["cycles"] if c["status"] == "pending"]
        out.append(gig)
    conn.close()
    return {"total": len(out), "household_gigs": out,
            "note": "service_details is the household's own account data — meter "
                    "number, the phone its prepaid token is sent to, account or "
                    "smartcard reference. It is released to you because you claimed "
                    "the gig. Use it for this work and nothing else; don't log, "
                    "forward, or republish it."}


# ── the gig ──────────────────────────────────────────────────────────────────

@router.patch("/{gig_id}")
async def patch_gig(gig_id: str, body: GigPatch, user: dict = Depends(current_actor)):
    """Household edits. Budget and title are editable only while the gig is still
    `open` — once an agent has claimed on those terms, changing them would be a
    renegotiation, and there is deliberately no renegotiation flow: cancel and
    repost instead. service_details and status are not terms and stay editable:
    a mistyped meter number has to be fixable mid-gig, or every cycle after it
    fails."""
    conn = get_conn()
    row = _owned(conn, gig_id, user["user_id"])
    sets, args = [], []

    terms = [f for f in (body.title, body.budget_amount, body.budget_currency)
             if f is not None]
    if terms and row["status"] != "open":
        conn.close()
        raise HTTPException(409, "This gig has been claimed — its terms are fixed. "
                                 "Cancel and repost to change them.")
    if body.title is not None:
        title = body.title.strip()
        if len(title) < 3:
            conn.close()
            raise HTTPException(422, "Title is too short")
        sets.append("title = ?")
        args.append(title)
    if body.budget_amount is not None:
        sets.append("budget_amount = ?")
        args.append(_clean_amount(body.budget_amount))
    if body.budget_currency is not None:
        sets.append("budget_currency = ?")
        args.append(body.budget_currency.strip()[:24])
    if body.service_details is not None:
        # Not frozen on claim: a meter number gets mistyped and a phone number
        # changes, and the agent needs the corrected one to do the next cycle.
        sets.append("service_details = ?")
        args.append(body.service_details.strip()[:MAX_DETAILS_LEN])

    if body.status is not None:
        if body.status not in ("active", "paused"):
            conn.close()
            raise HTTPException(422, "status may only be set to active or paused "
                                     "(use /cancel to end a gig)")
        if row["status"] not in ("claimed", "active", "paused"):
            conn.close()
            raise HTTPException(409, f"A {row['status']} gig cannot be paused or resumed")
        sets.append("status = ?")
        args.append(body.status)

    if not sets:
        conn.close()
        raise HTTPException(422, "Nothing to update")
    conn.execute(f"UPDATE household_gigs SET {', '.join(sets)} WHERE gig_id = ?",
                 args + [gig_id])
    conn.commit()
    updated = conn.execute("SELECT * FROM household_gigs WHERE gig_id = ?",
                           (gig_id,)).fetchone()
    conn.close()
    return household.shape_gig(updated)


@router.post("/{gig_id}/claim")
async def claim_gig(gig_id: str, body: ClaimBody, user: dict = Depends(current_actor)):
    """An agent takes the gig. The claim is decided by the database, not by a
    read-then-write in Python: the UPDATE carries `status='open'` in its own WHERE
    clause and runs inside an IMMEDIATE transaction, so of two agents racing the
    same gig exactly one sees rowcount 1 and the other is rejected."""
    address = body.agent_payment_address.strip()
    if not address:
        raise HTTPException(422, "Supply agent_payment_address — the household pays "
                                 "you directly, so they need to know where")
    if len(address) > MAX_ADDRESS_LEN:
        raise HTTPException(422, "agent_payment_address is too long")

    conn = get_conn()
    row = _gig_or_404(conn, gig_id)
    if row["household_user_id"] == user["user_id"]:
        conn.close()
        raise HTTPException(409, "You can't claim your own household gig")
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            """UPDATE household_gigs SET status='claimed', claimed_by_agent_id=?,
               agent_payment_address=?, claimed_at=CURRENT_TIMESTAMP
               WHERE gig_id=? AND status='open'""",
            (user["user_id"], address, gig_id))
        if cur.rowcount == 0:
            conn.rollback()
            conn.close()
            raise HTTPException(409, "Already claimed by another agent")
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        conn.close()
        raise HTTPException(500, "Could not claim the gig — try again")
    updated = conn.execute("SELECT * FROM household_gigs WHERE gig_id = ?",
                           (gig_id,)).fetchone()
    conn.close()

    gig = household.shape_gig(updated)
    from mailer import notify_gig_claimed
    notify_gig_claimed(gig)
    return gig


@router.post("/{gig_id}/cancel")
async def cancel_gig(gig_id: str, user: dict = Depends(current_actor)):
    """Household ends the gig. Clearing next_cycle_date is what actually stops the
    cycle loop. Nothing financial happens here, because nothing financial ever
    passed through ManagerX — there is no balance to refund or reverse."""
    conn = get_conn()
    row = _owned(conn, gig_id, user["user_id"])
    if row["status"] == "cancelled":
        conn.close()
        raise HTTPException(409, "Already cancelled")
    conn.execute("UPDATE household_gigs SET status='cancelled', next_cycle_date='' "
                 "WHERE gig_id = ?", (gig_id,))
    conn.commit()
    updated = conn.execute("SELECT * FROM household_gigs WHERE gig_id = ?",
                           (gig_id,)).fetchone()
    conn.close()

    gig = household.shape_gig(updated)
    from mailer import notify_gig_cancelled
    notify_gig_cancelled(gig)
    return gig


@router.get("/{gig_id}/dashboard")
async def gig_dashboard(gig_id: str, user: dict = Depends(current_actor)):
    """Household's view of one gig: terms, who claimed it, where to pay them, and
    every cycle with its reported status."""
    conn = get_conn()
    row = _owned(conn, gig_id, user["user_id"])
    cycles = conn.execute("SELECT * FROM household_gig_cycles WHERE gig_id = ? "
                          "ORDER BY cycle_index DESC", (gig_id,)).fetchall()
    agent = None
    if row["claimed_by_agent_id"]:
        arow = conn.execute("SELECT user_id, email FROM users WHERE user_id = ?",
                            (row["claimed_by_agent_id"],)).fetchone()
        agent = dict(arow) if arow else None
    conn.close()

    gig = household.shape_gig(row, cycles)
    gig["agent"] = agent
    gig["pay_the_agent"] = {
        "address": row["agent_payment_address"],
        "amount": row["budget_amount"],
        "currency": row["budget_currency"],
        "instruction": "Pay this agent directly — ManagerX does not process this "
                       "payment, and cycle statuses below are the agent's own report, "
                       "not a verification.",
    } if row["agent_payment_address"] else None
    return gig


# ── cycles ───────────────────────────────────────────────────────────────────

def _cycle_or_404(conn, gig_id: str, cycle_id: str):
    row = conn.execute("SELECT * FROM household_gig_cycles WHERE cycle_id = ? AND gig_id = ?",
                       (cycle_id, gig_id)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "No such cycle on this gig")
    return row


@router.post("/{gig_id}/cycles/{cycle_id}/status")
async def report_cycle(gig_id: str, cycle_id: str, body: CycleStatusBody,
                       user: dict = Depends(current_actor)):
    """The claiming agent reports how a cycle went. Pure relay — ManagerX records
    the claim and shows it to the household; it does not and cannot check it."""
    if body.status not in household.AGENT_CYCLE_STATUSES:
        raise HTTPException(422, "status must be done or not_done")
    conn = get_conn()
    row = _claimed_by(conn, gig_id, user["user_id"])
    cycle = _cycle_or_404(conn, gig_id, cycle_id)
    if cycle["status"] == "skipped":
        conn.close()
        raise HTTPException(409, "This cycle was skipped and can't be reported on")
    conn.execute(
        "UPDATE household_gig_cycles SET status=?, agent_note=?, "
        "reported_at=CURRENT_TIMESTAMP WHERE cycle_id=?",
        (body.status, body.agent_note.strip()[:MAX_NOTE_LEN], cycle_id))
    conn.commit()
    updated = conn.execute("SELECT * FROM household_gig_cycles WHERE cycle_id = ?",
                           (cycle_id,)).fetchone()
    conn.close()

    from mailer import notify_cycle_reported
    notify_cycle_reported(household.shape_gig(row), dict(updated))
    return {**dict(updated), "self_reported": True,
            "note": "Reported by the agent. ManagerX does not verify this."}


@router.post("/{gig_id}/cycles/{cycle_id}/ack")
async def ack_cycle(gig_id: str, cycle_id: str, user: dict = Depends(current_actor)):
    """Household confirms it has reviewed a cycle. This is the only field in the
    system the household itself asserts — everything else is the agent's word."""
    conn = get_conn()
    _owned(conn, gig_id, user["user_id"])
    _cycle_or_404(conn, gig_id, cycle_id)
    conn.execute("UPDATE household_gig_cycles SET household_ack=1, "
                 "acked_at=CURRENT_TIMESTAMP WHERE cycle_id=?", (cycle_id,))
    conn.commit()
    updated = conn.execute("SELECT * FROM household_gig_cycles WHERE cycle_id = ?",
                           (cycle_id,)).fetchone()
    conn.close()
    return dict(updated)
