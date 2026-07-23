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
POCKETBILLS_ENDPOINT = "https://bills.hashpaylink.com/v1/okx/checkout"

# Their `category` enum is three values. This is the real limit on what the
# Nigerian household agent can honestly claim — a gig for water or waste has no
# rail behind it, so policy should not let the agent take one.
BILL_TYPE_TO_CATEGORY = {
    "electricity": "electricity",
    "mobile": "data",
    "tv_subscription": "tv",
}


class PocketBillsAdapter(Adapter):
    """Pocket Bills Rail (#8044) — Nigerian data, electricity and TV.

    Payment is x402, not an API key: the endpoint answers every unpaid request
    with a 402 and a `payment-required` challenge, and the caller pays 0.01 USDT
    on X Layer (`exact` scheme, USDT at 6dp) to get an answer. This adapter never
    holds a signing key — it shells out to the onchainos CLI, which signs from
    the selected wallet in a TEE and hands back the header to replay with.

    The request body is schema-locked with `additionalProperties: false`:

        {"category": "data" | "electricity" | "tv",
         "serviceId": "<optional provider id, to get that provider's plans>"}

    WHAT IS NOT WIRED YET, and why. Their listing describes this service as
    catalog discovery that "prepares a machine-readable checkout handoff". That
    is the first half of fulfilment: it tells us the provider options and plans.
    The handoff itself — the call that actually vends the token against a meter
    number — is described in the response body, and the response body is behind
    the paywall. One successful paid call reveals it. Until then `pay()` refuses
    rather than guessing, because a guessed payment call is exactly the kind of
    thing that spends a household's money into a void.
    """
    name = "pocketbills"

    def __init__(self, endpoint: str = POCKETBILLS_ENDPOINT, timeout: int = 120):
        self.endpoint = endpoint
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
        payable = [c for c in data.get("candidates") or [] if c.get("hasBalance")]
        if not payable:
            want = (data.get("candidates") or [{}])[0]
            return Result.failed(
                f"Wallet cannot cover this call: needs "
                f"{want.get('amountHuman', '0.01')} {want.get('tokenSymbol', 'USDT')} "
                f"on {want.get('chainName', 'X Layer')}. Fund it, then retry.")

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

    def pay(self, *, cycle_id, bill_type, service_details, amount, currency) -> Result:
        return Result.failed(
            "The Pocket Bills checkout leg is not wired yet. Their listed service "
            "is catalog discovery that prepares a checkout handoff; the handoff's "
            "shape is inside the paid response and has not been read once. Run "
            "`python jobber.py catalog electricity` with a funded wallet to reveal "
            "it, then implement pay() against what comes back. Refusing rather "
            "than guessing — see POCKET_BILLS_CONTRACT.md.")


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
