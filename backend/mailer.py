"""Digest email: plain transactional SMTP, gated off cleanly when SMTP env is
absent (subscriptions are still captured; sends resume once creds are set)."""
import datetime
import json
import smtplib
from email.mime.text import MIMEText

import config
from db import get_conn, j

REMINDER_WINDOW_DAYS = 14   # deadlines this close get an email
REMINDER_COOLDOWN_DAYS = 7  # per document, at most one reminder a week


def _matches(listing, filters: dict) -> bool:
    if not filters:
        return True
    blob = " ".join([listing["role"], listing["firm"], listing["ecosystem"],
                     listing["location"], " ".join(j(listing["skills"], []))]).lower()
    eco = (filters.get("ecosystem") or "").lower()
    if eco and eco not in blob:
        return False
    if filters.get("newly_funded") and not listing["newly_funded"]:
        return False
    role_kw = [k.lower() for k in filters.get("role_keywords", []) if k]
    if role_kw and not any(k in listing["role"].lower() for k in role_kw):
        return False
    kw = [k.lower() for k in filters.get("keywords", []) if k]
    if kw and not any(k in blob for k in kw):
        return False
    return True


def _send(to_addr: str, subject: str, body: str):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_addr
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.send_message(msg)


def send_digests(new_listing_ids: list[str]):
    """Called from the scanner tick with the ids that are new this pass."""
    if not new_listing_ids:
        return
    conn = get_conn()
    qmarks = ",".join("?" * len(new_listing_ids))
    listings = conn.execute(
        f"SELECT * FROM listings WHERE listing_id IN ({qmarks})", new_listing_ids).fetchall()
    subs = conn.execute("SELECT * FROM subscriptions WHERE active = 1").fetchall()
    conn.close()
    if not subs:
        return

    sent = []
    for sub in subs:
        filters = j(sub["filters"], {})
        hits = [l for l in listings if _matches(l, filters)]
        if not hits:
            continue
        lines = [f"- {l['role']} @ {l['firm']}"
                 + (f" [{l['ecosystem']}]" if l["ecosystem"] else "")
                 + (f" ({l['location']})" if l["location"] else "")
                 + f"\n  {l['url']}" for l in hits[:25]]
        body = ("New listings matching your ManagerX filters:\n\n" + "\n".join(lines)
                + f"\n\nBrowse + one-click tailored CV: {config.PUBLIC_BASE_URL}/board"
                + f"\nUnsubscribe: {config.PUBLIC_BASE_URL}/api/unsubscribe/{sub['sub_id']}")
        if config.SMTP_ENABLED:
            try:
                _send(sub["email"], f"ManagerX: {len(hits)} new matching listing(s)", body)
                sent.append(sub["sub_id"])
            except Exception:
                continue  # transient SMTP failure — next tick's digest catches up
    if sent:
        conn = get_conn()
        qmarks = ",".join("?" * len(sent))
        conn.execute(f"UPDATE subscriptions SET last_digest_at=CURRENT_TIMESTAMP "
                     f"WHERE sub_id IN ({qmarks})", sent)
        conn.commit()
        conn.close()


def send_deadline_reminders():
    """Email users whose vault documents have obligations coming due (probation
    ends, offer expiries, contract ends). Rides the scanner tick; a no-op
    without SMTP creds, and each document reminds at most once per cooldown."""
    if not config.SMTP_ENABLED:
        return
    today = datetime.date.today()
    conn = get_conn()
    rows = conn.execute(
        """SELECT d.*, u.email FROM documents d JOIN users u ON u.user_id = d.user_id
           WHERE d.deadlines != '[]' AND (d.last_reminded_at IS NULL OR
           strftime('%s','now') - strftime('%s', d.last_reminded_at) >= ?)""",
        (REMINDER_COOLDOWN_DAYS * 86400,)).fetchall()
    conn.close()

    reminded = []
    for row in rows:
        due = []
        for d in j(row["deadlines"], []):
            try:
                date = datetime.date.fromisoformat(str(d.get("date", "")))
            except ValueError:
                continue
            days = (date - today).days
            if 0 <= days <= REMINDER_WINDOW_DAYS:
                due.append(f"- {d.get('label', 'Deadline')}: {date.isoformat()} "
                           f"({'today' if days == 0 else f'in {days} day(s)'})")
        if not due:
            continue
        name = row["filename"] or f"{row['kind']} document"
        body = (f"Upcoming obligations from “{name}” in your ManagerX vault:\n\n"
                + "\n".join(due)
                + f"\n\nReview the document: {config.PUBLIC_BASE_URL}/documents")
        try:
            _send(row["email"], f"ManagerX: {len(due)} deadline(s) coming up", body)
            reminded.append(row["doc_id"])
        except Exception:
            continue  # transient SMTP failure — next pass retries
    if reminded:
        conn = get_conn()
        qmarks = ",".join("?" * len(reminded))
        conn.execute(f"UPDATE documents SET last_reminded_at=CURRENT_TIMESTAMP "
                     f"WHERE doc_id IN ({qmarks})", reminded)
        conn.commit()
        conn.close()
