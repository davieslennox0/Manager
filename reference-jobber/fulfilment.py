"""Where the bill actually gets paid.

ManagerX is the marketplace, this agent is the jobber, and a fulfilment adapter is
the rail that settles with the biller — Pocket Bills, or anything else. Everything
below this line is deliberately swappable: the agent's loop knows nothing about
who pays the bill or how.

The one thing every adapter MUST get right is the difference between a definite
failure and an unknown one:

    Result.failed(...)   the biller said no. No money moved. Safe to retry.
    Result.unknown(...)  we never got an answer — timeout, dropped connection,
                         5xx. The money may or may not have moved.

Collapsing "unknown" into "failed" is the bug that pays a bill twice. A timeout is
not a failure; it is an absence of information, and the agent treats it as such.
"""
import uuid
from dataclasses import dataclass, field

import requests


@dataclass
class Result:
    state: str                      # "ok" | "failed" | "unknown"
    reference: str = ""             # the biller's receipt / token / txn id
    detail: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    @classmethod
    def succeeded(cls, reference: str, detail: str = "", raw: dict | None = None):
        return cls("ok", reference, detail, raw or {})

    @classmethod
    def failed(cls, detail: str, raw: dict | None = None):
        return cls("failed", "", detail, raw or {})

    @classmethod
    def unknown(cls, detail: str, raw: dict | None = None):
        return cls("unknown", "", detail, raw or {})


class Adapter:
    name = "adapter"

    def pay(self, *, cycle_id: str, bill_type: str, service_details: str,
            amount: str, currency: str) -> Result:
        raise NotImplementedError


class MockAdapter(Adapter):
    """Pays nothing, succeeds always. This is the default, and it is what you use
    to exercise the whole ManagerX loop — post, claim, cycle opens, report — with
    no money and no biller involved."""
    name = "mock"

    def pay(self, *, cycle_id, bill_type, service_details, amount, currency) -> Result:
        ref = "mock_" + uuid.uuid4().hex[:12]
        return Result.succeeded(
            ref, f"Simulated {bill_type} payment of {amount} {currency}. "
                 f"No money moved and no biller was contacted.")


# Pocket Bills Rail — OKX.AI marketplace agent #8044, an ASP listing the service
# "Nigerian Bills Catalog" at 0.01 USDT per call. Everything below was read off
# the live 402 challenge and the on-chain service listing, not from a spec sheet.
#
# Two endpoints, both x402. The catalog endpoint is discovery (which providers,
# which plans); the checkout endpoint vends the bill against a customer number.
POCKETBILLS_ENDPOINT = "https://bills.hashpaylink.com/v1/okx/checkout"
POCKETBILLS_CHECKOUT = "https://bills.hashpaylink.com/v1/okx/bills"

# Their `category` enum is three values. This is the real limit on what the
# Nigerian household agent can honestly claim — a gig for water or waste has no
# rail behind it, so policy should not let the agent take one.
BILL_TYPE_TO_CATEGORY = {
    "electricity": "electricity",
    "mobile": "data",
    "tv_subscription": "tv",
}

# Settlement states, mapped to the only three answers the agent's ledger cares
# about. Confirmed on the wire 2026-07-23 across four live purchases.
#
#   delivered  -> ok       a deliveryCode/receiptHash came back; the bill is paid
#   failed     -> failed   the provider rejected it; money moved but Pocket Bills
#                          auto-refunds (state walks needs_review -> refunding ->
#                          refunded via a requery job). Safe to retry the bill.
#   review     -> unknown  genuinely undetermined delivery. Never retry blind —
#                          a requery resolves it to one of the two above; poll the
#                          status endpoint rather than guessing.
DELIVERED_STATES = {"success", "delivered", "completed", "vended"}
FAILED_STATES = {"provider_failed", "provider_failed_unverified",
                 "refunding", "refunded", "failed", "reversed"}
REVIEW_STATES = {"needs_review", "pending", "processing", "queued"}


def classify_settlement(settlement: dict) -> Result:
    """Turn a Pocket Bills settlement record into a Result. The state field is
    authoritative; deliveryCode/receiptHash are what the household actually sees."""
    state = str(settlement.get("state", "")).lower()
    ref = settlement.get("deliveryCode") or settlement.get("receiptHash") \
        or settlement.get("providerReference") or settlement.get("settlementId", "")
    desc = settlement.get("providerDescription") or state or "no state returned"
    if state in DELIVERED_STATES and (settlement.get("deliveryCode")
                                      or settlement.get("receiptHash")):
        return Result.succeeded(ref, desc, settlement)
    if state in FAILED_STATES:
        return Result.failed(f"Pocket Bills: {desc} (refund in flight).", settlement)
    if state in REVIEW_STATES:
        return Result.unknown(f"Pocket Bills: {desc} — awaiting requery.", settlement)
    return Result.unknown(f"Pocket Bills returned an unrecognised state "
                          f"{state!r}: {desc}", settlement)


class PocketBillsAdapter(Adapter):
    """Pocket Bills Rail (#8044) — Nigerian data, electricity and TV.

    Payment is x402, not an API key: the endpoint answers every unpaid request
    with a 402 and a `payment-required` challenge, and the caller pays 0.01 USDT
    on X Layer (`exact` scheme, USDT at 6dp) to get an answer. This adapter never
    holds a signing key — it shells out to the onchainos CLI, which signs from
    the selected wallet in a TEE and hands back the header to replay with.

    The catalog body is schema-locked with `additionalProperties: false`:

        {"category": "data" | "electricity" | "tv",
         "serviceId": "<optional provider id, to get that provider's plans>"}

    The checkout body (POST /v1/okx/bills) is likewise locked:

        {"externalOrderId": "<bare id — Pocket Bills prepends 'okx:' itself>",
         "category": "data" | "electricity" | "tv",
         "serviceId": "<from the catalog, e.g. mtn-data>",
         "variationCode": "<the plan/bouquet/meter type, e.g. mtn-10mb-100>",
         "customerReference": "<phone / smartcard / meter number>",
         "contactPhone": "<required for electricity and tv>",
         "amountNgn": "<required for electricity>"}

    Confirmed on the wire 2026-07-23 (Pocket Bills' fixes verified from our side):
      · Checkout is `exact` / EIP-3009, one shot — Permit2 and its one-time
        approve are gone. `checkout()` signs the 402 and replays in a single call.
      · Duplicate-charge protection keys on externalOrderId. Do NOT prefix it
        with 'okx:' — they add that, and a doubled 'okx:okx:' was observed.
      · Failed purchases self-refund: state walks needs_review -> refunding ->
        refunded, driven by a requery job. classify_settlement() maps this.

    WHY pay() STILL REFUSES IN THE LOOP. Two things, neither about the rail's
    mechanics, which now work end to end:
      1. Live provider vending is currently DISABLED upstream ("Live provider
         vending is disabled." on a paid MTN call) — every purchase refunds, so
         nothing can be delivered to a household yet.
      2. A ManagerX gig carries freeform `service_details`, but checkout needs a
         structured (serviceId, variationCode). Mapping one to the other is an
         unmade product decision — structured posting fields, or resolve-and-
         confirm on first cycle. `checkout()` below is proven and ready; the loop
         stays on the mock until that decision lands and vending is re-enabled.
    """
    name = "pocketbills"

    def __init__(self, endpoint: str = POCKETBILLS_ENDPOINT, timeout: int = 120,
                 checkout_endpoint: str = POCKETBILLS_CHECKOUT):
        self.endpoint = endpoint
        self.checkout_endpoint = checkout_endpoint
        self.timeout = timeout

    def supports(self, bill_type: str) -> bool:
        return bill_type.lower() in BILL_TYPE_TO_CATEGORY

    def catalog(self, bill_type: str, service_id: str = "") -> Result:
        """The paid discovery call. Costs 0.01 USDT per invocation."""
        category = BILL_TYPE_TO_CATEGORY.get(bill_type.lower())
        if not category:
            return Result.failed(
                f"Pocket Bills has no category for bill type {bill_type!r} — it "
                f"covers {', '.join(sorted(BILL_TYPE_TO_CATEGORY))} only.")

        params = ["--param", f"category={category}"]
        if service_id:
            params += ["--param", f"serviceId={service_id}"]
        quote = _cli(["payment", "quote", self.endpoint, "--method", "POST",
                      *params], self.timeout)
        if not quote.get("ok"):
            return Result.failed(f"Could not read the Pocket Bills challenge: "
                                 f"{quote.get('error') or quote}")

        data = quote.get("data") or {}
        payment_id = data.get("paymentId") or ""
        candidates = data.get("candidates") or []
        if not candidates:
            return Result.failed("Pocket Bills offered no payable scheme.")
        # hasBalance is advisory, not a gate. Observed in the wild: a wallet
        # holding 0.70 of the exact asset reported hasBalance=false because the
        # preflight matches on symbol ("USDT") and the wallet reports the token's
        # own name ("USD₮0"). Refusing on it would have blocked a funded wallet,
        # so warn and let the signer be the authority on whether funds exist.
        payable = [c for c in candidates if c.get("hasBalance")] or candidates
        if not any(c.get("hasBalance") for c in candidates):
            want = candidates[0]
            print(f"  ! balance preflight says no {want.get('tokenSymbol')} on "
                  f"{want.get('chainName')} — attempting anyway, the symbol check "
                  f"gives false negatives")

        # payment pay signs; a non-answer from here on is genuinely unknown.
        index = payable[0].get("acceptsIndex", 0)
        signed = _cli(["payment", "pay", "--payment-id", payment_id,
                       "--selected-index", str(index), "--yes"], self.timeout)
        if not signed.get("ok"):
            return Result.unknown(f"Signing the Pocket Bills payment did not "
                                  f"return cleanly: {signed.get('error') or signed}")
        header = (signed.get("data") or {}).get("authorization_header") \
            or (signed.get("data") or {}).get("paymentSignature") or ""
        if not header:
            return Result.unknown("Payment signed but no header came back to "
                                  "replay the request with.")

        body = {"category": category}
        if service_id:
            body["serviceId"] = service_id
        try:
            r = requests.post(self.endpoint, json=body, timeout=self.timeout,
                              headers={"PAYMENT-SIGNATURE": header,
                                       "Content-Type": "application/json"})
        except requests.RequestException as exc:
            return Result.unknown(f"Paid, then could not reach Pocket Bills: {exc}")
        if r.status_code >= 500 or r.status_code == 402:
            return Result.unknown(f"Paid, but Pocket Bills answered "
                                  f"{r.status_code}.", {"body": r.text[:500]})
        if not r.ok:
            return Result.failed(f"Pocket Bills rejected the call "
                                 f"({r.status_code}).", {"body": r.text[:500]})
        try:
            return Result.succeeded(payment_id, "Catalog retrieved.", r.json())
        except ValueError:
            return Result.unknown("Paid, but the catalog response was not JSON.",
                                  {"body": r.text[:500]})

    def checkout(self, *, external_order_id: str, bill_type: str, service_id: str,
                 variation_code: str, customer_reference: str,
                 contact_phone: str = "", amount_ngn: str = "") -> Result:
        """Vend one bill. This is the proven leg — a paid x402/EIP-3009 POST to
        the checkout endpoint, signed sign-only via the CLI and replayed once.
        Returns a Result classified from the settlement Pocket Bills hands back.

        external_order_id must be STABLE per bill and reused only on a genuine
        retry of the same bill — it is the idempotency key. Pass it bare; Pocket
        Bills prepends its own 'okx:' namespace.
        """
        category = BILL_TYPE_TO_CATEGORY.get(bill_type.lower())
        if not category:
            return Result.failed(
                f"Pocket Bills has no category for bill type {bill_type!r}.")
        body = {"externalOrderId": external_order_id, "category": category,
                "serviceId": service_id, "variationCode": variation_code,
                "customerReference": customer_reference}
        if contact_phone:
            body["contactPhone"] = contact_phone
        if amount_ngn:
            body["amountNgn"] = amount_ngn

        # First hit is unpaid: it comes back 402 with the challenge to sign.
        try:
            probe = requests.post(self.checkout_endpoint, json=body,
                                  timeout=self.timeout)
        except requests.RequestException as exc:
            return Result.failed(f"Could not reach Pocket Bills checkout: {exc}")
        if probe.status_code != 402:
            # No money moved yet, so a non-402 here is a definite, safe failure.
            return Result.failed(f"Checkout did not quote a price (HTTP "
                                 f"{probe.status_code}).", {"body": probe.text[:500]})
        challenge = probe.headers.get("payment-required") \
            or probe.headers.get("PAYMENT-REQUIRED")
        if not challenge:
            return Result.failed("402 with no payment-required challenge header.")

        # Sign-only: the CLI signs the challenge in a TEE and hands back a header.
        signed = _cli(["payment", "pay", "--payload", challenge], self.timeout)
        if not signed.get("ok"):
            # Signing failed before any settle — no money moved.
            return Result.failed(f"Signing the checkout payment failed: "
                                 f"{signed.get('error') or signed}")
        data = signed.get("data") or {}
        header = data.get("authorization_header") or data.get("paymentSignature")
        name = data.get("header_name", "PAYMENT-SIGNATURE")
        if not header:
            return Result.failed("Payment signed but no header came back.")

        # Replay with payment. From here a non-answer is genuinely unknown: the
        # signature may have settled on-chain even if the reply never arrived.
        try:
            r = requests.post(self.checkout_endpoint, json=body, timeout=self.timeout,
                              headers={name: header, "Content-Type": "application/json"})
        except requests.RequestException as exc:
            return Result.unknown(f"Paid, then lost the Pocket Bills reply: {exc}")
        if r.status_code >= 500 or r.status_code == 402:
            return Result.unknown(f"Paid, but Pocket Bills answered "
                                  f"{r.status_code}.", {"body": r.text[:500]})
        try:
            payload = r.json()
        except ValueError:
            return Result.unknown("Paid, but the checkout reply was not JSON.",
                                  {"body": r.text[:500]})
        settlement = payload.get("settlement") or {}
        if not settlement:
            return Result.unknown("Paid, but no settlement record came back.", payload)
        return classify_settlement(settlement)

    def status(self, settlement_id: str, token: str) -> Result:
        """Re-check a settlement whose delivery was left unknown. The token is a
        QUERY parameter — sent as an Authorization: Bearer header it returns
        STATUS_TOKEN_INVALID. A requery job walks needs_review to a final state."""
        url = f"https://bills.hashpaylink.com/v1/okx/settlements/{settlement_id}"
        try:
            r = requests.get(url, params={"token": token}, timeout=self.timeout)
        except requests.RequestException as exc:
            return Result.unknown(f"Could not reach the status endpoint: {exc}")
        if not r.ok:
            return Result.unknown(f"Status endpoint answered {r.status_code}.",
                                  {"body": r.text[:300]})
        try:
            return classify_settlement((r.json() or {}).get("settlement") or {})
        except ValueError:
            return Result.unknown("Status reply was not JSON.")

    def pay(self, *, cycle_id, bill_type, service_details, amount, currency) -> Result:
        return Result.failed(
            "Pocket Bills' rail now works end to end — checkout is EIP-3009, "
            "duplicate-charge protection and auto-refunds are confirmed, and "
            "`checkout()` is proven against it. pay() still refuses in the loop "
            "for two reasons: (1) live provider vending is currently DISABLED "
            "upstream, so every purchase refunds and nothing reaches a household; "
            "(2) a gig's freeform service_details isn't yet mapped to the "
            "structured (serviceId, variationCode) checkout needs — an unmade "
            "product decision. Call checkout() directly for a structured test. "
            "See POCKET_BILLS_CONTRACT.md.")


def _cli(args: list[str], timeout: int) -> dict:
    """Run the onchainos CLI and parse its JSON. Keeps signing keys out of this
    process entirely — the CLI signs in a TEE from the selected wallet."""
    import json
    import subprocess
    try:
        proc = subprocess.run(["onchainos", *args], capture_output=True,
                              text=True, timeout=timeout)
    except FileNotFoundError:
        return {"ok": False, "error": "onchainos CLI not on PATH — install it from "
                                      "https://github.com/okx/onchainos-skills"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"onchainos {args[0]} {args[1]} timed out"}
    out = (proc.stdout or proc.stderr or "").strip()
    for line in reversed(out.splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return {"ok": False, "error": out[:500] or "no output from onchainos"}


def build(name: str, *, endpoint: str = "") -> Adapter:
    if name == "pocketbills":
        return PocketBillsAdapter(endpoint or POCKETBILLS_ENDPOINT)
    if name == "mock":
        return MockAdapter()
    raise SystemExit(f"Unknown FULFILMENT adapter: {name!r} (mock, pocketbills)")
