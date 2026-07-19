"""Document vault: offers/contracts/NDAs the user RECEIVED. Upload -> AI review
(terms, red flags, deadlines, diff against the linked job's parsed posting) ->
optional single-signer onchain anchor: the user's wallet writes
createAgreement(docHash, [self]) + sign to SignatureRegistry, making a
timestamped, tamper-evident record of exactly what they were sent — no
counterparty required, which is the whole point on a job-seeker platform."""
import datetime
import json
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

import chain
import config
import docreview
from auth import current_user
from db import get_conn, j
from llm import LLMError

router = APIRouter(prefix="/v1/documents", tags=["documents"])

KINDS = ("offer", "contract", "nda", "other")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class DocumentPatch(BaseModel):
    job_id: str | None = None       # '' unlinks
    kind: str | None = Field(None, pattern="^(offer|contract|nda|other)$")


class DocumentAnchor(BaseModel):
    chain_agreement_id: int
    create_tx: str


def _document(conn, doc_id: str, user_id: str):
    row = conn.execute("SELECT * FROM documents WHERE doc_id = ? AND user_id = ?",
                       (doc_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "No such document")
    return row


def _card(row, full: bool = False) -> dict:
    out = {
        "doc_id": row["doc_id"], "job_id": row["job_id"], "kind": row["kind"],
        "filename": row["filename"], "doc_hash": row["doc_hash"],
        "status": row["status"], "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
        "chain_agreement_id": row["chain_agreement_id"], "anchor_tx": row["anchor_tx"],
        "deadlines": j(row["deadlines"], []),
        "review": j(row["review"], {}),
    }
    if full:
        out["raw_text"] = row["raw_text"]
        if not row["chain_agreement_id"]:
            # The frontend appends the connected wallet as the sole signer.
            out["anchor_request"] = {
                "chain_id": config.CHAIN_ID, "registry": config.REGISTRY_ADDRESS,
                "function": "createAgreement(bytes32,address[],uint8,string)",
                "doc_hash": row["doc_hash"],
            }
    return out


async def _run_review(conn, row, user_id: str) -> dict | None:
    """Review in place; returns the review dict or None when the LLM chain is
    down (the upload is already stored — review can be retried)."""
    parsed = None
    if row["job_id"]:
        job = conn.execute("SELECT parsed FROM jobs WHERE job_id = ? AND user_id = ?",
                           (row["job_id"], user_id)).fetchone()
        parsed = j(job["parsed"], {}) if job else None
    try:
        review = await docreview.review_document(row["raw_text"], parsed)
    except LLMError:
        return None
    kind = review.get("kind") if review.get("kind") in KINDS else row["kind"]
    conn.execute(
        "UPDATE documents SET review=?, deadlines=?, kind=?, status='reviewed', "
        "reviewed_at=CURRENT_TIMESTAMP WHERE doc_id=? AND status != 'anchored'",
        (json.dumps(review, ensure_ascii=False),
         json.dumps(review.get("deadlines", []), ensure_ascii=False),
         kind, row["doc_id"]))
    # An anchored doc keeps its status but still takes the fresh review.
    conn.execute(
        "UPDATE documents SET review=?, deadlines=?, reviewed_at=CURRENT_TIMESTAMP "
        "WHERE doc_id=? AND status = 'anchored'",
        (json.dumps(review, ensure_ascii=False),
         json.dumps(review.get("deadlines", []), ensure_ascii=False), row["doc_id"]))
    conn.commit()
    return review


@router.post("")
async def upload_document(file: UploadFile | None = None, text: str = Form(""),
                          filename: str = Form(""), job_id: str = Form(""),
                          kind: str = Form("other"),
                          user: dict = Depends(current_user)):
    """Multipart upload (PDF or plain text file) or pasted text. The doc hash is
    computed over the exact uploaded bytes; the review runs inline."""
    if file is not None:
        data = await file.read()
        filename = filename or (file.filename or "")
    else:
        data = text.strip().encode()
    if not data:
        raise HTTPException(422, "Provide a file or pasted text")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Document too large (5 MB max)")
    try:
        raw_text = docreview.extract_text(data, filename).strip()
    except Exception:
        raise HTTPException(422, "Could not extract text — upload a text-based PDF "
                                 "or paste the content")
    if not raw_text:
        raise HTTPException(422, "No text found in the document (scanned image PDF?) "
                                 "— paste the content instead")
    if kind not in KINDS:
        kind = "other"
    conn = get_conn()
    if job_id:
        job = conn.execute("SELECT job_id FROM jobs WHERE job_id = ? AND user_id = ?",
                           (job_id, user["user_id"])).fetchone()
        if not job:
            conn.close()
            raise HTTPException(404, "No such job to link")
    doc_id = "doc_" + uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO documents (doc_id, user_id, job_id, kind, filename, raw_text, doc_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (doc_id, user["user_id"], job_id or None, kind, filename[:200],
         raw_text[:120000], docreview.document_hash(data)))
    conn.commit()
    row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    review = await _run_review(conn, row, user["user_id"])
    row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    conn.close()
    out = _card(row, full=True)
    if review is None:
        out["review_error"] = ("Document stored, but review is unavailable right now — "
                               "retry with POST /v1/documents/{doc_id}/review")
    return out


@router.get("")
async def list_documents(user: dict = Depends(current_user)):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM documents WHERE user_id = ? ORDER BY created_at DESC",
                        (user["user_id"],)).fetchall()
    conn.close()
    return {"documents": [_card(r) for r in rows]}


@router.get("/deadlines")
async def upcoming_deadlines(user: dict = Depends(current_user)):
    """Every dated obligation across the vault, soonest first — probation ends,
    notice windows, offer expiries, non-compete lapses."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM documents WHERE user_id = ?",
                        (user["user_id"],)).fetchall()
    conn.close()
    today = datetime.date.today()
    out = []
    for row in rows:
        for d in j(row["deadlines"], []):
            try:
                date = datetime.date.fromisoformat(str(d.get("date", "")))
            except ValueError:
                continue
            out.append({"doc_id": row["doc_id"], "filename": row["filename"],
                        "kind": row["kind"], "label": d.get("label", ""),
                        "date": date.isoformat(), "note": d.get("note", ""),
                        "days_left": (date - today).days})
    out.sort(key=lambda d: d["date"])
    return {"deadlines": out}


@router.get("/{doc_id}")
async def get_document(doc_id: str, user: dict = Depends(current_user)):
    conn = get_conn()
    row = _document(conn, doc_id, user["user_id"])
    conn.close()
    return _card(row, full=True)


@router.patch("/{doc_id}")
async def patch_document(doc_id: str, body: DocumentPatch,
                         user: dict = Depends(current_user)):
    conn = get_conn()
    row = _document(conn, doc_id, user["user_id"])
    job_id = row["job_id"]
    if body.job_id is not None:
        job_id = body.job_id or None
        if job_id and not conn.execute(
                "SELECT job_id FROM jobs WHERE job_id = ? AND user_id = ?",
                (job_id, user["user_id"])).fetchone():
            conn.close()
            raise HTTPException(404, "No such job to link")
    conn.execute("UPDATE documents SET job_id=?, kind=? WHERE doc_id=?",
                 (job_id, body.kind or row["kind"], doc_id))
    conn.commit()
    row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    conn.close()
    return _card(row)


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, user: dict = Depends(current_user)):
    conn = get_conn()
    _document(conn, doc_id, user["user_id"])
    conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    conn.commit()
    conn.close()
    return {"doc_id": doc_id, "deleted": True,
            "note": "Removed from the vault; an onchain anchor, if any, is immutable"}


@router.post("/{doc_id}/review")
async def rereview(doc_id: str, user: dict = Depends(current_user)):
    """Re-run the AI review — e.g. after linking the job the document answers."""
    conn = get_conn()
    row = _document(conn, doc_id, user["user_id"])
    review = await _run_review(conn, row, user["user_id"])
    row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    conn.close()
    if review is None:
        raise HTTPException(503, "Review unavailable — all LLM providers failed")
    return _card(row, full=True)


@router.post("/{doc_id}/anchor")
async def anchor_document(doc_id: str, body: DocumentAnchor,
                          user: dict = Depends(current_user)):
    """Frontend reports the mined createAgreement+sign txs; verified against the
    chain: the anchored hash must be this document's, signed by its sole signer."""
    conn = get_conn()
    row = _document(conn, doc_id, user["user_id"])
    conn.close()
    if row["chain_agreement_id"]:
        raise HTTPException(409, "Already anchored")
    if chain.tx_receipt_status(body.create_tx) != 1:
        raise HTTPException(422, "createAgreement tx not found or not successful yet")
    onchain = chain.read_agreement(body.chain_agreement_id)
    if onchain["doc_hash"].lower() != row["doc_hash"].lower():
        raise HTTPException(422, "Onchain doc hash does not match this document")
    if len(onchain["signers"]) != 1:
        raise HTTPException(422, "Anchor must be single-signer (your wallet only)")
    if not onchain["executed"]:
        raise HTTPException(422, "Not signed yet — send the sign() tx and retry")
    conn = get_conn()
    conn.execute("UPDATE documents SET chain_agreement_id=?, anchor_tx=?, "
                 "status='anchored' WHERE doc_id=?",
                 (body.chain_agreement_id, body.create_tx, doc_id))
    conn.commit()
    conn.close()
    return {"doc_id": doc_id, "status": "anchored", "onchain": onchain}
