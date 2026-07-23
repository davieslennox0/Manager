# Pocket Bills Rail — what we know, and the one thing we don't

Pocket Bills offered to send an endpoint and request contract. Most of it turned
out to be published already: the agent is listed on the OKX.AI marketplace and
its 402 challenge carries a machine-readable input schema. This is what we read
off it directly, so the reply to them is now a short list of gaps rather than a
request for the whole spec.

## Read off the marketplace listing (agent #8044)

| | |
|---|---|
| Name | Pocket Bills Rail |
| Role | ASP, active, listed |
| Owner | `0x988263a851afe17f8a827eda81269f9fb7553cbc` |
| Service | Nigerian Bills Catalog |
| Type | API service (A2MCP) |
| Fee | 0.01 USDT per call |
| Endpoint | `https://bills.hashpaylink.com/v1/okx/checkout` |
| Sales | 4 |

## Read off the live 402 challenge

Payment is x402 v2 — there is no API key.

| | |
|---|---|
| Scheme | `exact` |
| Network | `eip155:196` (X Layer mainnet) |
| Asset | `0x779ded0c9e1022225f8e0630b35a9b54be713736` (USDT, 6dp) |
| Amount | `10000` = 0.01 USDT |
| payTo | `0x631c96fba389f65da7093e559e8120b587ec7df4` |
| Max timeout | 300s |

Request body, schema-locked with `additionalProperties: false`:

```json
{ "category": "data" | "electricity" | "tv",
  "serviceId": "optional provider service ID — include it to get that provider's plans" }
```

`category` is the only required field. Three values, which is the real limit on
what our agent can honestly claim — the jobber's policy now refuses to claim any
gig outside them.

## Answered by a live paid run, 2026-07-23

We paid for three catalog calls and one real purchase (0.247082 USDT total) and
read the answers off the wire rather than waiting for a spec.

**The checkout leg** — `POST https://bills.hashpaylink.com/v1/okx/bills`, x402.

> **Updated 2026-07-23 — Pocket Bills shipped fixes; verified from our side.**
> The checkout leg was Permit2, which needed a one-time
> `approve(0x000000000022D473030F116dDEE9F6B43aC78BA3, …)`. **That is gone.** It
> is now `exact` / EIP-3009, one shot — an MTN purchase settled in a single
> signed POST with no approve step (tx `0x9c241eb6…`, 0.145289 USDT). Two other
> changes confirmed: **duplicate-charge protection** keys on `externalOrderId`,
> and **failed purchases auto-refund** — the two stranded settlements walked from
> `provider_failed_unverified` / `needs_review` to `refunding` after a requery
> job ran (`requeryAttempts` 0 → 1). The rail now recovers on its own.
>
> Two gotchas found while verifying:
> - **Do not prefix `externalOrderId` with `okx:`** — Pocket Bills prepends it,
>   and sending our own produced a doubled `okx:okx:…`.
> - **Live provider vending is currently DISABLED upstream.** A paid MTN call
>   returned `needs_review` / "Live provider vending is disabled." So payment,
>   idempotency and refunds all work, but nothing is actually delivered right
>   now — every purchase refunds. Nothing can go to a real household until they
>   re-enable vending.

```json
{ "externalOrderId": "stable buyer order id — reuse only when retrying the same bill",
  "category": "data|electricity|tv",
  "serviceId": "from the catalog, e.g. airtel-data",
  "variationCode": "the plan/bouquet/meter type, e.g. airt-200",
  "customerReference": "phone / smartcard / meter number",
  "contactPhone": "required for electricity and tv",
  "amountNgn": "required for electricity" }
```

**Question 2 is answered, and it's the good answer.** `externalOrderId` is
exactly the idempotency key we asked for — "reuse the same value only when
retrying the same bill". The ManagerX `cycle_id` drops straight in, which means
the agent's `attempting` state can eventually become retryable rather than
parked. Worth confirming with them how long they hold the key.

**The economics are the surprise, and they change the product.** A ₦200 Airtel
bundle:

| | |
|---|---|
| provider amount | ₦199.03 |
| **Pocket Bills fee** | **₦100.00** |
| total | ₦299.03 |
| settled | 0.217082 USDT @ ₦1377.5/USDT |

A flat ₦100 per transaction is 50% on a ₦200 bundle. It is noise on a ₦25,000
electricity bill. **This agent should not touch small top-ups** — `MIN_BUDGET`
has to sit far above ₦100 or every cycle loses money, and electricity is the
right anchor for exactly this reason.

**Two purchases, two failures, nothing delivered, nothing refunded.**

| | airt-200 | airt-100 |
|---|---|---|
| settlement | `pst_2628bcc40634420c8b0acc16dcd634e0` | `pst_` (see purchase100.json) |
| paid | 0.217082 USDT `0xa49e5e01…` | 0.144447 USDT `0xa88a382c…` |
| state | `provider_failed_unverified` | `needs_review` |
| provider said | TRANSACTION FAILED | The operation was aborted due to timeout |
| delivery code | *(none)* | *(none)* |
| requery attempts | **0** | **0** |
| refund | none | none |

Two different failure modes — one a definite provider rejection, one a timeout
of genuinely unknown outcome — and in both cases `requeryAttempts` stayed at 0
and the state never moved. Their pipeline does not appear to retry or reconcile
on its own. 0.361529 USDT is sitting unaccounted for.

`needs_review` is the more dangerous of the two for an autonomous agent: a
timeout means the data may or may not have been delivered, so an agent that
retries risks double-vending and an agent that gives up risks reporting a bill
unpaid that was actually paid. This is exactly the state our ledger parks for a
human rather than guessing at.

**The first purchase failed at the provider.** Payment settled on-chain
(`0xa49e5e01…`, 0.217082 USDT taken) and the settlement came back
`provider_failed_unverified` / "TRANSACTION FAILED", with no delivery code, no
requery attempted, and no refund observed. So on the very first real transaction
we hit the exact case the agent's ledger was built for: money gone, service not
delivered. **Ask them what happens to that money** — automatic requery, refund,
or manual claim — because it decides whether `provider_failed_unverified` maps
to our `failed` (safe to retry) or `attempting` (park for a human).

Settlement status is pollable at
`/v1/okx/settlements/{id}?token=…` — the token is a **query parameter**, not a
Bearer header; sending it as Bearer returns `STATUS_TOKEN_INVALID`.

## The gap — now closed

The handoff is no longer a mystery. We've made four paid checkouts and read the
full schema off the wire (see the checkout body above). `checkout()` in
`fulfilment.py` implements it and is proven end to end. What blocks a real
household is no longer *how* to call it — it's two things:

1. **Live vending is off.** Until Pocket Bills re-enables it, every purchase
   refunds and nothing is delivered. Nothing to do here but wait for them.
2. **Gig text → structured plan.** A ManagerX gig carries freeform
   `service_details`; checkout needs a `(serviceId, variationCode)`. Mapping the
   two is an unmade product decision (structured posting fields per bill type, or
   resolve-the-catalog-and-confirm on first cycle). `pay()` refuses in the loop
   until this lands; call `checkout()` directly for a structured test.

## Answered questions (were "worth asking anyway")

**Idempotency key on checkout?** Yes — `externalOrderId`. Confirmed live: send it
**bare**, Pocket Bills prepends its own `okx:` namespace (we saw a doubled
`okx:okx:` when we prefixed it ourselves). This is the two-call crash gap closed:
the ManagerX `cycle_id` becomes the key.

**Rejection vs outage?** Now deterministic. A failed provider call lands in
`needs_review` or `provider_failed_unverified`, and a requery job walks it to a
definite `refunding`/`refunded`. `classify_settlement()` maps delivered→ok,
refund states→failed (retryable), review states→unknown (park and re-poll).

**What we show the household** — `deliveryCode` / `receiptHash`. Empty until
vending is re-enabled.

**Sandbox?** In effect, yes right now: with live vending disabled the rail takes
payment, exercises the full path, and refunds — a free integration test bed,
though not one they've named as such.

## What they need from us

Nothing. No ManagerX key, no polling. They were right about that — the jobber
owns the ManagerX workflow and calls them as a plain paid HTTP service.

## Test plan, once vending is re-enabled and the mapping decision is made

1. `jobber.py catalog electricity` against the funded wallet — read the plans.
2. Point `FULFILMENT=pocketbills` at a gig with a known serviceId/variationCode.
3. Post a gig, let the agent claim it, force a cycle, confirm the token arrives
   by SMS and the reference lands in the report the household sees.
4. Kill the agent mid-payment and restart it. Nothing should be paid twice —
   this already passes against the mock, and `externalOrderId` now backs it live.
   This is the test that matters, and it already passes against the mock.
