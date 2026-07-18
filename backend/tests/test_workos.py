import json
import os
import tempfile

os.environ["WORKOS_SECRET_KEY"] = "test-secret"
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["SCANNER_ENABLED"] = "0"

import pytest
from fastapi.testclient import TestClient

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
