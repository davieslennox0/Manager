"""Digest email: plain transactional SMTP, gated off cleanly when SMTP env is
absent (subscriptions are still captured; sends resume once creds are set)."""
import datetime
import json
import smtplib
from email.message import EmailMessage
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


def send_application(to_addr: str, subject: str, body: str, pdf: bytes,
                     pdf_name: str, reply_to: str):
    """One job application: cover letter as the body, tailored CV attached,
    Reply-To the candidate so the employer answers them, not the platform."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_addr
    msg["Reply-To"] = reply_to
    msg.set_content(body)
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=pdf_name)
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


def _skill_hits(skills: list[str], blob: str) -> list[str]:
    """Profile skills present in a listing's text — substring match, but skills
    shorter than 3 chars ('R', 'Go') need word boundaries to avoid noise."""
    hits = []
    words = set(blob.replace("/", " ").replace(",", " ").split())
    for skill in skills:
        s = skill.strip().lower()
        if not s:
            continue
        if (s in blob if len(s) >= 3 else s in words):
            hits.append(skill.strip())
    return hits


def send_job_match_alerts(new_listing_ids: list[str]):
    """Personalized version of the digest: when a listing that just entered the
    board overlaps a user's profile skills, tell them. Opt-out via the
    job_alerts toggle on the profile; a no-op without SMTP creds."""
    if not new_listing_ids or not config.SMTP_ENABLED:
        return
    conn = get_conn()
    qmarks = ",".join("?" * len(new_listing_ids))
    listings = conn.execute(
        f"SELECT * FROM listings WHERE listing_id IN ({qmarks})", new_listing_ids).fetchall()
    users = conn.execute(
        """SELECT p.user_id, p.skills, p.headline, u.email FROM profiles p
           JOIN users u ON u.user_id = p.user_id
           WHERE p.job_alerts = 1 AND p.skills != '[]'""").fetchall()
    conn.close()
    if not listings or not users:
        return

    for user in users:
        skills = [s for s in j(user["skills"], []) if isinstance(s, str)]
        if not skills:
            continue
        matches = []
        for listing in listings:
            blob = " ".join([listing["role"], listing["firm"], listing["ecosystem"],
                             listing["category"], listing["location"],
                             " ".join(j(listing["skills"], []))]).lower()
            hits = _skill_hits(skills, blob)
            if len(hits) >= min(2, len(skills)):
                matches.append((listing, hits))
        if not matches:
            continue
        lines = [f"- {l['role']} @ {l['firm'] or 'unnamed firm'}"
                 + (f" [{l['ecosystem']}]" if l["ecosystem"] else "")
                 + f"\n  matches your skills: {', '.join(h[:5])}"
                 + f"\n  {l['url']}" for l, h in matches[:10]]
        body = ("A role matching your ManagerX profile just hit the board:\n\n"
                + "\n".join(lines)
                + f"\n\nOne-click tailored CV: {config.PUBLIC_BASE_URL}/board"
                + f"\nTurn these alerts off in your profile: {config.PUBLIC_BASE_URL}/profile")
        try:
            _send(user["email"],
                  f"ManagerX: {len(matches)} new role(s) matching your profile", body)
        except Exception:
            continue  # transient SMTP failure — alerts are best-effort


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
