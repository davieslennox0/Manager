"""SQLite (WAL) storage. The schema is the product's data spine: one profile per
user holds base experience/skills; every per-job artifact (tailored CV, work
agreement) references it rather than duplicating qualifications, and executed
agreements feed back into it as verified work history."""
import json
import sqlite3

from config import DATABASE_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'user',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- The data spine: one row per user, everything else references it.
CREATE TABLE IF NOT EXISTS profiles (
    user_id     TEXT PRIMARY KEY REFERENCES users(user_id),
    full_name   TEXT NOT NULL DEFAULT '',
    headline    TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    links       TEXT NOT NULL DEFAULT '[]',   -- JSON [{label, url}]
    summary     TEXT NOT NULL DEFAULT '',
    skills      TEXT NOT NULL DEFAULT '[]',   -- JSON [str]
    experience  TEXT NOT NULL DEFAULT '[]',   -- JSON [{title, org, start, end, bullets[]}]
    education   TEXT NOT NULL DEFAULT '[]',   -- JSON [{degree, school, year}]
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Verified track record: written ONLY from fully-executed onchain agreements.
CREATE TABLE IF NOT EXISTS work_history (
    entry_id     TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    agreement_id TEXT NOT NULL,
    title        TEXT NOT NULL,
    counterparty TEXT NOT NULL DEFAULT '',
    scope        TEXT NOT NULL DEFAULT '[]',  -- JSON [str] scope-of-work clauses
    start_date   TEXT NOT NULL DEFAULT '',
    end_date     TEXT NOT NULL DEFAULT '',
    doc_hash     TEXT NOT NULL,
    tx_hash      TEXT NOT NULL,
    chain_agreement_id INTEGER,
    signed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- One row per job a user works: pasted posting or a scanner listing they picked.
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id),
    source      TEXT NOT NULL DEFAULT 'pasted',      -- pasted | listing
    listing_id  TEXT,
    url         TEXT NOT NULL DEFAULT '',
    raw_text    TEXT NOT NULL DEFAULT '',
    parsed      TEXT NOT NULL DEFAULT '{}',          -- JSON {role, firm, skills[], seniority, tone, language}
    status      TEXT NOT NULL DEFAULT 'parsed',      -- parsed | cv_ready | accepted | contracted
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Per-job tailored CV: structured JSON so review/edit round-trips cleanly.
CREATE TABLE IF NOT EXISTS cvs (
    cv_id       TEXT PRIMARY KEY,
    job_id      TEXT UNIQUE NOT NULL REFERENCES jobs(job_id),
    user_id     TEXT NOT NULL REFERENCES users(user_id),
    content     TEXT NOT NULL,                       -- JSON CV document
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agreements (
    agreement_id TEXT PRIMARY KEY,
    job_id      TEXT UNIQUE NOT NULL REFERENCES jobs(job_id),
    user_id     TEXT NOT NULL REFERENCES users(user_id),
    content     TEXT NOT NULL,                       -- JSON {title, parties[], scope[], payment, duration, ...}
    doc_hash    TEXT NOT NULL DEFAULT '',
    privacy_mode TEXT NOT NULL DEFAULT 'HASH_ONLY',  -- HASH_ONLY | WITH_METADATA
    signers     TEXT NOT NULL DEFAULT '[]',          -- JSON [checksum addresses]
    chain_agreement_id INTEGER,
    create_tx   TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'draft',       -- draft | pending_signatures | executed
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    executed_at TIMESTAMP
);

-- ── Scanner ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sources (
    source_id   TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,                       -- greenhouse | lever | rss | scrape
    name        TEXT NOT NULL,
    target      TEXT NOT NULL,                       -- org slug (greenhouse/lever) or URL (rss/scrape)
    poll_seconds INTEGER NOT NULL DEFAULT 3600,
    last_polled TIMESTAMP,
    last_error  TEXT,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS listings (
    listing_id  TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL REFERENCES sources(source_id),
    external_id TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL,
    firm        TEXT NOT NULL DEFAULT '',
    ecosystem   TEXT NOT NULL DEFAULT '',            -- chain/ecosystem tag when detectable
    comp_range  TEXT NOT NULL DEFAULT '',
    skills      TEXT NOT NULL DEFAULT '[]',          -- JSON [str]
    remote      TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL,
    posted_at   TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,                      -- dedup key across sources
    first_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active      INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_listings_hash ON listings(content_hash);
CREATE INDEX IF NOT EXISTS idx_listings_seen ON listings(last_seen);

CREATE TABLE IF NOT EXISTS subscriptions (
    sub_id      TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    filters     TEXT NOT NULL DEFAULT '{}',          -- JSON {ecosystem?, role_keywords[]?, keywords[]?}
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_digest_at TIMESTAMP,
    active      INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subs_email_filters ON subscriptions(email, filters);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()


def j(row_value: str, default):
    """Tolerant JSON column read."""
    try:
        return json.loads(row_value)
    except (TypeError, ValueError):
        return default
