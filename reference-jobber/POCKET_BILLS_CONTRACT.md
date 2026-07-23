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

## The gap

Their listing says the service "prepares a machine-readable checkout handoff".
That is discovery — provider options and plans. **The handoff itself is described
inside the paid response, and we have never seen a paid response.** So we know
how to ask what an electricity plan costs; we do not yet know the call that vends
a token against a specific meter number.

One successful paid call reveals it. `payment quote` currently reports
`hasBalance: false` — the wallet holds no USDT on X Layer, so the call cannot go
through until it's funded. 0.01 USDT settles this.

Until then `PocketBillsAdapter.pay()` deliberately refuses instead of guessing.

## Questions worth asking them anyway

**1. Does the checkout leg cost separately, and how is the bill amount itself
paid?** The 0.01 USDT is the catalog fee. Vending ₦25,000 of electricity is a
different quantum of money, and we need to know whether that rides the same x402
rail, a prefunded balance, or something else.

**2. Do you honour an idempotency key on the checkout leg?** This is the one that
changes our architecture. The jobber pays a bill and then reports it to ManagerX
— two calls. If it dies in between, we don't know whether the money moved. Today
it parks the cycle for a human, which is safe and slow. If you dedupe on a key we
supply — we'd send the ManagerX `cycle_id`, unique per bill per period and stable
across retries — that failure mode disappears.

**3. Can we distinguish a rejection from an outage?** We need a definite "no money
moved" that isn't a 500 or a timeout. Confirm you never return 4xx after taking
money.

**4. What comes back that we can show the household?** For prepaid electricity
that should be the actual token. Name the field.

**5. Is there a sandbox?** We'd rather find our mistakes without vending real
tokens to real meters.

## What they need from us

Nothing. No ManagerX key, no polling. They were right about that — the jobber
owns the ManagerX workflow and calls them as a plain paid HTTP service.

## Test plan once the checkout leg is known

1. `jobber.py catalog electricity` against a funded wallet — read the handoff.
2. Implement `pay()` against it; point `FULFILMENT=pocketbills` at a sandbox.
3. Post a gig, let the agent claim it, force a cycle, confirm the token arrives
   by SMS and the reference lands in the report the household sees.
4. Kill the agent mid-payment and restart it. Nothing should be paid twice.
   This is the test that matters, and it already passes against the mock.
