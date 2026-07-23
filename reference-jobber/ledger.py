"""The jobber's own memory of what it has already paid for.

This exists because of one hazard, and the whole design of the agent follows from
it: fulfilling a cycle moves real money at the biller, and reporting that cycle to
ManagerX is a separate network call. If the process dies between the two, a naive
agent that just re-reads its pending cycles from ManagerX will pay the same bill
again. ManagerX cannot protect against this — it never sees the payment — so the
agent has to remember for itself, locally, before it acts.

Hence: write the intent down BEFORE calling the biller, and never let the record
be recreated from remote state.

States, and why each exists:

  attempting  We called the biller and never heard back. The money may or may not
              have moved. This is the only state that is not safe to act on, and
              the agent deliberately will NOT retry it — it parks it for a human.
              Silently retrying an unknown payment is how you double-pay someone.
  fulfilled   The biller confirmed. Safe to report to ManagerX, and safe to report
              again if that call failed the first time.
  failed      The biller gave a definite no, with no money moved. Safe to retry
              later, or to report as not_done.
  reported    ManagerX has the outcome. The cycle is closed as far as we care.
"""
import sqlite3
import datetime
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS cycle_work (
    cycle_id    TEXT PRIMARY KEY,
    gig_id      TEXT NOT NULL,
    state       TEXT NOT NULL,
    reference   TEXT NOT NULL DEFAULT '',
    detail      TEXT NOT NULL DEFAULT '',
    started_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cycle_work_state ON cycle_work (state);

CREATE TABLE IF NOT EXISTS claims (
    gig_id      TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    claimed_at  TEXT NOT NULL
);
"""

UNSAFE = "attempting"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class Ledger:
    def __init__(self, path: str):
        self.path = path
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── cycle work ───────────────────────────────────────────────────────────

    def get(self, cycle_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM cycle_work WHERE cycle_id = ?",
                               (cycle_id,)).fetchone()
        return dict(row) if row else None

    def begin(self, cycle_id: str, gig_id: str) -> bool:
        """Claim the right to fulfil this cycle. Returns False if a record already
        exists — meaning some earlier run already got at least as far as calling
        the biller, and this run must not call it again."""
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO cycle_work (cycle_id, gig_id, state, started_at, "
                    "updated_at) VALUES (?, ?, ?, ?, ?)",
                    (cycle_id, gig_id, UNSAFE, _now(), _now()))
            return True
        except sqlite3.IntegrityError:
            return False

    def mark(self, cycle_id: str, state: str, reference: str = "", detail: str = ""):
        with self._conn() as conn:
            conn.execute(
                "UPDATE cycle_work SET state = ?, reference = ?, detail = ?, "
                "updated_at = ? WHERE cycle_id = ?",
                (state, reference[:200], detail[:1000], _now(), cycle_id))

    def in_state(self, state: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM cycle_work WHERE state = ? "
                                "ORDER BY updated_at", (state,)).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute("SELECT state, COUNT(*) c FROM cycle_work "
                                "GROUP BY state").fetchall()
        return {r["state"]: r["c"] for r in rows}

    # ── claims ───────────────────────────────────────────────────────────────

    def record_claim(self, gig_id: str, title: str):
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO claims (gig_id, title, claimed_at) "
                         "VALUES (?, ?, ?)", (gig_id, title, _now()))

    def has_claimed(self, gig_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM claims WHERE gig_id = ?",
                               (gig_id,)).fetchone()
        return row is not None
