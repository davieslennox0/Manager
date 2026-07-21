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
    handle      TEXT NOT NULL DEFAULT '',     -- public track-record URL slug, '' = unset
    public_profile INTEGER NOT NULL DEFAULT 0,
    job_alerts  INTEGER NOT NULL DEFAULT 1,   -- email when a new listing matches the skills
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
    parsed      TEXT NOT NULL DEFAULT '{}',          -- JSON {role, firm, skills[], seniority, tone, language, apply_email}
    status      TEXT NOT NULL DEFAULT 'parsed',      -- parsed | cv_ready | applied | accepted | contracted
    cover_letter TEXT NOT NULL DEFAULT '',           -- for the email application, user-editable
    applied_at  TIMESTAMP,                           -- set when the platform emailed the application
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
    category    TEXT NOT NULL DEFAULT '',            -- Engineering / Design / … (scanner classifier)
    newly_funded INTEGER NOT NULL DEFAULT 0,         -- funding.apply_funded_tags maintains this
    content_hash TEXT NOT NULL,                      -- dedup key across sources
    first_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active      INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_listings_hash ON listings(content_hash);
CREATE INDEX IF NOT EXISTS idx_listings_seen ON listings(last_seen);
CREATE INDEX IF NOT EXISTS idx_listings_category ON listings(category);

CREATE TABLE IF NOT EXISTS subscriptions (
    sub_id      TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    filters     TEXT NOT NULL DEFAULT '{}',          -- JSON {ecosystem?, role_keywords[]?, keywords[]?, newly_funded?}
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_digest_at TIMESTAMP,
    active      INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subs_email_filters ON subscriptions(email, filters);

-- ── Newly-funded pipeline ────────────────────────────────────────────────
-- Firms detected in funding feeds. status flips speculative -> hiring the
-- moment a listing for the firm shows up in the compiled feed.
CREATE TABLE IF NOT EXISTS funded_firms (
    firm_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    normalized  TEXT NOT NULL,                       -- lowercase dedup/matching key
    round       TEXT NOT NULL DEFAULT '',
    amount      TEXT NOT NULL DEFAULT '',
    announced_at TEXT NOT NULL DEFAULT '',
    source_url  TEXT NOT NULL DEFAULT '',
    careers_kind TEXT NOT NULL DEFAULT '',           -- greenhouse | lever | '' none found
    careers_target TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'speculative', -- speculative | hiring
    first_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    careers_checked_at TIMESTAMP,
    active      INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_funded_normalized ON funded_firms(normalized);

-- ── Proof-of-work sources ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS github_accounts (
    user_id     TEXT PRIMARY KEY REFERENCES users(user_id),
    username    TEXT NOT NULL,
    access_token TEXT NOT NULL DEFAULT '',           -- '' = public-data mode (no OAuth)
    repos       TEXT NOT NULL DEFAULT '[]',          -- cached normalized repo list JSON
    fetched_at  TIMESTAMP,
    connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wallets (
    user_id     TEXT PRIMARY KEY REFERENCES users(user_id),
    address     TEXT NOT NULL,                       -- checksummed; ownership proven by signature
    activity    TEXT NOT NULL DEFAULT '{}',          -- cached onchain footprint JSON
    fetched_at  TIMESTAMP,
    connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── Document vault ───────────────────────────────────────────────────────
-- Documents the user RECEIVES (offers, contracts, NDAs): AI-reviewed, hash-
-- anchored onchain by the user alone — no counterparty signature needed.
CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id),
    job_id      TEXT REFERENCES jobs(job_id),        -- optional link to the application it answers
    kind        TEXT NOT NULL DEFAULT 'other',       -- offer | contract | nda | other
    filename    TEXT NOT NULL DEFAULT '',
    raw_text    TEXT NOT NULL,                       -- extracted text (review input)
    doc_hash    TEXT NOT NULL,                       -- 0x sha256 over the uploaded bytes
    review      TEXT NOT NULL DEFAULT '{}',          -- JSON {terms, red_flags[], posting_diff[], summary}
    deadlines   TEXT NOT NULL DEFAULT '[]',          -- JSON [{label, date, note}]
    chain_agreement_id INTEGER,                      -- single-signer SignatureRegistry anchor
    anchor_tx   TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'uploaded',    -- uploaded | reviewed | anchored
    last_reminded_at TIMESTAMP,                      -- deadline-email dedup
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id);

-- Agent Jobs: gigs/bounties an autonomous agent can take (a firm hiring an
-- agent), aggregated from external agent-economy sources. Distinct from the
-- human job `listings` board. One row per (source, external id).
CREATE TABLE IF NOT EXISTS agent_jobs (
    job_id       TEXT PRIMARY KEY,          -- aj_<source>_<external id>
    source       TEXT NOT NULL,             -- superteam | okx | ...
    external_id  TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    reward       TEXT NOT NULL DEFAULT '',  -- numeric-as-text, '' if unset/negotiable
    token        TEXT NOT NULL DEFAULT '',  -- USDC / USDT0 / ...
    chain        TEXT NOT NULL DEFAULT '',
    deadline     TEXT NOT NULL DEFAULT '',  -- ISO date, '' if none
    url          TEXT NOT NULL DEFAULT '',  -- where to view/claim it
    tags         TEXT NOT NULL DEFAULT '[]',-- JSON [str]
    agent_access TEXT NOT NULL DEFAULT '',  -- source's own agent-eligibility hint
    sponsor      TEXT NOT NULL DEFAULT '',
    posted_at    TEXT NOT NULL DEFAULT '',
    first_seen   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_seen ON agent_jobs(last_seen);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_source ON agent_jobs(source);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    # Pre-schema migration: the category column arrived after first deploy, and
    # executescript would otherwise fail on the new index.
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(listings)").fetchall()]
    if cols and "category" not in cols:
        conn.execute("ALTER TABLE listings ADD COLUMN category TEXT NOT NULL DEFAULT ''")
    if cols and "newly_funded" not in cols:
        conn.execute("ALTER TABLE listings ADD COLUMN newly_funded INTEGER NOT NULL DEFAULT 0")
    pcols = [r["name"] for r in conn.execute("PRAGMA table_info(profiles)").fetchall()]
    if pcols and "handle" not in pcols:
        conn.execute("ALTER TABLE profiles ADD COLUMN handle TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE profiles ADD COLUMN public_profile INTEGER NOT NULL DEFAULT 0")
    if pcols and "job_alerts" not in pcols:
        conn.execute("ALTER TABLE profiles ADD COLUMN job_alerts INTEGER NOT NULL DEFAULT 1")
    jcols = [r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    if jcols and "cover_letter" not in jcols:
        conn.execute("ALTER TABLE jobs ADD COLUMN cover_letter TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE jobs ADD COLUMN applied_at TIMESTAMP")
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()


def j(row_value: str, default):
    """Tolerant JSON column read."""
    try:
        return json.loads(row_value)
    except (TypeError, ValueError):
        return default
