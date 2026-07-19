"""Verified track record: a public, shareable read of the data the platform
already holds — profile spine basics, proof-of-work repos, and every executed
onchain agreement. Read-only over existing tables; nothing here changes how
contracts are signed or stored. Pages are opt-in (profiles.public_profile)."""
import re
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import config
from auth import current_user
from db import get_conn, j

router = APIRouter(prefix="/v1/public", tags=["public"])

HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,29}$")
EXPLORER_TX = "https://www.okx.com/web3/explorer/xlayer/tx/"


class PublicSettingsBody(BaseModel):
    handle: str = ""
    public: bool = False


def _public_user(handle: str):
    conn = get_conn()
    p = conn.execute("SELECT * FROM profiles WHERE handle=? AND public_profile=1",
                     (handle,)).fetchone()
    conn.close()
    if not p:
        raise HTTPException(404, "No public profile at this handle")
    return p


@router.put("/settings")
async def public_settings(body: PublicSettingsBody, user: dict = Depends(current_user)):
    """Claim a handle + flip the public toggle (the one write in this module,
    and it only touches the two profile columns added for this feature)."""
    handle = body.handle.strip().lower()
    if body.public and not handle:
        raise HTTPException(422, "Pick a handle to publish your track record")
    if handle and not HANDLE_RE.match(handle):
        raise HTTPException(422, "Handle: 3-30 chars, lowercase letters/digits/hyphens")
    conn = get_conn()
    if handle:
        taken = conn.execute("SELECT user_id FROM profiles WHERE handle=? AND user_id!=?",
                             (handle, user["user_id"])).fetchone()
        if taken:
            conn.close()
            raise HTTPException(409, "That handle is taken")
    conn.execute("UPDATE profiles SET handle=?, public_profile=? WHERE user_id=?",
                 (handle, 1 if body.public else 0, user["user_id"]))
    conn.commit()
    conn.close()
    return {"handle": handle, "public": body.public,
            "url": f"{config.PUBLIC_BASE_URL}/u/{handle}" if body.public and handle else ""}


@router.get("/{handle}")
async def public_profile(handle: str):
    p = _public_user(handle)
    conn = get_conn()
    contracts = conn.execute(
        """SELECT w.entry_id, w.title, w.counterparty, w.start_date, w.end_date,
                  w.tx_hash, w.doc_hash, w.chain_agreement_id, w.signed_at,
                  a.privacy_mode
           FROM work_history w LEFT JOIN agreements a ON a.agreement_id = w.agreement_id
           WHERE w.user_id=? ORDER BY w.signed_at DESC""", (p["user_id"],)).fetchall()
    cv_count = conn.execute("SELECT COUNT(*) c FROM cvs WHERE user_id=?",
                            (p["user_id"],)).fetchone()["c"]
    gh = conn.execute("SELECT username, repos FROM github_accounts WHERE user_id=?",
                      (p["user_id"],)).fetchone()
    wallet = conn.execute("SELECT activity FROM wallets WHERE user_id=?",
                          (p["user_id"],)).fetchone()
    conn.close()

    repos = []
    if gh:
        repos = [{k: r[k] for k in ("full_name", "description", "language",
                                    "stars", "pushed_at", "url", "pinned")}
                 for r in j(gh["repos"], [])[:6]]
    activity = j(wallet["activity"], {}) if wallet else {}
    return {
        "handle": handle,
        "full_name": p["full_name"], "headline": p["headline"],
        "location": p["location"], "links": j(p["links"], []),
        "stats": {"contracts_completed": len(contracts), "cvs_tailored": cv_count,
                  "dao_votes": activity.get("dao_votes", 0)},
        "claim": (f"{len(contracts)} contract{'s' if len(contracts) != 1 else ''} "
                  f"completed, onchain, zero disputes") if contracts else "",
        "github": {"username": gh["username"], "top_repos": repos} if gh else None,
        "contracts": [{
            "entry_id": c["entry_id"], "title": c["title"],
            "firm": c["counterparty"], "start": c["start_date"], "end": c["end_date"],
            "signed_at": str(c["signed_at"]), "privacy_mode": c["privacy_mode"],
            "tx_hash": c["tx_hash"], "tx_url": EXPLORER_TX + c["tx_hash"],
            "chain_agreement_id": c["chain_agreement_id"],
            "card_url": f"{config.PUBLIC_BASE_URL}/v1/public/{handle}/card/{c['entry_id']}.svg",
        } for c in contracts],
    }


_CARD_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="800" height="418" viewBox="0 0 800 418">
  <rect width="800" height="418" rx="18" fill="#0e0d0b"/>
  <rect x="1.5" y="1.5" width="797" height="415" rx="17" fill="none" stroke="#2b2820" stroke-width="3"/>
  <text x="48" y="72" font-family="Helvetica,Arial,sans-serif" font-size="26" font-weight="bold" fill="#ffffff">Manager<tspan fill="#8a8578">X</tspan></text>
  <text x="752" y="72" text-anchor="end" font-family="Helvetica,Arial,sans-serif" font-size="16" fill="#8a8578">Verified track record</text>
  <text x="48" y="175" font-family="Helvetica,Arial,sans-serif" font-size="38" font-weight="bold" fill="#ffffff">{role}</text>
  <text x="48" y="215" font-family="Helvetica,Arial,sans-serif" font-size="24" fill="#b5b0a1">{firm}</text>
  <text x="48" y="252" font-family="Helvetica,Arial,sans-serif" font-size="17" fill="#8a8578">{period}</text>
  <g transform="translate(48,296)">
    <rect width="272" height="44" rx="22" fill="#123a22"/>
    <circle cx="24" cy="22" r="12" fill="#22c55e"/>
    <path d="M18 22 l4.5 4.5 L30.5 17" stroke="#0e0d0b" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
    <text x="44" y="28" font-family="Helvetica,Arial,sans-serif" font-size="17" font-weight="bold" fill="#4ade80">Executed onchain · X Layer</text>
  </g>
  <text x="48" y="384" font-family="Courier,monospace" font-size="15" fill="#8a8578">tx {tx_short}</text>
  <text x="752" y="384" text-anchor="end" font-family="Helvetica,Arial,sans-serif" font-size="15" fill="#8a8578">managerx.xyz/u/{handle}</text>
</svg>"""


@router.get("/{handle}/card/{entry_id}.svg")
async def proof_card(handle: str, entry_id: str):
    """One shareable proof card per completed contract — self-contained SVG."""
    p = _public_user(handle)
    conn = get_conn()
    c = conn.execute("SELECT * FROM work_history WHERE entry_id=? AND user_id=?",
                     (entry_id, p["user_id"])).fetchone()
    conn.close()
    if not c:
        raise HTTPException(404, "No such contract on this profile")
    period = " – ".join(x for x in (c["start_date"], c["end_date"]) if x) \
        or str(c["signed_at"])[:10]
    tx = c["tx_hash"]
    svg = _CARD_TEMPLATE.format(
        role=escape(c["title"][:44]), firm=escape((c["counterparty"] or "—")[:52]),
        period=escape(period[:60]), handle=escape(handle),
        tx_short=escape(f"{tx[:14]}…{tx[-8:]}" if len(tx) > 26 else tx))
    return Response(svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=300",
                             "Content-Disposition":
                             f'inline; filename="managerx-proof-{entry_id}.svg"'})
