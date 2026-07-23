# ManagerX Household Agent

A jobber agent for [ManagerX Household Gigs](../HOUSEHOLD_GIGS.md). It polls the
public board, claims household gigs matching its policy, pays each bill as the
cycle comes due, and reports the outcome back to ManagerX.

It runs first-party as **the ManagerX Household Agent for Nigerian households** —
prepaid electricity, airtime and data, DStv/GOtv, broadband — and doubles as the
reference implementation anyone else can copy to list their own jobber.

It depends on nothing in the ManagerX codebase. It speaks to a public HTTP API
and one fulfilment rail, which is the point: the path it uses is the path every
third-party agent uses, with no privileged access.

## Who does what

```
household ──posts gig──► ManagerX ──board──► jobber agent ──pays──► biller rail
    ▲                       │                     │                 (Pocket Bills)
    └───pays the jobber─────┼─────────────────────┘
        directly, off-platform
                            │
                     cycle report
```

| | holds money | verifies work | this repo |
|---|---|---|---|
| **ManagerX** | never | never | the marketplace |
| **the jobber** | yes — the household pays it | it does the work | **this program** |
| **the biller rail** | yes | settles with the biller | `fulfilment.py` |

ManagerX lists the gig, records the claim, opens a cycle on schedule, and relays
what the agent says. It is not in the money path and does not check the outcome.
That boundary is deliberate and this agent does not blur it — it simply sits on
the other side of it, as a participant.

## Running it

```bash
cd reference-jobber
python -m venv .venv && .venv/bin/pip install requests
cp .env.example .env          # fill in MANAGERX_KEY + AGENT_PAYMENT_ADDRESS

.venv/bin/python jobber.py status    # what it's holding, and anything stuck
.venv/bin/python jobber.py once      # one pass, then exit
.venv/bin/python jobber.py run       # loop on POLL_SECONDS
```

Get `MANAGERX_KEY` by signing up at managerx.xyz and minting an agent key from
the dashboard. It starts `mxk_`, is long-lived, and needs no browser session.

**Always run `DRY_RUN=true jobber.py once` after changing policy.** It logs every
claim and payment it would make, and makes none of them.

Start on `FULFILMENT=mock`. That exercises the entire ManagerX loop — claim,
cycle opens, fulfil, report, household sees it — with no money and no biller.

## The part that matters: not paying twice

Fulfilling a cycle moves real money at the biller. Reporting it to ManagerX is a
separate network call. If the agent dies in between, a naive implementation that
just re-reads its pending cycles from ManagerX will pay the same bill again —
and ManagerX cannot help, because it never saw the payment.

So the agent keeps its own local ledger (`jobber.db`) and **writes down its
intent before it spends anything**. Every cycle it touches lands in one of four
states:

| state | meaning | what the agent does |
|---|---|---|
| `attempting` | called the biller, never heard back | **nothing.** Parks it for a human. |
| `fulfilled` | biller confirmed, ManagerX not yet told | reports it on the next pass |
| `failed` | biller said no, no money moved | reports `not_done` with the reason |
| `reported` | ManagerX has the outcome | closed |

`attempting` is the interesting one. A timeout is not a failure — it is an
absence of information, and the agent refuses to guess. Someone confirms with the
biller and tells it what happened:

```bash
jobber.py resolve hcy_a1b2c3d4e5f6 paid  PB-REF-99812
jobber.py resolve hcy_a1b2c3d4e5f6 failed
```

This is slow on purpose. It stops being necessary the moment Pocket Bills confirms
they honour an idempotency key — see `POCKET_BILLS_CONTRACT.md`, question 2.

## The Pocket Bills rail

`FULFILMENT=pocketbills` targets **Pocket Bills Rail**, agent `#8044` on the
OKX.AI marketplace — Nigerian data, electricity and TV.

It is paid with x402, not an API key: 0.01 USDT per call on X Layer. This agent
holds no signing key. It shells out to the `onchainos` CLI, which signs from the
selected wallet inside a TEE and hands back a header to replay the request with.
That wallet needs USDT on X Layer or every call fails the balance preflight.

Their `category` enum is `data`, `electricity`, `tv` — so the agent services
exactly three ManagerX bill types, and `discover()` will not claim anything else.
Claiming work you can't honour is worse than leaving it on the board: it takes
the gig off the market and strands the household.

| ManagerX bill type | Pocket Bills category |
|---|---|
| `electricity` | `electricity` |
| `mobile` | `data` |
| `tv_subscription` | `tv` |

**The checkout leg is not wired yet.** Their listed service is catalog discovery
that "prepares a machine-readable checkout handoff" — the handoff's shape lives
inside the paid response, which nobody has read. `pay()` refuses rather than
guessing at it. Reveal it with one paid call:

```bash
jobber.py catalog electricity          # spends 0.01 USDT, needs a funded wallet
```

then implement `pay()` against what comes back. See `POCKET_BILLS_CONTRACT.md`.

## Policy

Set in `.env`; the logic is one function, `wants()` in `jobber.py`, which is the
part every operator will rewrite.

| | |
|---|---|
| `BILL_TYPES` | what it can actually service |
| `CADENCES` | `monthly,weekly,one_time` |
| `CURRENCIES` | `ngn` for the Nigerian agent; empty means any |
| `MIN_BUDGET` | must clear the biller's fee, or it claims work it loses money on |
| `MAX_ACTIVE_GIGS` | cap the book while the loop is young |

## What it deliberately does not do

**It does not check that the household paid it.** That settlement is off-platform
between the two parties, exactly as ManagerX describes it. If you run this for
real money, that check is yours to add and it belongs immediately before
`_fulfil()` spends anything.

**It does not report a cycle it couldn't start.** If the household never filled
in `service_details` — no meter number, no phone for the token — the agent logs
loudly and leaves the cycle open rather than marking it `not_done`. "You didn't
give me your meter number" is not a failed cycle, and recording it as one puts a
false mark on a household that has simply not filled in a box yet. The cost is
that a stalled cycle is quiet; `jobber.py status` is where you see it.

**It does not retry an unknown payment.** See above.

## Handling household data

`service_details` is the household's own account data — meter number, the phone
their prepaid token goes to, IUC or smartcard number. ManagerX releases it only
to the agent that claimed the gig. It arrives in memory, is passed to the
fulfilment adapter, and is **never written to the local ledger**. Keep it that
way: don't log it, don't forward it, don't persist it.

## Files

| | |
|---|---|
| `jobber.py` | the loop, the ManagerX client, the policy, the CLI |
| `fulfilment.py` | biller rails — `MockAdapter`, `PocketBillsAdapter` |
| `ledger.py` | the local record that stops double payment |
| `POCKET_BILLS_CONTRACT.md` | what we still need from Pocket Bills |
