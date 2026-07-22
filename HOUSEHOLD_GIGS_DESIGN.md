# Household Gigs — design notes

_Captured during the ManagerX session on 2026-07-22. This is the full text of what
was discussed from the moment the "Household Gigs" prompt was dropped. Say "unleash"
and Claude will drop it back inline; this file is the durable copy._

---

## PART 1 — What the "job board" actually is today (schema reality check)

Before adding anything, the existing structure was inspected. The infra the spec
assumed to reuse mostly does not exist. Three tables that *sound* like a marketplace
but aren't one:

| Table        | Rows  | What it really is |
|--------------|-------|-------------------|
| `listings`   | 1,648 | Career jobs **scraped** from Greenhouse/Lever/RSS. Read-only aggregation, deduped by `content_hash`. Nobody posts to it. |
| `agent_jobs` | 111   | Agent gigs **scraped** from Superteam/dealwork/opentask/x402. Its own docstring: "Discovery only: this board finds work; it does not bid, execute, or pay." |
| `jobs`       | 1     | Not a posting. It's **one user's private application row** — posting → parsed → tailored CV → cover letter → applied_at. |

Concretely:

- **There is no claim mechanic.** `grep -rn claim` returns nothing but unrelated hits.
  Nobody has ever claimed anything, because both boards link out to the source site.
- **There is no escrow in ManagerX.** `grep -rni escrow` across backend + frontend:
  zero hits. SignatureRegistry anchors document hashes — it never holds funds.
- **There is no job runner or queue.** Three in-process `asyncio` interval loops in
  `main.py:40-47` (scanner, funding, balance report). No worker, no retries, no
  dead-letter, no distributed lock.
- **The $0.1 isn't a job-board access fee on claim.** It's x402 per-*request* pricing
  (`x402_setup.py:31`) — 0.1 per page view or API call, stateless, no accounts, no
  refunds. Nothing to hook a claim onto.

The pieces that genuinely exist and are reusable: the **onchain agreement layer**
(SignatureRegistry on X Layer, hash anchoring, single- and multi-signer) plus the
**EIP-3009 payment machinery**.

**Migration verdict:** do NOT put `job_type` on `jobs`. `jobs` is a private CV-pipeline
row (`parsed`, `cover_letter`, `cv_id`, `applied_at`) — essentially zero field overlap
with a household gig, and it's not the table the board reads from. A separate
`household_gigs` table is cleaner and means **zero migration touching career rows**.

---

## PART 2 — Escrow, dashboards, and what's involved (first answer)

### Escrow is the whole build, not a component
A household gig is "an agent spends my money on my electricity bill." That is
categorically different from everything ManagerX does today, which never touches user
funds. Three ways to authorize it:

1. **Custodial escrow** — household deposits to an address/contract you control.
   Simplest to code, worst outcome: you're holding customer funds to pay third parties,
   which is money transmission in most jurisdictions. Avoid.
2. **Pull authorization with a cap (EIP-3009)** — household signs a
   `transferWithAuthorization` per cycle, capped at `budget_cap`, with validity windows.
   You already run exactly this rail for x402 on X Layer. No custody, no new contract,
   no audit. Strongest fit by a wide margin.
3. **Smart-account delegation / session key** (ERC-4337 + spend limits) — household
   delegates capped recurring spend once. Best UX, most engineering.

The honest gap in all three: an authorization proves the household *let you* spend, but
nothing onchain proves the **biller got paid** — the receipt is off-chain from the
provider, so `receipt_ref` is a trust anchor, not a proof. Disputes hang off that.

### Dashboards — three, not one
- **Household**: active gigs, next execution date, budget remaining this cycle,
  execution log with receipts, pause/cancel (instant + unconditional), authorization top-up.
- **Agent/provider**: claimed gigs, upcoming executions, earnings per execution,
  failures needing intervention.
- **Ops (yours)** — non-optional the moment money moves: total authorized vs. spent,
  executions pending/failed, retry queue depth, relayer gas, disputes. Today your only
  ops surface is the daily Telegram balance report; that isn't enough to run recurring
  payments.

### What the spec doesn't mention but decides the build
- **`account_ref` encrypted** — there's no KMS, no encryption-at-rest, no key rotation.
  It's a SQLite file on this box, which is also the live prod server. Storing someone's
  meter number *and* spend authority makes this box a genuine target. Needs envelope
  encryption with the key held outside the DB, minimum.
- **Idempotency** — cron fires twice, you pay the bill twice. Every execution needs a
  `(gig_id, cycle)` lock. #1 way recurring-payment systems lose money.
- **Failure handling** — payment fails at 3am: retry, partial, skip, who eats it?
  Recurring money movement is ~80% failure handling, and none of it exists.
- **Provider integration is the actual product.** Stubbing the settlement API is right
  for a skeleton, but a household gig board that can't really pay Octopus or Sky has no
  value. Most billers have no public API — that's per-provider, open-ended work and it's
  where the moat is.
- **Cadence edge cases** — timezones, month-end (31st in February), cadence drift.
- **KYC/regulation** — recurring third-party bill payment on someone's behalf is
  regulated almost everywhere.

### Positioning note
ManagerX today is a careers/agreements product end to end — the landing page, ASP #7120
under review, all three paid endpoints. Household bill-paying is a different user, a
different trust model, and a different regulator. It's a second product rather than a
feature. Your call, not Claude's.

### Suggested phasing
- **Phase 0 — no money moves.** New `household_gigs` table, board tab + household card
  variant, claim → `active`, a tick loop reusing the existing `asyncio` loop pattern,
  stubbed executor writing `execution_log`, notifications via `mailer.py`. Genuinely
  additive, zero risk to career rows.
- **Phase 1 — real money.** EIP-3009 capped authorization, idempotency locks, encrypted
  `account_ref`, retry/failure semantics, ops dashboard.
- **Phase 2 — real billers.** Open-ended, per provider.

---

## PART 3 — Bondsman as escrow + the verifier (second answer)

The user's direction: build household gigs + a listing portal for users to post those
gigs, use **Bondsman as escrow**, and add a **verifier** that the agent did what it was
meant to. Everything is real money.

### Correction: Bondsman is not a payment escrow — it's a performance bond
Reading `BondsmanEscrow.sol` (live at `0x5B989E92ee2CA65Ff459C8abd96bb6f9716FB85f` on
X Layer 196, owner = operator `0xCf8Dc51BFEc57384A96Bb9B7bb022a7C7A008AfE`):

```solidity
function deposit(bytes32 bondId, address token, uint256 amount) external {
    ...
    bonds[bondId] = Bond({depositor: msg.sender, ...});
    IERC20(token).transferFrom(msg.sender, address(this), amount);
}
```

`msg.sender` is **the agent**, depositing **their own** collateral. Funds exit only
three ways — `release()` → back to depositor, `slash()` → to requester, `splitRelease()`
→ split. **There is no path to pay a third party.** The contract literally cannot pay an
electricity company.

So Bondsman can't hold the household's bill money. What it CAN do is guarantee the
household is made whole if the agent fails. Different half of the problem.

**You need two pots:**

| Pot               | Whose money   | Where it lives                     | Purpose |
|-------------------|---------------|------------------------------------|---------|
| **Bill float**    | Household's   | ⚠️ Undecided — nothing exists yet | Must reach the biller |
| **Performance bond** | Agent's own | ✅ BondsmanEscrow, live `0x5B98…B85f` | Slashed to household if agent fails |

The bond pot is done and running (`bondsman-api` online 9 days, `/health` = ok). The
float pot is the open question — the one with real money in it.

### How you verify the agent actually did it (strongest-first)
Let deterministic tiers handle the routine case so the evaluator only sees genuine
ambiguity.

- **Tier 1 — native onchain proof (no oracle at all).** If the agent pays the biller
  from a known biller address onchain, the transfer *is* the proof: right recipient,
  amount ≤ `budget_cap`, inside the window, confirmed. Fully deterministic. Catch: no
  utility takes USDT0 — only applies via a crypto-native bill-pay rail
  (Bitrefill/Bando-style) or billers you onboard directly. Still the tier to design
  toward — it's the only one that removes the oracle.
- **Tier 2 — independent provider re-check.** Executor pays; then a *separate* code path
  re-queries the provider API for that reference and stores the raw response. The
  separation means a buggy/compromised executor can't just assert success. What real
  bill-pay systems do.
- **Tier 3 — balance delta.** Two facts checkable without trusting the agent: money left
  the float to the expected recipient, and the household's provider balance moved by that
  amount. Fact one alone kills the biggest failure mode — agent takes money, does nothing.
- **Tier 4 — receipt + AI extraction.** Agent uploads a receipt; hash it, anchor via
  SignatureRegistry, extract amount/provider/account last-4/date and check against the
  gig. Reuses `docreview.py`. Catches sloppiness, NOT fraud (receipts forge trivially).
  Evidence in a dispute, never the verifier.
- **Tier 5 — household confirmation window.** N days to dispute; silence = accepted →
  `release`. Dispute → evaluator → `slash` or `splitRelease`. Bondsman already implements
  all of this including timeout auto-resolve (`/v1/internal/resolve-expired`).

**Recommendation:** Tiers 2+3 as the automated verdict, Tier 4 as dispute evidence,
Tier 5 as backstop. Tier 1 becomes reachable only if you go crypto-native on the biller
side.

### Three things that will bite you
1. **The operator key is a single point of failure, and it's shared.**
   `slash(bondId, requester)` takes the recipient as an *argument* and is `onlyOwner`.
   Owner is `0xCf8Dc51…08AfE` — the same key that signs ManagerX x402 settlements,
   anchors Engram, pays gas everywhere. If it leaks, every active bond is drainable.
   Today exposure is capped at collateral in flight; adding household float multiplies
   it. Before real money scales, the escrow owner should be a different key from the hot
   relayer — ideally multisig or timelocked on `slash`.
2. **Collateral is currently 100% of task value.** `engram_bridge.get_engram_score()`
   returns `None` unconditionally (Engram isn't live); `collateral.py` treats that as
   `NO_TRACK_RECORD_RATIO = 1.00`. For a £100 bill the agent locks £100 to earn a small
   fee. Hard economics until Engram ships and the ratio can drop.
3. **Bond per cycle, not per gig.** `deposit` requires `bonds[bondId].amount == 0` — one
   deposit per bondId, no top-up. For recurring gigs that's a clean fit:
   `bondId = keccak(gig_id, cycle_index)`, each cycle bonded to its own `budget_cap`.

### The float decision (chosen: EIP-3009 capped pull)
The household's bill money should be held via an **EIP-3009 capped pull**: household
signs a per-cycle `transferWithAuthorization` capped at `budget_cap`, presented at
execution time. No custody, no new contract, no audit, no money-transmission exposure.
Reuses the exact rail ManagerX already runs on X Layer (2 live settlements proven).
Weakness: household signs each cycle (or batch-signs N cycles ahead).

**Still-open sub-questions under this choice:**
- Signing burden / batching — one authorization row per cycle vs. a pre-signed set.
- **Who the `to` address is** — EIP-3009 names a fixed recipient at signing time. If no
  biller takes stablecoins, `to` must be a settlement provider or the agent, and that
  choice determines what the verifier can actually prove. This is the genuinely unsolved
  part.
- Build order — portal + schema first, or verifier logic first.

### Bondsman API surface (already live, reusable as-is)
- `POST /v1/bond` — prices collateral, returns deposit instructions
  (`escrow_contract`, `chain_id`, `token_address`, `bond_id_onchain`, `amount_raw`).
- `POST /v1/release` — `outcome` = delivered | disputed | failed.
- `GET /v1/verify/{agent_id}` — aggregate bond history + success rate.
- `GET /badge/{bond_id}` — public, proof is a real X Layer tx hash.
- `POST /v1/internal/resolve-dispute`, `POST /v1/internal/resolve-expired` — operator-only.
Tokens: USDT0 / USDG / USDC on X Layer.

---

## Open decision still needed before Phase 1 (real money)
The EIP-3009 `to` recipient problem above. Everything else (listing portal,
`household_gigs` schema, board tab + card variant, claim → active, cycle tick,
bond-per-cycle wiring, execution log, notifications) can be built without resolving it —
that's Phase 0.
