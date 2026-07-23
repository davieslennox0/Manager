import json
import os
import tempfile

os.environ["WORKOS_SECRET_KEY"] = "test-secret"
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["SCANNER_ENABLED"] = "0"
os.environ["FUNDING_ENABLED"] = "0"

import pytest
from fastapi.testclient import TestClient

import funding
import proofwork
import scanner
from db import init_db
from main import app
from mailer import _matches
from pipeline import agreement_doc_hash


@pytest.fixture()
def client():
    init_db()
    with TestClient(app) as c:
        yield c


def _signup(client, email="t@t.dev"):
    resp = client.post("/v1/auth/signup", json={"email": email, "password": "longenough1"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def test_ecosystem_tagging_word_boundaries():
    assert scanner._tag_ecosystem("Senior Solidity dev for an Ethereum rollup") == "Ethereum"
    assert scanner._tag_ecosystem("Manage our customer database in Boston") == ""
    assert scanner._tag_ecosystem("Building on Base with OP Stack") == "Base"
    assert scanner._tag_ecosystem("suitable candidates apply") == ""
    assert scanner._tag_ecosystem("TON ecosystem grants") == "Ton"


def test_digest_matching():
    listing = {"role": "Solidity Engineer", "firm": "DeFi Labs", "ecosystem": "Ethereum",
               "location": "Remote", "skills": json.dumps(["solidity", "evm"])}
    assert _matches(listing, {})
    assert _matches(listing, {"ecosystem": "ethereum"})
    assert not _matches(listing, {"ecosystem": "solana"})
    assert _matches(listing, {"role_keywords": ["solidity"]})
    assert not _matches(listing, {"role_keywords": ["designer"]})
    assert _matches(listing, {"keywords": ["evm"]})


def test_doc_hash_is_canonical():
    a = {"title": "T", "scope_of_work": ["x"], "payment": {"amount": "1"}}
    b = {"payment": {"amount": "1"}, "scope_of_work": ["x"], "title": "T"}
    assert agreement_doc_hash(a) == agreement_doc_hash(b)
    assert agreement_doc_hash(a) != agreement_doc_hash({**a, "title": "U"})


def test_auth_and_profile_roundtrip(client):
    headers = _signup(client)
    resp = client.put("/v1/profile", headers=headers,
                      json={"full_name": "Ada", "skills": ["Solidity"],
                            "experience": [{"title": "Dev", "org": "X",
                                            "start": "2020", "end": "2024", "bullets": ["y"]}]})
    assert resp.status_code == 200
    spine = client.get("/v1/profile", headers=headers).json()
    assert spine["full_name"] == "Ada"
    assert spine["verified_work_history"] == []


def test_job_requires_input(client):
    headers = _signup(client, "j@t.dev")
    assert client.post("/v1/jobs", json={}, headers=headers).status_code == 422


def test_agreement_gated_on_acceptance(client):
    headers = _signup(client, "g@t.dev")
    conn_resp = client.post("/v1/agreements/draft/job_missing", headers=headers)
    assert conn_resp.status_code == 404


def test_listings_public_and_filterable(client):
    resp = client.get("/v1/listings?q=nothingmatchesthis")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_subscription_capture(client):
    resp = client.post("/v1/subscriptions",
                       json={"email": "d@t.dev", "keywords": ["solidity"]})
    assert resp.status_code == 200
    dup = client.post("/v1/subscriptions",
                      json={"email": "d@t.dev", "keywords": ["solidity"]})
    assert dup.status_code == 409
    sub_id = resp.json()["sub_id"]
    assert client.get(f"/v1/unsubscribe/{sub_id}").json()["unsubscribed"] is True


def test_category_classifier():
    assert scanner._tag_category("Senior Security Engineer") == "Security"
    assert scanner._tag_category("Product Designer") == "Design"
    assert scanner._tag_category("Solidity Developer") == "Engineering"
    assert scanner._tag_category("Head of Marketing") == "Marketing & Growth"
    assert scanner._tag_category("General Counsel") == "Legal & Compliance"
    assert scanner._tag_category("Chief of Staff") == "Operations & People"
    assert scanner._tag_category("Wizard of Nothing") == "Other"


# ── Newly-funded filter ──────────────────────────────────────────────────

def test_raise_parser():
    hits = funding.parse_raises(
        "Velocity raises $38M to build stablecoin treasury infrastructure. "
        "Crypto VC Paradigm raises $1.2B to push into AI. "
        "Institutional crypto exchange EDX lands $76M from SBI Holdings. "
        "Trasia raised $1.8M in a Seed funding round from Multicoin Capital. "
        "Kalshi seeks funding at $40B valuation.")
    by_firm = {h["firm"]: h for h in hits}
    assert by_firm["Velocity"]["amount"] == "$38M"
    assert by_firm["Paradigm"]["amount"] == "$1.2B"   # "Crypto VC" prefix stripped
    assert by_firm["EDX"]["amount"] == "$76M"
    assert by_firm["Trasia"]["round"] == "Seed"
    assert "Kalshi" not in by_firm                    # "seeks" is not a completed raise


def test_slug_candidates():
    slugs = funding.slug_candidates("DeFi Labs Inc")
    assert "defilabsinc" in slugs and "defi-labs-inc" in slugs
    assert funding.normalize_firm("Crypto.com") == "cryptocom"


def test_newly_funded_filter_and_facet(client):
    resp = client.get("/v1/listings?newly_funded=1")
    assert resp.status_code == 200
    assert "newly_funded" in resp.json()["facets"]
    tiers = client.get("/v1/funded").json()
    assert "speculative" in tiers and "hiring" in tiers


def test_digest_newly_funded_criterion():
    base = {"role": "Dev", "firm": "X", "ecosystem": "", "location": "",
            "skills": "[]"}
    assert not _matches({**base, "newly_funded": 0}, {"newly_funded": True})
    assert _matches({**base, "newly_funded": 1}, {"newly_funded": True})
    assert _matches({**base, "newly_funded": 0}, {})


def test_subscription_captures_newly_funded(client):
    resp = client.post("/v1/subscriptions",
                       json={"email": "nf@t.dev", "newly_funded": True})
    assert resp.status_code == 200
    assert resp.json()["filters"] == {"newly_funded": True}


# ── Proof-of-work layer ──────────────────────────────────────────────────

def test_contract_address_extraction():
    text = ("Deployed at 0x78fBD5B1b50B80045a03D272D12B357a374a01c3 and "
            "0x78fbd5b1b50b80045a03d272d12b357a374a01c3 (same, case) plus junk 0x1234")
    addrs = proofwork.extract_addresses(text)
    assert addrs == ["0x78fBD5B1b50B80045a03D272D12B357a374a01c3"]


def test_platform_proof_claim(client):
    headers = _signup(client, "pp@t.dev")
    me = client.get("/v1/profile", headers=headers)
    assert me.status_code == 200
    # no executed contracts yet -> empty claim, zero count
    resp = client.get("/v1/proof/wallet", headers=headers)
    assert resp.json() == {"connected": False}


def test_proof_match_requires_job(client):
    headers = _signup(client, "pm@t.dev")
    assert client.post("/v1/proof/jobs/job_missing/match",
                       headers=headers).status_code == 404


def test_wallet_connect_rejects_bad_signature(client):
    headers = _signup(client, "w@t.dev")
    nonce = client.get("/v1/proof/wallet/nonce", headers=headers).json()["nonce"]
    resp = client.post("/v1/proof/wallet", headers=headers,
                       json={"address": "0x78fBD5B1b50B80045a03D272D12B357a374a01c3",
                             "signature": "0x" + "11" * 65, "nonce": nonce})
    assert resp.status_code == 422


# ── Verified track record ────────────────────────────────────────────────

def test_public_profile_opt_in_flow(client):
    headers = _signup(client, "pub@t.dev")
    # private by default
    assert client.get("/v1/public/no-such-handle").status_code == 404
    # publishing without a handle is rejected
    assert client.put("/v1/public/settings", headers=headers,
                      json={"handle": "", "public": True}).status_code == 422
    assert client.put("/v1/public/settings", headers=headers,
                      json={"handle": "BAD HANDLE!", "public": True}).status_code == 422
    resp = client.put("/v1/public/settings", headers=headers,
                      json={"handle": "ada-dev", "public": True})
    assert resp.status_code == 200
    page = client.get("/v1/public/ada-dev")
    assert page.status_code == 200
    assert page.json()["stats"]["contracts_completed"] == 0
    # handle collision
    other = _signup(client, "pub2@t.dev")
    assert client.put("/v1/public/settings", headers=other,
                      json={"handle": "ada-dev", "public": True}).status_code == 409
    # unpublish hides the page
    client.put("/v1/public/settings", headers=headers,
               json={"handle": "ada-dev", "public": False})
    assert client.get("/v1/public/ada-dev").status_code == 404


def test_proof_card_svg(client):
    headers = _signup(client, "card@t.dev")
    client.put("/v1/public/settings", headers=headers,
               json={"handle": "card-dev", "public": True})
    missing = client.get("/v1/public/card-dev/card/nope.svg")
    assert missing.status_code == 404
    # seed a work_history row directly (only executed agreements write here in prod)
    from db import get_conn
    conn = get_conn()
    uid = conn.execute("SELECT user_id FROM users WHERE email='card@t.dev'").fetchone()[0]
    conn.execute(
        "INSERT INTO work_history (entry_id, user_id, agreement_id, title, counterparty,"
        " doc_hash, tx_hash) VALUES ('wh_test', ?, 'agr_x', 'Solidity Auditor',"
        " 'DeFi Labs', '0xabc', '0xee728ecc1234')", (uid,))
    conn.commit()
    conn.close()
    card = client.get("/v1/public/card-dev/card/wh_test.svg")
    assert card.status_code == 200
    assert card.headers["content-type"].startswith("image/svg+xml")
    assert "Solidity Auditor" in card.text and "DeFi Labs" in card.text


# --- Agent-jobs adapters: normalization is the breakable part; test it offline. ---

class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _FakeClient:
    def __init__(self, payload):
        self._p = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        return _FakeResp(self._p)


def _patch_http(monkeypatch, payload):
    import agent_jobs
    monkeypatch.setattr(agent_jobs.httpx, "AsyncClient",
                        lambda *a, **k: _FakeClient(payload))


def test_agent_jobs_trim():
    import agent_jobs
    assert agent_jobs._trim("10.0000") == "10"
    assert agent_jobs._trim("15.5000") == "15.5"
    assert agent_jobs._trim(None) == "" and agent_jobs._trim("") == ""
    assert agent_jobs._trim("N/A") == "N/A"  # non-numeric passes through


def test_dealwork_adapter_normalizes(monkeypatch):
    import asyncio
    import agent_jobs
    _patch_http(monkeypatch, {"data": [
        {"id": "d1", "title": "Base research", "description": "x", "category": "research",
         "tags": ["defi"], "eligibleWorkerTypes": "ai_only", "budgetMin": "10.0000",
         "budgetMax": "10.0000", "fixedPrice": None, "status": "bidding",
         "visibility": "public", "biddingDeadline": "2026-08-01T00:00:00.000Z",
         "createdAt": "2026-07-21T00:00:00Z", "posterDisplayName": "Bot"},
        {"id": "d2", "title": "closed", "status": "completed", "visibility": "public"},
        {"id": "d3", "title": "human only", "status": "bidding", "visibility": "public",
         "eligibleWorkerTypes": "human_only"},
    ]})
    rows = asyncio.run(agent_jobs._dealwork())
    assert [r["external_id"] for r in rows] == ["d1", "d3"]  # completed dropped
    d1 = rows[0]
    assert d1["reward"] == "10" and d1["token"] == "USDC" and d1["chain"] == "Base"
    assert d1["agent_access"] == "AGENT" and d1["deadline"] == "2026-08-01"
    assert rows[1]["agent_access"] == "HUMAN_ONLY"


def test_x402_bounty_adapter_filters_and_normalizes(monkeypatch):
    import asyncio
    import agent_jobs
    _patch_http(monkeypatch, {"resources": [
        {"resource": "https://x.io/bounty/claim", "serviceName": "Bounty Board",
         "tags": ["bounty", "work"], "description": "Claim an open bounty to work on",
         "accepts": [{"amount": "2000", "network": "base"}], "lastUpdated": "2026-07-21T00:00:00Z"},
        {"resource": "https://x.io/email", "serviceName": "Email service",
         "tags": ["email", "smtp"], "description": "Send email over x402",
         "accepts": [{"amount": "10000", "network": "eip155:8453"}]},
    ]})
    rows = asyncio.run(agent_jobs._x402_bounties())
    assert len(rows) == 1  # the non-bounty service is filtered out
    r = rows[0]
    assert r["url"] == "https://x.io/bounty/claim"
    assert r["chain"] == "Base"  # bare "base" slug normalized
    assert r["reward"] == "" and "x402 claim 0.002 USDC" in r["description"]
    assert r["agent_access"] == "AGENT"


# --- Website paywall: humans free, agents pay. The gate decision is the risk. ---

class _FakeReq:
    def __init__(self, path="/", method="GET", headers=None):
        self.method = method
        self.headers = headers or {}
        self.url = type("U", (), {"path": path})()


def test_wall_is_page_request():
    import x402_setup as x
    assert x._is_page_request(_FakeReq("/"))            # homepage
    assert x._is_page_request(_FakeReq("/profiles"))    # SPA route
    assert not x._is_page_request(_FakeReq("/v1/agent-jobs"))
    assert not x._is_page_request(_FakeReq("/assets/app.js"))
    assert not x._is_page_request(_FakeReq("/health"))
    assert not x._is_page_request(_FakeReq("/favicon.ico"))
    assert not x._is_page_request(_FakeReq("/managerx-mark.svg"))  # static asset
    assert not x._is_page_request(_FakeReq("/", method="POST"))    # non-GET


def test_wall_looks_like_agent():
    import x402_setup as x
    browser = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"
    assert not x._looks_like_agent(_FakeReq(headers={"user-agent": browser}))       # human
    assert x._looks_like_agent(_FakeReq(headers={"user-agent": "python-httpx/0.27"}))  # agent
    assert x._looks_like_agent(_FakeReq(headers={"user-agent": "curl/8.0"}))         # agent
    assert x._looks_like_agent(_FakeReq(headers={}))                                 # no UA -> agent
    assert not x._looks_like_agent(_FakeReq(                                          # crawler -> free
        headers={"user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"}))
    assert x._looks_like_agent(_FakeReq(                                              # paying x402 client
        headers={"user-agent": browser, "x-payment": "eyJ..."}))


def test_balance_report_format():
    import balance_report as br
    data = {"payto": "0xA06ec7302917C4bd51C521330Ec970629b4E047f",
            "relayer": "0xCf8D", "total_stable": 12.34,
            "rails": [{"network": "X Layer", "token": "USDT0", "gas_symbol": "OKB",
                       "token_balance": "12.34", "relayer_gas": "0.5", "low_gas": False}]}
    msg = br.format_report(data, "2026-07-21")
    assert "0xA06e…047f" in msg and "X Layer · USDT0: 12.34" in msg
    assert "≈ 12.34" in msg and "⚠️" not in msg
    # low gas raises a visible warning; a dead RPC degrades to a read-failed line
    data["rails"][0]["low_gas"] = True
    assert "LOW" in br.format_report(data, "2026-07-21")
    data["rails"][0] = {"network": "Base", "token": "USDC", "gas_symbol": "ETH",
                        "error": "TimeoutError"}
    assert "read failed" in br.format_report(data, "2026-07-21")


def test_balance_trim():
    import balance_report as br
    assert br._fmt(12340000, 6) == "12.34"
    assert br._fmt(0, 6) == "0"
    assert br._fmt(1000000, 6) == "1"

def test_x402_accepts_one_option_per_asset():
    """Every gated route offers each accepted stablecoin, so a payer settles in
    whichever it holds. All are 6-decimal, so one atomic amount prices them all."""
    x = pytest.importorskip("x402_setup")
    opts = x._option("100000")
    assert len(opts) == len(x.ACCEPTED) >= 1
    assert {o.price.asset.lower() for o in opts} == {
        a["address"].lower() for a in x.ACCEPTED}
    for o in opts:
        assert o.scheme == "exact"
        assert o.network == x.NETWORK          # one network -> no router needed
        assert o.price.amount == "100000"      # shared amount: all 6 decimals
        assert o.extra["assetTransferMethod"] == "eip3009"
        assert o.extra["decimals"] == 6
    # distinct EIP-712 domains per token (USDC is version 2, the others version 1)
    assert len({(o.extra["name"], o.extra["version"]) for o in opts}) == len(opts)


def test_x402_domain_verification_drops_mismatch(monkeypatch):
    """A wrong EIP-712 domain silently rejects every payment, so it must be caught
    at boot rather than shipped. A correct entry alongside it is kept."""
    x = pytest.importorskip("x402_setup")
    usdc = next(a for a in x.ASSETS if a["symbol"] == "USDC")
    kept = x._verify_domains([{**usdc, "version": "999"}, dict(usdc)])
    assert [a["version"] for a in kept] == [usdc["version"]]


def test_x402_rails_line_lists_every_symbol():
    x = pytest.importorskip("x402_setup")
    line = x._rails("0.02")
    assert line.startswith("0.02 ")
    for a in x.ACCEPTED:
        assert a["symbol"] in line


# ── Household Gigs ───────────────────────────────────────────────────────────
# The whole point of this feature is what it does NOT do: no payment, no escrow,
# no verification. The tests assert the boundary as hard as the behaviour.

def _post_gig(client, headers, **over):
    body = {"title": "Flat 4 — utilities bundle", "bill_types": ["electricity", "broadband"],
            "cadence": "monthly", "budget_amount": "45000", "budget_currency": "NGN"}
    body.update(over)
    return client.post("/v1/household-gigs", headers=headers, json=body)


def test_household_gig_lifecycle(client):
    import household
    home = _signup(client, "home@t.dev")
    agent = _signup(client, "agent@t.dev")

    gig = _post_gig(client, home).json()
    assert gig["status"] == "open"
    assert gig["bill_types"] == ["electricity", "broadband"]
    assert gig["settlement"]["processed_by_managerx"] is False

    # Public board: no auth, and the household's identity never leaves the dashboard.
    board = client.get("/v1/household-gigs").json()
    assert board["total"] == 1
    assert "household_user_id" not in board["household_gigs"][0]
    assert client.get("/v1/household-gigs?bill_type=electricity").json()["total"] == 1
    assert client.get("/v1/household-gigs?bill_type=gas").json()["total"] == 0

    claimed = client.post(f"/v1/household-gigs/{gig['gig_id']}/claim", headers=agent,
                          json={"agent_payment_address": "0xAgentWallet"}).json()
    assert claimed["status"] == "claimed"
    assert claimed["agent_payment_address"] == "0xAgentWallet"
    assert client.get("/v1/household-gigs").json()["total"] == 0  # off the open board

    # The cycle clock opens the first cycle (next_cycle_date defaults to today).
    opened = household.generate_due_cycles()
    assert len(opened) == 1
    cycle_id = opened[0][1]["cycle_id"]

    dash = client.get(f"/v1/household-gigs/{gig['gig_id']}/dashboard", headers=home).json()
    assert dash["status"] == "active"          # claimed -> active once cycles run
    assert dash["cycles"][0]["status"] == "pending"
    assert dash["pay_the_agent"]["address"] == "0xAgentWallet"
    assert "does not process" in dash["pay_the_agent"]["instruction"]

    # Agent self-reports; ManagerX relays it and says so.
    rep = client.post(f"/v1/household-gigs/{gig['gig_id']}/cycles/{cycle_id}/status",
                      headers=agent, json={"status": "done", "agent_note": "Paid via app"})
    assert rep.json()["self_reported"] is True
    assert rep.json()["status"] == "done"

    queue = client.get("/v1/household-gigs/claimed", headers=agent).json()
    assert queue["household_gigs"][0]["pending_cycles"] == []

    assert client.get("/v1/household-gigs/mine", headers=home).json()[
        "household_gigs"][0]["unacked_cycles"] == 1
    acked = client.post(f"/v1/household-gigs/{gig['gig_id']}/cycles/{cycle_id}/ack",
                        headers=home).json()
    assert acked["household_ack"] == 1


def test_household_gig_claim_is_race_safe(client):
    home = _signup(client, "home2@t.dev")
    a1 = _signup(client, "a1@t.dev")
    a2 = _signup(client, "a2@t.dev")
    gig_id = _post_gig(client, home).json()["gig_id"]

    first = client.post(f"/v1/household-gigs/{gig_id}/claim", headers=a1,
                        json={"agent_payment_address": "0xOne"})
    second = client.post(f"/v1/household-gigs/{gig_id}/claim", headers=a2,
                         json={"agent_payment_address": "0xTwo"})
    assert first.status_code == 200
    assert second.status_code == 409
    # The loser leaves no trace on the row.
    dash = client.get(f"/v1/household-gigs/{gig_id}/dashboard", headers=home).json()
    assert dash["agent_payment_address"] == "0xOne"


def test_household_gig_guards(client):
    home = _signup(client, "home3@t.dev")
    agent = _signup(client, "agent3@t.dev")
    stranger = _signup(client, "nosy@t.dev")
    gig_id = _post_gig(client, home).json()["gig_id"]

    assert _post_gig(client, home, budget_amount="-5").status_code == 422
    assert _post_gig(client, home, budget_amount="free").status_code == 422
    assert _post_gig(client, home, cadence="hourly").status_code == 422
    assert _post_gig(client, home, bill_types=[]).status_code == 422

    # A household can't claim its own gig; a stranger can't read the dashboard.
    assert client.post(f"/v1/household-gigs/{gig_id}/claim", headers=home,
                       json={"agent_payment_address": "0xSelf"}).status_code == 409
    assert client.get(f"/v1/household-gigs/{gig_id}/dashboard",
                      headers=stranger).status_code == 403

    # Budget is editable while open, frozen once claimed.
    assert client.patch(f"/v1/household-gigs/{gig_id}", headers=home,
                        json={"budget_amount": "50000"}).status_code == 200
    client.post(f"/v1/household-gigs/{gig_id}/claim", headers=agent,
                json={"agent_payment_address": "0xA"})
    assert client.patch(f"/v1/household-gigs/{gig_id}", headers=home,
                        json={"budget_amount": "1"}).status_code == 409

    # Only the claiming agent can report a cycle.
    import household
    cycle_id = household.generate_due_cycles()[0][1]["cycle_id"]
    assert client.post(f"/v1/household-gigs/{gig_id}/cycles/{cycle_id}/status",
                       headers=stranger, json={"status": "done"}).status_code == 403
    assert client.post(f"/v1/household-gigs/{gig_id}/cycles/{cycle_id}/status",
                       headers=agent, json={"status": "paid"}).status_code == 422


def test_household_cancel_stops_the_cycle_clock(client):
    import household
    home = _signup(client, "home4@t.dev")
    agent = _signup(client, "agent4@t.dev")
    gig_id = _post_gig(client, home).json()["gig_id"]
    client.post(f"/v1/household-gigs/{gig_id}/claim", headers=agent,
                json={"agent_payment_address": "0xA"})
    household.generate_due_cycles()

    cancelled = client.post(f"/v1/household-gigs/{gig_id}/cancel", headers=home).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["next_cycle_date"] == ""
    assert household.generate_due_cycles() == []


def test_one_time_gig_opens_exactly_one_cycle(client):
    import household
    home = _signup(client, "home5@t.dev")
    agent = _signup(client, "agent5@t.dev")
    gig_id = _post_gig(client, home, cadence="one_time").json()["gig_id"]
    client.post(f"/v1/household-gigs/{gig_id}/claim", headers=agent,
                json={"agent_payment_address": "0xA"})
    assert len(household.generate_due_cycles()) == 1
    assert household.generate_due_cycles() == []


def test_lapsed_gig_does_not_backfill_a_flood_of_cycles(client):
    """A gig months overdue opens one cycle and catches its date up in one pass."""
    import datetime
    import household
    from db import get_conn
    home = _signup(client, "home6@t.dev")
    agent = _signup(client, "agent6@t.dev")
    gig_id = _post_gig(client, home).json()["gig_id"]
    client.post(f"/v1/household-gigs/{gig_id}/claim", headers=agent,
                json={"agent_payment_address": "0xA"})
    stale = (datetime.date.today() - datetime.timedelta(days=200)).isoformat()
    conn = get_conn()
    conn.execute("UPDATE household_gigs SET next_cycle_date=? WHERE gig_id=?", (stale, gig_id))
    conn.commit()
    conn.close()

    assert len(household.generate_due_cycles()) == 1
    assert household.generate_due_cycles() == []   # date is now in the future


# ── Agent API keys ───────────────────────────────────────────────────────────
# The credential an autonomous client can actually hold: no session to refresh,
# no password to type. It authenticates AS the user who minted it.

def test_agent_key_mint_use_and_revoke(client):
    owner = _signup(client, "keyowner@t.dev")
    minted = client.post("/v1/agent-keys", headers=owner, json={"label": "bill-bot"}).json()
    secret = minted["key"]
    assert secret.startswith("mxk_")
    assert minted["prefix"] == secret[:12]

    # Listed without the secret — it exists in that one response and nowhere else.
    listed = client.get("/v1/agent-keys", headers=owner).json()["agent_keys"]
    assert len(listed) == 1 and "key" not in listed[0] and listed[0]["revoked"] == 0

    # Both header forms work, and identify the same user as the JWT would.
    for headers in ({"Authorization": f"Bearer {secret}"}, {"X-API-Key": secret}):
        assert client.get("/v1/household-gigs/claimed", headers=headers).status_code == 200

    assert client.get("/v1/household-gigs/claimed",
                      headers={"X-API-Key": "mxk_not-a-real-key"}).status_code == 401

    # A key cannot mint another key — a leak can't extend its own foothold.
    assert client.post("/v1/agent-keys", headers={"Authorization": f"Bearer {secret}"},
                       json={"label": "escalate"}).status_code == 401

    key_id = minted["key_id"]
    assert client.delete(f"/v1/agent-keys/{key_id}", headers=owner).status_code == 200
    assert client.get("/v1/household-gigs/claimed",
                      headers={"X-API-Key": secret}).status_code == 401
    assert client.delete(f"/v1/agent-keys/{key_id}", headers=owner).status_code == 409


def test_agent_key_claims_and_reports_a_gig(client):
    """The whole point: an autonomous agent runs the gig loop with no session."""
    import household
    home = _signup(client, "home7@t.dev")
    bot_owner = _signup(client, "bot7@t.dev")
    key = client.post("/v1/agent-keys", headers=bot_owner,
                      json={"label": "bot"}).json()["key"]
    agent = {"X-API-Key": key}

    gig_id = _post_gig(client, home).json()["gig_id"]
    board = client.get("/v1/household-gigs", headers=agent).json()
    assert board["total"] == 1

    assert client.post(f"/v1/household-gigs/{gig_id}/claim", headers=agent,
                       json={"agent_payment_address": "0xBot"}).status_code == 200
    cycle_id = household.generate_due_cycles()[0][1]["cycle_id"]
    rep = client.post(f"/v1/household-gigs/{gig_id}/cycles/{cycle_id}/status",
                      headers=agent, json={"status": "done"})
    assert rep.status_code == 200 and rep.json()["self_reported"] is True

    # The household sees the key's owner, not a nameless machine.
    dash = client.get(f"/v1/household-gigs/{gig_id}/dashboard", headers=home).json()
    assert dash["agent"]["email"] == "bot7@t.dev"


def test_agent_key_cannot_reach_another_users_gig(client):
    home = _signup(client, "home8@t.dev")
    outsider = _signup(client, "outsider8@t.dev")
    key = client.post("/v1/agent-keys", headers=outsider, json={}).json()["key"]
    gig_id = _post_gig(client, home).json()["gig_id"]
    assert client.get(f"/v1/household-gigs/{gig_id}/dashboard",
                      headers={"X-API-Key": key}).status_code == 403


# ── service_details: household PII, released only on claim ───────────────────

def test_service_details_never_reach_the_public_board(client):
    home = _signup(client, "home9@t.dev")
    agent = _signup(client, "agent9@t.dev")
    secret = "Meter 04123456789\nToken to 0803 000 0000\nIkeja Electric"
    gig_id = _post_gig(client, home, service_details=secret).json()["gig_id"]

    # Select by id: other tests leave open gigs on the board and created_at ties
    # at second granularity, so position is not stable.
    board = client.get("/v1/household-gigs").json()["household_gigs"]
    mine = next(g for g in board if g["gig_id"] == gig_id)
    assert "service_details" not in mine
    assert mine["has_service_details"] is True
    assert "04123456789" not in json.dumps(board)   # not in ANY row on the board

    # Released to the agent only once they've claimed it.
    client.post(f"/v1/household-gigs/{gig_id}/claim", headers=agent,
                json={"agent_payment_address": "0xA"})
    claimed = client.get("/v1/household-gigs/claimed", headers=agent).json()
    assert claimed["household_gigs"][0]["service_details"] == secret

    # ...and never to anyone else.
    stranger = _signup(client, "stranger9@t.dev")
    assert client.get("/v1/household-gigs/claimed",
                      headers=stranger).json()["household_gigs"] == []


def test_service_details_stay_editable_after_claim(client):
    """Unlike the commercial terms: a mistyped meter number has to be fixable, or
    every cycle after it fails."""
    home = _signup(client, "home10@t.dev")
    agent = _signup(client, "agent10@t.dev")
    gig_id = _post_gig(client, home, service_details="Meter 0000 (wrong)").json()["gig_id"]
    client.post(f"/v1/household-gigs/{gig_id}/claim", headers=agent,
                json={"agent_payment_address": "0xA"})

    assert client.patch(f"/v1/household-gigs/{gig_id}", headers=home,
                        json={"budget_amount": "1"}).status_code == 409   # terms frozen
    fixed = client.patch(f"/v1/household-gigs/{gig_id}", headers=home,
                         json={"service_details": "Meter 04123456789"})
    assert fixed.status_code == 200
    assert client.get("/v1/household-gigs/claimed", headers=agent).json()[
        "household_gigs"][0]["service_details"] == "Meter 04123456789"
