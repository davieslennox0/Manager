#!/usr/bin/env python3
"""A reference jobber agent for ManagerX Household Gigs.

The loop, in one paragraph: poll the public board for open household gigs, claim
the ones matching this agent's policy, watch the claimed gigs for cycles that come
due, pay each due bill through a fulfilment adapter, and report the outcome back
to ManagerX.

Three parties, and it is worth being precise about who does what:

    the household   posts the gig, pays the jobber directly, off-platform
    ManagerX        lists the gig, records the claim, opens a cycle on schedule,
                    relays the outcome. Touches no money and verifies nothing.
    the jobber      this program. Claims, pays the biller, reports.
    the biller rail Pocket Bills or equivalent — see fulfilment.py

This file depends on nothing in the ManagerX codebase. It talks to a public HTTP
API and nothing else, which is the point: anyone can run this, or write their own,
and get listed on the marketplace.

What this agent deliberately does NOT do: verify that the household actually paid
it. That is off-platform between the two parties, exactly as ManagerX describes
it, and this agent inherits the same boundary. If you run this for real money,
that check is yours to add and it belongs before fulfil().

    python jobber.py once        one pass, then exit
    python jobber.py run         loop forever
    python jobber.py status      what this agent is holding, incl. anything stuck
    python jobber.py resolve     unstick a cycle whose payment outcome is unknown
"""
import os
import sys
import time
import datetime
from dataclasses import dataclass, field

import requests

import fulfilment
from ledger import Ledger

VERSION = "0.1.0"


# ── configuration ────────────────────────────────────────────────────────────

def load_env(path: str = ".env"):
    """Minimal .env reader so this runs with no dependency beyond requests."""
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _csv(name: str, default: str) -> tuple:
    raw = os.getenv(name, default)
    return tuple(v.strip().lower() for v in raw.split(",") if v.strip())


@dataclass
class Config:
    base: str = ""
    key: str = ""
    payment_address: str = ""
    poll_seconds: int = 300
    bill_types: tuple = ()
    cadences: tuple = ()
    currencies: tuple = ()
    min_budget: float = 0.0
    max_active_gigs: int = 10
    fulfilment: str = "mock"
    pocketbills_endpoint: str = ""
    ledger_path: str = "jobber.db"
    dry_run: bool = False
    note_prefix: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        cfg = cls(
            base=os.getenv("MANAGERX_BASE", "https://managerx.xyz").rstrip("/"),
            key=os.getenv("MANAGERX_KEY", "").strip(),
            payment_address=os.getenv("AGENT_PAYMENT_ADDRESS", "").strip(),
            poll_seconds=int(os.getenv("POLL_SECONDS", "300")),
            bill_types=_csv("BILL_TYPES", "electricity,broadband,mobile,water"),
            cadences=_csv("CADENCES", "monthly,weekly,one_time"),
            currencies=_csv("CURRENCIES", ""),
            min_budget=float(os.getenv("MIN_BUDGET", "0") or 0),
            max_active_gigs=int(os.getenv("MAX_ACTIVE_GIGS", "10")),
            fulfilment=os.getenv("FULFILMENT", "mock").strip().lower(),
            pocketbills_endpoint=os.getenv("POCKETBILLS_ENDPOINT", "").strip(),
            ledger_path=os.getenv("LEDGER_PATH", "jobber.db"),
            dry_run=os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes"),
            note_prefix=os.getenv("NOTE_PREFIX", "").strip(),
        )
        if not cfg.key:
            raise SystemExit("MANAGERX_KEY is not set. Mint an agent key at "
                             "managerx.xyz -> dashboard, then put it in .env")
        if not cfg.payment_address:
            raise SystemExit("AGENT_PAYMENT_ADDRESS is not set. The household pays "
                             "you directly, so they need somewhere to send it.")
        return cfg


def log(*parts):
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}]", *parts, flush=True)


# ── ManagerX client ──────────────────────────────────────────────────────────

class ManagerX:
    """The five calls in the whole integration. Nothing else is needed."""

    def __init__(self, base: str, key: str, timeout: int = 30):
        self.base = base
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": key,
                                     "User-Agent": f"managerx-reference-jobber/{VERSION}"})

    def _call(self, method: str, path: str, **kw):
        r = self.session.request(method, f"{self.base}{path}", timeout=self.timeout, **kw)
        return r

    def browse(self, bill_type: str = "", cadence: str = "") -> list[dict]:
        """Public board. No auth needed for this one, but reusing the session is
        harmless and keeps the client in one place."""
        params = {k: v for k, v in
                  (("bill_type", bill_type), ("cadence", cadence)) if v}
        r = self._call("GET", "/v1/household-gigs", params=params)
        r.raise_for_status()
        return r.json().get("household_gigs", [])

    def claim(self, gig_id: str, address: str) -> tuple[bool, str]:
        r = self._call("POST", f"/v1/household-gigs/{gig_id}/claim",
                       json={"agent_payment_address": address})
        if r.status_code == 409:
            return False, "already claimed"
        if r.status_code == 401:
            raise SystemExit("ManagerX rejected the agent key (401). Check "
                             "MANAGERX_KEY, and that it has not been revoked.")
        if not r.ok:
            return False, f"{r.status_code} {r.text[:200]}"
        return True, ""

    def claimed(self) -> list[dict]:
        r = self._call("GET", "/v1/household-gigs/claimed")
        if r.status_code == 401:
            raise SystemExit("ManagerX rejected the agent key (401).")
        r.raise_for_status()
        return r.json().get("household_gigs", [])

    def report(self, gig_id: str, cycle_id: str, status: str, note: str) -> bool:
        r = self._call("POST",
                       f"/v1/household-gigs/{gig_id}/cycles/{cycle_id}/status",
                       json={"status": status, "agent_note": note[:2000]})
        if not r.ok:
            log(f"  ! report failed {r.status_code}: {r.text[:200]}")
        return r.ok


# ── policy ───────────────────────────────────────────────────────────────────

def wants(cfg: Config, gig: dict) -> tuple[bool, str]:
    """Should this agent claim this gig? Kept as one honest function rather than
    scattered ifs, because this is the part every operator will rewrite."""
    types = [t.lower() for t in gig.get("bill_types") or []]
    if cfg.bill_types and not any(t in cfg.bill_types for t in types):
        return False, f"bill types {types} outside policy"
    if cfg.cadences and (gig.get("cadence") or "").lower() not in cfg.cadences:
        return False, f"cadence {gig.get('cadence')!r} outside policy"

    currency = (gig.get("budget_currency") or "").lower()
    if cfg.currencies and currency not in cfg.currencies:
        return False, f"currency {currency!r} outside policy"
    if cfg.min_budget:
        try:
            if float(gig.get("budget_amount") or 0) < cfg.min_budget:
                return False, f"budget {gig.get('budget_amount')} below minimum"
        except (TypeError, ValueError):
            return False, "budget unreadable"
    return True, ""


# ── the three phases of a pass ───────────────────────────────────────────────

def settle_outstanding(cfg: Config, mx: ManagerX, led: Ledger):
    """Anything the biller finished but ManagerX was never told about. This runs
    FIRST, before any new work, so a crash mid-cycle is repaired before it can
    compound."""
    for row in led.in_state("fulfilled"):
        note = f"Paid. Reference: {row['reference']}. {row['detail']}".strip()
        if mx.report(row["gig_id"], row["cycle_id"], "done", _note(cfg, note)):
            led.mark(row["cycle_id"], "reported", row["reference"], row["detail"])
            log(f"  ~ reported a previously-unreported payment {row['cycle_id']}")

    for row in led.in_state("failed"):
        note = f"Could not complete this cycle. {row['detail']}".strip()
        if mx.report(row["gig_id"], row["cycle_id"], "not_done", _note(cfg, note)):
            led.mark(row["cycle_id"], "reported", "", row["detail"])
            log(f"  ~ reported failed cycle {row['cycle_id']}")

    stuck = led.in_state("attempting")
    if stuck:
        log(f"  ! {len(stuck)} cycle(s) with an UNKNOWN payment outcome — not "
            f"retrying. Run `python jobber.py status` and resolve them by hand.")


def discover(cfg: Config, mx: ManagerX, led: Ledger, active: int,
             adapter: fulfilment.Adapter):
    room = cfg.max_active_gigs - active
    if room <= 0:
        log(f"  at capacity ({active}/{cfg.max_active_gigs}) — not claiming")
        return 0

    board = mx.browse()
    claimed = 0
    for gig in board:
        if claimed >= room:
            break
        gid = gig.get("gig_id", "")
        if led.has_claimed(gid):
            continue
        want, why = wants(cfg, gig)
        # Don't claim work the rail can't actually service. A claim the agent
        # can't honour is worse than leaving the gig on the board for someone
        # who can — it takes the gig off the market and strands the household.
        if want and hasattr(adapter, "supports"):
            types = [t.lower() for t in gig.get("bill_types") or []]
            if not any(adapter.supports(t) for t in types):
                want, why = False, f"{adapter.name} has no rail for {types}"
        if not want:
            log(f"  - skip {gid} ({gig.get('title', '')[:40]}): {why}")
            continue
        if cfg.dry_run:
            log(f"  = DRY RUN would claim {gid} ({gig.get('title', '')[:40]})")
            continue
        ok, err = mx.claim(gid, cfg.payment_address)
        if ok:
            led.record_claim(gid, gig.get("title", ""))
            claimed += 1
            log(f"  + claimed {gid} ({gig.get('title', '')[:40]})")
        else:
            log(f"  - could not claim {gid}: {err}")
    if not board:
        log("  board is empty")
    return claimed


def work(cfg: Config, mx: ManagerX, led: Ledger,
         adapter: fulfilment.Adapter) -> tuple[int, int]:
    gigs = mx.claimed()
    active = sum(1 for g in gigs
                 if g.get("status") in ("claimed", "active", "paused"))
    done = 0
    for gig in gigs:
        for cycle in gig.get("pending_cycles") or []:
            if _fulfil(cfg, mx, led, adapter, gig, cycle):
                done += 1
    return active, done


def _fulfil(cfg, mx, led, adapter, gig, cycle) -> bool:
    cycle_id, gig_id = cycle["cycle_id"], gig["gig_id"]
    label = f"{gig.get('title', '')[:32]} cycle {cycle.get('cycle_index')}"

    if led.get(cycle_id):
        return False  # settle_outstanding owns it now; never pay twice

    details = (gig.get("service_details") or "").strip()
    if not details:
        # Deliberately not reported as not_done. "You didn't give me your meter
        # number" is not a failed cycle, and recording it as one would put a
        # false mark on a household that has simply not filled a box in yet.
        # The cycle stays pending and visible on their dashboard.
        log(f"  ! {label}: no service_details from the household — cannot act, "
            f"leaving the cycle open")
        return False

    if cfg.dry_run:
        log(f"  = DRY RUN would pay {label} via {adapter.name}")
        return False

    # Write the intent down BEFORE spending anything. If we die on the next line,
    # the record is what stops the next run from paying again.
    if not led.begin(cycle_id, gig_id):
        return False

    log(f"  > paying {label} via {adapter.name}")
    result = adapter.pay(
        cycle_id=cycle_id,
        bill_type=(gig.get("bill_types") or ["other"])[0],
        service_details=details,
        amount=str(gig.get("budget_amount") or ""),
        currency=str(gig.get("budget_currency") or ""),
    )

    if result.state == "unknown":
        led.mark(cycle_id, "attempting", "", result.detail)
        log(f"  ! {label}: UNKNOWN outcome — {result.detail}")
        log(f"    parked. Check with the biller, then: python jobber.py resolve "
            f"{cycle_id} <paid|failed> [reference]")
        return False

    if not result.ok:
        led.mark(cycle_id, "failed", "", result.detail)
        note = f"Could not complete this cycle. {result.detail}"
        if mx.report(gig_id, cycle_id, "not_done", _note(cfg, note)):
            led.mark(cycle_id, "reported", "", result.detail)
        log(f"  x {label}: {result.detail}")
        return False

    led.mark(cycle_id, "fulfilled", result.reference, result.detail)
    note = f"Paid. Reference: {result.reference}. {result.detail}".strip()
    if mx.report(gig_id, cycle_id, "done", _note(cfg, note)):
        led.mark(cycle_id, "reported", result.reference, result.detail)
    log(f"  * {label}: done, ref {result.reference}")
    return True


def _note(cfg: Config, note: str) -> str:
    return f"{cfg.note_prefix} {note}".strip() if cfg.note_prefix else note


# ── commands ─────────────────────────────────────────────────────────────────

def run_once(cfg: Config, mx: ManagerX, led: Ledger, adapter: fulfilment.Adapter):
    log(f"pass starting (fulfilment={adapter.name}"
        f"{', DRY RUN' if cfg.dry_run else ''})")
    settle_outstanding(cfg, mx, led)
    active, done = work(cfg, mx, led, adapter)
    claimed = discover(cfg, mx, led, active, adapter)
    log(f"pass done — {active} gig(s) held, {done} cycle(s) fulfilled, "
        f"{claimed} newly claimed")


def cmd_status(cfg: Config, mx: ManagerX, led: Ledger):
    print(f"ManagerX      {cfg.base}")
    print(f"paying out to {cfg.payment_address}")
    print(f"fulfilment    {cfg.fulfilment}{'  (DRY RUN)' if cfg.dry_run else ''}")
    print(f"policy        bill_types={','.join(cfg.bill_types) or 'any'} "
          f"cadences={','.join(cfg.cadences) or 'any'} "
          f"min_budget={cfg.min_budget or 'none'} max_gigs={cfg.max_active_gigs}")
    print()

    counts = led.counts()
    print("ledger        " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                              or "empty"))

    stuck = led.in_state("attempting")
    if stuck:
        print()
        print(f"!! {len(stuck)} cycle(s) with an UNKNOWN payment outcome. The agent "
              f"will not touch these.")
        print("   Confirm with the biller whether the money moved, then resolve:")
        for row in stuck:
            print(f"     {row['cycle_id']}  gig {row['gig_id']}  since "
                  f"{row['started_at']}")
            print(f"       {row['detail'][:110]}")
            print(f"       python jobber.py resolve {row['cycle_id']} "
                  f"<paid|failed> [reference]")

    try:
        gigs = mx.claimed()
    except Exception as exc:
        print(f"\ncould not reach ManagerX: {exc}")
        return
    print(f"\nholding {len(gigs)} gig(s):")
    for g in gigs:
        pending = len(g.get("pending_cycles") or [])
        print(f"  {g['gig_id']}  {g.get('status'):9}  "
              f"{(g.get('title') or '')[:40]:42} pending={pending}")


def cmd_resolve(cfg: Config, mx: ManagerX, led: Ledger, argv: list[str]):
    """The human's way out of an unknown payment. The agent will not guess, so
    somebody checks with the biller and tells it what happened."""
    if len(argv) < 2:
        raise SystemExit("usage: jobber.py resolve <cycle_id> <paid|failed> "
                         "[reference]")
    cycle_id, outcome = argv[0], argv[1].lower()
    reference = argv[2] if len(argv) > 2 else ""
    row = led.get(cycle_id)
    if not row:
        raise SystemExit(f"no ledger record for {cycle_id}")
    if row["state"] != "attempting":
        raise SystemExit(f"{cycle_id} is in state {row['state']!r}, nothing to "
                         f"resolve")
    if outcome == "paid":
        led.mark(cycle_id, "fulfilled", reference or "confirmed-by-operator",
                 "Outcome confirmed manually after an unknown response.")
        print(f"{cycle_id} marked fulfilled; it will be reported on the next pass.")
    elif outcome == "failed":
        led.mark(cycle_id, "failed", "",
                 "Confirmed with the biller that no payment was taken.")
        print(f"{cycle_id} marked failed; it will be reported not_done next pass.")
    else:
        raise SystemExit("outcome must be 'paid' or 'failed'")


def cmd_catalog(adapter: fulfilment.Adapter, argv: list[str]):
    """Read the biller's catalog. This SPENDS 0.01 USDT per call, so it is a
    deliberate command rather than something the loop does on its own — and it is
    how the checkout handoff shape gets discovered in the first place."""
    if not isinstance(adapter, fulfilment.PocketBillsAdapter):
        raise SystemExit("catalog needs FULFILMENT=pocketbills")
    if not argv:
        raise SystemExit("usage: jobber.py catalog <electricity|mobile|"
                         "tv_subscription> [provider_service_id]")
    import json
    result = adapter.catalog(argv[0], argv[1] if len(argv) > 1 else "")
    print(f"[{result.state}] {result.detail}")
    if result.raw:
        print(json.dumps(result.raw, indent=2)[:4000])


def main():
    load_env()
    argv = sys.argv[1:]
    cmd = argv[0] if argv else "once"

    cfg = Config.from_env()
    led = Ledger(cfg.ledger_path)
    mx = ManagerX(cfg.base, cfg.key)
    adapter = fulfilment.build(cfg.fulfilment, endpoint=cfg.pocketbills_endpoint)

    if cmd == "status":
        cmd_status(cfg, mx, led)
    elif cmd == "catalog":
        cmd_catalog(adapter, argv[1:])
    elif cmd == "resolve":
        cmd_resolve(cfg, mx, led, argv[1:])
    elif cmd == "once":
        run_once(cfg, mx, led, adapter)
    elif cmd == "run":
        log(f"reference jobber {VERSION} — polling every {cfg.poll_seconds}s. "
            f"Ctrl-C to stop.")
        while True:
            try:
                run_once(cfg, mx, led, adapter)
            except SystemExit:
                raise
            except Exception as exc:
                log(f"! pass failed: {type(exc).__name__}: {exc}")
            time.sleep(cfg.poll_seconds)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
