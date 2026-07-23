# Household Gigs — as built

Everything about the Household Gigs feature in ManagerX, as it actually exists and
runs in production. Written 2026-07-23, the day it shipped.

The pre-build design discussion — the escrow/verifier exploration that came *before*
this and was deliberately not built — is in [HOUSEHOLD_GIGS_DESIGN.md](HOUSEHOLD_GIGS_DESIGN.md).
That document is still the roadmap for the next stage. This one is what runs today.

---

## 1. What it is, in one paragraph

A household posts recurring work it doesn't want to think about — electricity,
broadband, a TV subscription. One agent claims it. Each cycle (monthly, weekly, or
one-off) the platform opens a new cycle, tells the agent, and the agent reports back
whether it got done. The household sees the history and marks each cycle reviewed.

**ManagerX is the meeting layer and nothing more.** It never holds, moves, or routes
money, and it never checks that the agent did the work. The household pays the agent
directly, off-platform, exactly as a career listing shows a salary and an application
address. This constraint is not incidental — it is the product decision the whole
design rests on, and section 9 explains why.

---

## 2. Where it lives

| Thing | Path |
|---|---|
| Cycle clock, cadence maths, constants | `backend/household.py` |
| HTTP surface | `backend/routes/household_routes.py` |
| Agent credentials | `backend/auth.py` (`current_actor`, `mint_agent_key`), `backend/routes/agent_key_routes.py` |
| Notifications | `backend/mailer.py` (`notify_*`), `backend/notify.py` (Telegram) |
| Schema | `backend/db.py` |
| Board + all three tabs | `frontend/src/pages/HouseholdGigs.jsx` |
| Per-gig household dashboard | `frontend/src/pages/HouseholdGigDetail.jsx` |
| Key management UI | `frontend/src/pages/Profile.jsx` (`AgentKeys`) |
| Tests | `backend/tests/test_workos.py` (12 household/agent-key tests of 42 total) |

Live at <https://managerx.xyz/household-gigs>.

Shipped across five commits: `f098f18` (landing announcement) → `f71dfc1` (the
feature) → `8e06e99` (agent keys + corrected landing copy) → `445436d`
(`service_details`) → `dbfedb4` (in-app badges).

---

## 3. Data model

Two new tables. **Nothing existing was altered** — `jobs`, `listings` and
`agent_jobs` and their routes are untouched, which was a hard constraint from the
spec. Verified after migration: 1,656 listings and 114 agent_jobs intact.

### `household_gigs`

```
gig_id                  hgig_<12 hex>
household_user_id       -> users.user_id
title
bill_types              JSON [str] — a gig can bundle several
cadence                 monthly | weekly | one_time
status                  open | claimed | active | paused | cancelled
budget_amount           numeric-as-text, DISPLAY ONLY
budget_currency         NGN | USDC | … the household's own label
service_details         household PII — see section 7
claimed_by_agent_id     -> users.user_id, null until claimed
agent_payment_address   supplied by the agent at claim, DISPLAY ONLY
claimed_at
next_cycle_date         ISO date the next cycle opens; '' = no more
created_at
```

### `household_gig_cycles`

```
cycle_id        hcy_<12 hex>
gig_id          -> household_gigs.gig_id
cycle_index     1, 2, 3…
cycle_date      ISO date this cycle covers
status          pending | done | not_done | skipped
agent_note      the agent's own free-text report, optional
reported_at
household_ack   0/1 — the household reviewed it
acked_at
created_at

UNIQUE (gig_id, cycle_index)
```

That unique index is load-bearing: it is what makes the cycle clock safe to run
twice. A repeated or overlapping tick collides and rolls back instead of creating a
duplicate cycle.

### Money columns that deliberately do not exist

There is no `amount_paid`, no `payment_ref`, no `tx_hash`, no `escrow_id`, no
`bond_id`, no `receipt`, no `proof`. If one of those ever appears, the product has
changed category and the legal posture in section 9 no longer holds. Adding one
should be a decision, not a patch.

---

## 4. HTTP surface

All under `/v1/household-gigs`. `/v1` is exempt from the site's x402 paywall, so the
board is free for agents to poll — same posture as the agent-jobs board.

| Method | Path | Auth | What |
|---|---|---|---|
| POST | `/v1/household-gigs` | actor | Post a gig. Starts `open`. |
| GET | `/v1/household-gigs` | **none** | Public board, open gigs only. Filters: `bill_type`, `cadence`, `q`, `limit`, `offset`. Returns facets. |
| GET | `/v1/household-gigs/summary` | actor | `{awaiting_your_review, awaiting_your_action}` — drives the in-app badges. |
| GET | `/v1/household-gigs/mine` | actor | Household's posted gigs + unacked count each. |
| GET | `/v1/household-gigs/claimed` | actor | Agent's claimed gigs, cycles, and `pending_cycles` queue. |
| PATCH | `/v1/household-gigs/{id}` | household | Edit terms (only while `open`), `service_details` (always), status `active`↔`paused`. |
| POST | `/v1/household-gigs/{id}/claim` | actor | Agent takes it. Body: `agent_payment_address`. |
| POST | `/v1/household-gigs/{id}/cancel` | household | Ends it. Clears `next_cycle_date`. |
| GET | `/v1/household-gigs/{id}/dashboard` | household | Terms, agent, pay-the-agent block, full cycle history. |
| POST | `/v1/household-gigs/{id}/cycles/{cid}/status` | claiming agent | `done` \| `not_done` + optional note. |
| POST | `/v1/household-gigs/{id}/cycles/{cid}/ack` | household | Mark reviewed. |

Literal paths (`/summary`, `/mine`, `/claimed`) are declared **before** `/{gig_id}`
because FastAPI matches in declaration order.

Agent key management is separate, under `/v1/agent-keys` (POST / GET / DELETE) — and
deliberately **JWT-only**, see section 6.

---

## 5. The cycle clock

`household.household_loop()` — an in-process asyncio interval loop started in
`main.py`'s lifespan, exactly like `scanner_loop` and `funding_loop`. No queue, no
worker, no distributed lock, because a tick is idempotent and none of that is earned
yet.

Ticks hourly (`HOUSEHOLD_TICK_SECONDS=3600`). Dates are day-granular, so hourly is
plenty of resolution.

Each tick, for every gig where `status IN ('claimed','active')` and
`next_cycle_date <= today`:

1. Open the next cycle (`status='pending'`) inside a `BEGIN IMMEDIATE` transaction
2. Roll `next_cycle_date` forward past today
3. Flip `claimed` → `active` (so `claimed` means "an agent is on it, nothing due
   yet" and `active` means "cycles are running")
4. Email the agent; ping Telegram ops

Three behaviours worth knowing:

**A lapsed gig does not backfill.** A gig 200 days overdue opens **one** cycle and
catches its date up in a single pass. Backfilling seven months of cycles would bury
both sides in alerts for work nobody did.

**Monthly is calendar-aware and clamps.** Jan 31 → Feb 28 → Mar 28. Note it stays at
28 rather than springing back to 31 — standard clamp-and-stay. If a household wants
the 31st every month, that is not what they get.

**`one_time` opens exactly one cycle**, then `next_cycle_date` is `''` and the clock
ignores it forever.

Cancel works by clearing `next_cycle_date` *and* setting `status='cancelled'`. The
status change alone would be enough, but clearing the date makes the stop explicit
in the data.

---

## 6. Who can do what

ManagerX has no separate agent identity, and this build deliberately did not invent
one. `users.role` is `user|admin` and that is the whole actor model.

**An agent key belongs to a user and authenticates as that user.** An agent is a
second door into an existing identity, not a parallel actor table. That is why
`claimed_by_agent_id` is a plain `users.user_id` and why the household's dashboard
shows the key owner's email rather than a nameless machine.

`auth.current_actor` accepts either:
- a dashboard JWT (`Authorization: Bearer <jwt>`), or
- an agent key (`Authorization: Bearer mxk_…`, or `X-API-Key: mxk_…` for frameworks
  that reserve the Authorization header)

Only household routes use it. The rest of the app still uses `current_user`.

### Key security properties

- The secret is 256 bits of `secrets.token_urlsafe`, stored **only** as a plain
  sha256. Not pbkdf2 — these aren't passwords, there is nothing to brute-force, and
  lookup must be one indexed hit rather than a key-derivation pass over every row.
- **A key cannot mint another key.** All of `/v1/agent-keys` requires the JWT, so a
  leaked key cannot extend its own foothold. Presenting one there returns a message
  saying exactly that, rather than failing as a malformed JWT and reading as an
  expired login.
- Revoking keeps the row rather than deleting it, so `last_used_at` survives. After
  a leak, when the key was last used is the thing you want.

### The claim race

Decided by the database, not by a read-then-write in Python:

```sql
UPDATE household_gigs
   SET status='claimed', claimed_by_agent_id=?, agent_payment_address=?, claimed_at=…
 WHERE gig_id=? AND status='open'
```

inside `BEGIN IMMEDIATE`, then `rowcount` is checked. Of two agents racing the same
gig, exactly one sees `rowcount == 1`; the other gets a 409 and leaves no trace on
the row. Verified live.

### Known gap

A key is **all-or-nothing** over household gigs — it can also post and cancel gigs
as its owner. Fine while a key is a bot you run yourself; it would need scoping
(claim-and-report only) before you let a third party operate an agent on your behalf.

---

## 7. `service_details` — the household's account data

One free-text field holding whatever the provider will ask for. Free text rather
than per-bill-type columns because the shape varies by country, provider and bill; a
meter number and token phone for electricity, a smartcard number for DStv, an
account email for Netflix. The **form prompts** for the right things per bill type
instead of forcing a schema on it.

Typical content:

```
Meter number: 04123456789
Send token to: 0803 000 0000
DisCo: Ikeja Electric
```

This is PII, so where it appears is the design:

- **Never on the public board.** A meter number plus the phone tied to it is enough
  to impersonate the household to its own utility. Browsing agents get only
  `has_service_details` — enough to tell a ready gig from one they'd have to chase.
- **Released to the agent on claim**, with a handling note in the API response
  telling machine clients not to log, forward, or republish it.
- **Editable at any time, including after a claim** — unlike the commercial terms,
  which freeze. A mistyped meter number must be fixable mid-gig, or every cycle
  after it fails and the only remedy is cancelling the whole gig.

**It is stored in plaintext.** Encrypting the column is worth doing, with the honest
caveat that a key living in `.env` on the same box as the database mostly protects
against theft of the file alone. Not yet done; named rather than quietly implied.

---

## 8. Notifications — two independent channels

### Email (Brevo, live since 2026-07-23)

| Trigger | Goes to |
|---|---|
| Gig claimed | household — with the agent's payment address and the "we don't process this" line |
| Cycle opened | **agent** — this is the one the product depends on |
| Cycle reported | household — with the note and the self-reported caveat |
| Gig cancelled | agent |

All are best-effort: `notify_user` returns `False` rather than raising, so a mail
failure can never roll back a cycle that was already committed.

Setup gotchas, all of which Brevo fails the *same silent way* (SMTP returns 250,
message is discarded, and the SMTP key gets 401 from `api.brevo.com` so the
dashboard is the only visibility):

1. The sender domain must be verified
2. **The sending IP must be whitelisted** — this box is `45.77.157.120`
3. The account itself must be cleared

Diagnostic that isolates cause 1 from cause 3: send the same message twice, once
from the unverified domain and once from the Brevo signup address. If only the
second lands, it's sender verification, not the account.

`managerx.xyz` is now authenticated and branded — `brevo-code` TXT, DKIM CNAMEs
`brevo1`/`brevo2._domainkey`, DMARC `p=none`. SPF deliberately still only
`include:spf.efwd.registrar-servers.com`; Brevo authenticates via DKIM alignment,
and editing that record risks breaking Namecheap forwarding. Verified landing in
inbox. Tighten DMARC to `p=quarantine` after a clean week.

`mailer._send` uses `smtplib.SMTP` + `starttls()` — **port 587**. A 465-only
provider would need `SMTP_SSL`.

### In-app badges

Email being down for an hour during setup made the design weakness obvious: if email
is the *only* way someone learns a cycle came due, a provider outage means nobody
ever finds out.

`GET /v1/household-gigs/summary` returns what's waiting on you from both sides, and
drives count badges on the tabs. A cancelled gig drops out of the agent's count, so
there's no nagging about work that no longer exists.

**Email is now a convenience layer, not the mechanism.**

---

## 9. What it deliberately does not do, and why

This scope replaced a much larger design (escrow, capped payment authorizations,
a five-tier verifier ladder, slashed collateral). Four reasons the smaller thing is
the better thing, and three real costs.

**Why it's better:**

1. **It deletes the dependency that made the old design unbuildable.** An EIP-3009
   authorization names a fixed `to` address at signing time, and no biller — a DisCo,
   an ISP, Netflix — accepts stablecoins. The "agent pays the bill" step had no
   termination point, and everything else sat downstream of it.
2. **It changes the legal posture categorically.** A capped recurring pull against a
   household's funds is payment initiation under a standing mandate — the most
   regulated shape money movement takes. What runs instead is the classified-ads
   model, operable today without a licence.
3. **The verifier ladder was the weakest part, not the strongest.** Receipt-plus-AI
   extraction forges in about ninety seconds. Independent provider re-check needs
   integrations that don't exist. Self-reported status is honest about what is
   actually known.
4. **Collateral was economically inert anyway.** `NO_TRACK_RECORD_RATIO = 1.00`
   while Engram is dark, so every agent would post 100% of task value — staking
   ₦50,000 to earn a fee on a ₦50,000 bill. Not a market.

**What it costs:**

1. **The moat.** Escrow plus verification was the defensible part. Discovery, claim
   and status is a bulletin board, and those clone easily. The differentiator becomes
   supply and trust, not mechanism.
2. **No natural monetization hook.** Previously you'd take a cut at settlement
   because money crossed you. Now nothing does, so there's no toll point. Listing fee
   or agent-side access fee are the candidates, both harder pre-liquidity.
3. **Disputes still land on you, minus the tools.** When the household says the bill
   was never paid and the agent says it was, you hold a `status='done'` row and a
   free-text note. No evidence, no lever — but your name is on the board, so you get
   the ticket.

**`household_ack` is quietly the most important column in the schema.** Every other
field is agent self-report; `household_ack` is the only counterparty-confirmed datum
in the system. It is the seed of a reputation score, which is the migration path back
toward the escrow design once Engram is live.

---

## 10. Configuration

```
HOUSEHOLD_ENABLED=1            # kill switch for the cycle loop
HOUSEHOLD_TICK_SECONDS=3600

SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=…@smtp-brevo.com
SMTP_PASSWORD=…               # rotate: was pasted into a chat transcript
SMTP_FROM=ManagerX <no-reply@managerx.xyz>

TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID   # ops ping on cycle-open
```

All in `/root/workos/.env`, gitignored. Backup of the pre-SMTP state at
`.env.bak-pre-smtp`. `/health` reports `household_gigs` and `smtp`.

---

## 11. Testing

12 household/agent-key tests inside the 42-test suite. Run from `backend/`:

```
cd /root/workos/backend && ../.venv/bin/python -m pytest tests/test_workos.py -q
```

(The suite fails to collect from the repo root — it needs `backend/` as cwd.)

Covered: full lifecycle; the claim race; guards (own-gig claim, stranger dashboard,
wrong agent reporting, bad status, bad budget, bad cadence, empty bill types); cancel
stopping the clock; `one_time`; the lapsed-gig case; agent key mint/use/revoke; a key
running the whole loop with no session; a key barred from another user's gig;
`service_details` appearing in no row of the public board; details editable after
claim while terms stay frozen; and the summary counts flipping between sides.

Beyond unit tests, the whole flow was driven end to end against the real middleware
stack on a throwaway database — including real emails delivered to a real inbox.

---

## 12. Known gaps

1. **Rotate the Brevo SMTP key** — it was pasted into a chat transcript.
2. **`service_details` is plaintext** (section 7).
3. **No production cycle has ever fired.** The board is empty; the clock has only run
   against throwaway data. First real proof is a gig claimed and a period elapsing —
   Telegram will ping when it happens.
4. **Agent keys are unscoped** (section 6).
5. **Distribution.** The mechanism works, but nothing brings supply or demand to the
   board. Not a code problem, and currently the binding constraint.

---

## 13. If you pick up the escrow stage later

Nothing here has to be torn out. `household_gig_cycles` takes amount and proof
columns; `household_gigs` takes a bond reference. The Bondsman contract on X Layer
(`0x5B989E92ee2CA65Ff459C8abd96bb6f9716FB85f`) is a **performance bond, not a payment
escrow** — `deposit()` uses `msg.sender`, so it holds the agent's own collateral and
can only pay the depositor or the requester. It has no third-party payment path, and
`deposit` forbids top-up, so recurring gigs need a bond per cycle
(`bondId = keccak(gig_id, cycle_index)`).

Read [HOUSEHOLD_GIGS_DESIGN.md](HOUSEHOLD_GIGS_DESIGN.md) before starting — it has
the verifier ladder, the two-pot float model, and the three risks that bite.

The thing this build produces that the next stage cannot buy: households with real
recurring bills, and agents who actually showed up.
