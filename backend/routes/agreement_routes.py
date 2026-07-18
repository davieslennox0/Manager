"""Agreement stage: accepted job -> LLM draft from the same spine as the CV ->
signer wallets + privacy mode -> the browser wallet writes createAgreement/sign
to SignatureRegistry -> backend verifies onchain state -> executed agreements
become verified work-history entries in the profile spine."""
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from web3 import Web3

import chain
import config
import pipeline
from auth import current_user
from db import get_conn, j
from llm import LLMError

router = APIRouter(prefix="/v1/agreements", tags=["agreements"])


class AgreementEdit(BaseModel):
    content: dict


class AgreementFinalize(BaseModel):
    privacy_mode: str = Field("HASH_ONLY", pattern="^(HASH_ONLY|WITH_METADATA)$")
    signers: list[str] = Field(min_length=1, max_length=16,
                               description="wallet addresses that must sign")


class AgreementAnchor(BaseModel):
    chain_agreement_id: int
    create_tx: str


def _agreement(conn, agreement_id: str, user_id: str):
    row = conn.execute("SELECT * FROM agreements WHERE agreement_id = ? AND user_id = ?",
                       (agreement_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "No such agreement")
    return row


@router.post("/draft/{job_id}")
async def draft(job_id: str, user: dict = Depends(current_user)):
    conn = get_conn()
    job = conn.execute("SELECT * FROM jobs WHERE job_id = ? AND user_id = ?",
                       (job_id, user["user_id"])).fetchone()
    conn.close()
    if not job:
        raise HTTPException(404, "No such job")
    if job["status"] not in ("accepted", "contracted"):
        raise HTTPException(409, "Mark the job accepted first — agreements are drafted "
                                 "only for accepted offers/gigs")
    spine = pipeline.load_spine(user["user_id"])
    try:
        content = await pipeline.draft_agreement(j(job["parsed"], {}), spine)
    except LLMError as e:
        raise HTTPException(503, f"Agreement drafting unavailable: {e}")
    agreement_id = "agr_" + uuid.uuid4().hex[:12]
    conn = get_conn()
    conn.execute(
        "INSERT INTO agreements (agreement_id, job_id, user_id, content) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(job_id) DO UPDATE SET content=excluded.content "
        "WHERE agreements.status = 'draft'",
        (agreement_id, job_id, user["user_id"], json.dumps(content, ensure_ascii=False)))
    conn.commit()
    row = conn.execute("SELECT * FROM agreements WHERE job_id = ?", (job_id,)).fetchone()
    conn.close()
    if row["status"] != "draft":
        raise HTTPException(409, "Agreement already finalized — it can't be redrafted")
    return {"agreement_id": row["agreement_id"], "content": content, "status": "draft"}


@router.get("")
async def list_agreements(user: dict = Depends(current_user)):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM agreements WHERE user_id = ? ORDER BY created_at DESC",
                        (user["user_id"],)).fetchall()
    conn.close()
    return {"agreements": [{**dict(r), "content": j(r["content"], {}),
                            "signers": j(r["signers"], [])} for r in rows]}


@router.get("/{agreement_id}")
async def get_agreement(agreement_id: str, user: dict = Depends(current_user)):
    conn = get_conn()
    row = _agreement(conn, agreement_id, user["user_id"])
    conn.close()
    out = {**dict(row), "content": j(row["content"], {}), "signers": j(row["signers"], [])}
    if row["status"] == "pending_signatures" and not row["chain_agreement_id"]:
        content = j(row["content"], {})
        metadata = ""
        if row["privacy_mode"] == "WITH_METADATA":
            metadata = json.dumps({"title": content.get("title", ""),
                                   "parties": content.get("parties", [])},
                                  ensure_ascii=False)
        out["tx_request"] = {
            "chain_id": config.CHAIN_ID, "registry": config.REGISTRY_ADDRESS,
            "function": "createAgreement(bytes32,address[],uint8,string)",
            "args": [row["doc_hash"], j(row["signers"], []),
                     1 if row["privacy_mode"] == "WITH_METADATA" else 0, metadata],
        }
    if row["chain_agreement_id"]:
        try:
            out["onchain"] = chain.read_agreement(row["chain_agreement_id"])
        except Exception as e:
            out["onchain_error"] = str(e)
    return out


@router.put("/{agreement_id}")
async def edit(agreement_id: str, body: AgreementEdit, user: dict = Depends(current_user)):
    conn = get_conn()
    row = _agreement(conn, agreement_id, user["user_id"])
    if row["status"] != "draft":
        conn.close()
        raise HTTPException(409, "Finalized agreements are immutable — the doc hash "
                                 "is what gets signed")
    conn.execute("UPDATE agreements SET content=? WHERE agreement_id=?",
                 (json.dumps(body.content, ensure_ascii=False), agreement_id))
    conn.commit()
    conn.close()
    return {"agreement_id": agreement_id, "content": body.content}


@router.post("/{agreement_id}/finalize")
async def finalize(agreement_id: str, body: AgreementFinalize,
                   user: dict = Depends(current_user)):
    """Lock content, compute the doc hash, and hand the frontend everything the
    wallet needs to send createAgreement() onchain."""
    try:
        signers = [Web3.to_checksum_address(s) for s in body.signers]
    except Exception:
        raise HTTPException(422, "Invalid signer address")
    conn = get_conn()
    row = _agreement(conn, agreement_id, user["user_id"])
    if row["status"] != "draft":
        conn.close()
        raise HTTPException(409, "Already finalized")
    content = j(row["content"], {})
    doc_hash = pipeline.agreement_doc_hash(content)
    metadata = ""
    if body.privacy_mode == "WITH_METADATA":
        metadata = json.dumps({"title": content.get("title", ""),
                               "parties": content.get("parties", [])},
                              ensure_ascii=False)
    conn.execute(
        "UPDATE agreements SET doc_hash=?, privacy_mode=?, signers=?, "
        "status='pending_signatures' WHERE agreement_id=?",
        (doc_hash, body.privacy_mode, json.dumps(signers), agreement_id))
    conn.commit()
    conn.close()
    return {
        "agreement_id": agreement_id, "status": "pending_signatures",
        "doc_hash": doc_hash, "privacy_mode": body.privacy_mode, "signers": signers,
        "tx_request": {
            "chain_id": config.CHAIN_ID,
            "registry": config.REGISTRY_ADDRESS,
            "function": "createAgreement(bytes32,address[],uint8,string)",
            "args": [doc_hash, signers,
                     1 if body.privacy_mode == "WITH_METADATA" else 0, metadata],
        },
    }


@router.post("/{agreement_id}/anchor")
async def anchor(agreement_id: str, body: AgreementAnchor,
                 user: dict = Depends(current_user)):
    """Frontend reports the mined createAgreement tx; we verify against the chain
    (real read, no trust in the client) and store the onchain id."""
    conn = get_conn()
    row = _agreement(conn, agreement_id, user["user_id"])
    conn.close()
    if row["status"] != "pending_signatures":
        raise HTTPException(409, f"Agreement is {row['status']}")
    if chain.tx_receipt_status(body.create_tx) != 1:
        raise HTTPException(422, "createAgreement tx not found or not successful yet")
    onchain = chain.read_agreement(body.chain_agreement_id)
    if onchain["doc_hash"].lower() != row["doc_hash"].lower():
        raise HTTPException(422, "Onchain doc hash does not match this agreement")
    if sorted(onchain["signers"]) != sorted(s.lower() for s in j(row["signers"], [])):
        raise HTTPException(422, "Onchain signer set does not match this agreement")
    conn = get_conn()
    conn.execute("UPDATE agreements SET chain_agreement_id=?, create_tx=? WHERE agreement_id=?",
                 (body.chain_agreement_id, body.create_tx, agreement_id))
    conn.commit()
    conn.close()
    return {"agreement_id": agreement_id, "onchain": onchain}


@router.post("/{agreement_id}/refresh")
async def refresh(agreement_id: str, user: dict = Depends(current_user)):
    """Re-read onchain state; on full execution, write the verified work-history
    entry back into the profile spine (the feedback loop that makes future CVs
    cite an unfakeable track record)."""
    conn = get_conn()
    row = _agreement(conn, agreement_id, user["user_id"])
    conn.close()
    if not row["chain_agreement_id"]:
        raise HTTPException(409, "Not anchored onchain yet")
    onchain = chain.read_agreement(row["chain_agreement_id"])
    if not onchain["executed"] or row["status"] == "executed":
        return {"agreement_id": agreement_id, "status": row["status"], "onchain": onchain}

    content = j(row["content"], {})
    parties = content.get("parties", [])
    counterparty = next((p.get("name", "") for p in parties
                         if p.get("role", "").lower() != "contractor"), "")
    duration = content.get("duration", {}) or {}
    conn = get_conn()
    conn.execute("UPDATE agreements SET status='executed', executed_at=CURRENT_TIMESTAMP "
                 "WHERE agreement_id=?", (agreement_id,))
    conn.execute("UPDATE jobs SET status='contracted' WHERE job_id=?", (row["job_id"],))
    conn.execute(
        """INSERT INTO work_history (entry_id, user_id, agreement_id, title, counterparty,
           scope, start_date, end_date, doc_hash, tx_hash, chain_agreement_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("wh_" + uuid.uuid4().hex[:12], user["user_id"], agreement_id,
         content.get("title", "Work Agreement"), counterparty,
         json.dumps(content.get("scope_of_work", []), ensure_ascii=False),
         str(duration.get("start", "")), str(duration.get("end_or_term", "")),
         row["doc_hash"], row["create_tx"], row["chain_agreement_id"]))
    conn.commit()
    conn.close()
    return {"agreement_id": agreement_id, "status": "executed", "onchain": onchain,
            "work_history": "verified entry added to your profile spine"}
