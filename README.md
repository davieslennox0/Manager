# ManagerX

Job-first pipeline: take a job posting → generate a CV tailored to exactly that
posting → when the offer/gig lands, draft the work agreement from the same data →
sign it onchain → the executed contract becomes verified, unfakeable work history
that strengthens every future CV.

## The data spine

One profile object per user (experience, skills, education). Every artifact is a
projection of it:

- **Tailored CV** — one-off generation per job: mirrors the posting's language,
  reorders matching skills, drops irrelevant experience. Review, edit, export PDF.
- **Work agreement** — drafted on offer acceptance: claimed skills become
  scope-of-work clauses; payment/duration pulled from the posting where stated.
- **Verified work history** — written back into the spine only when the agreement
  is fully executed onchain (signed, timestamped, checkable by anyone).

## Onchain signing — SignatureRegistry.sol

X Layer mainnet (chain 196): [`0x78fBD5B1b50B80045a03D272D12B357a374a01c3`](https://www.okx.com/web3/explorer/xlayer/address/0x78fBD5B1b50B80045a03D272D12B357a374a01c3)

Dual privacy mode per agreement: `HASH_ONLY` (nothing but the sha256 doc hash
onchain) or `WITH_METADATA` (title + parties too). Signers are wallet addresses;
each signature is a real `sign()` transaction from that wallet. When the last
signer signs, the contract emits `Executed` — the backend verifies chain state
before trusting anything the browser reports.

## Discovery layer

A scanner polls configured sources — Greenhouse/Lever public board APIs per firm,
RSS aggregators, LLM-assisted page scrape as fallback — normalizes listings into
a common schema, dedups across sources, and feeds:

- the public, filterable job board (ecosystem / role / firm / remote), and
- email digests (subscribe with filters; plain SMTP, gated off until creds are set).

Scanner-sourced listings and user-pasted postings feed the same tailored-CV
pipeline.

## Stack

FastAPI + SQLite (WAL) · Gemini→Groq LLM fallback chain · fpdf2 PDF export ·
Vite/React frontend (static dist served by the API) · ethers v6 browser-wallet
signing · Foundry for the contract. Port 8011, PM2 app `workos-api`.

```bash
cp .env.example .env       # fill WORKOS_SECRET_KEY, LLM keys
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cd frontend && npm install && npm run build
cd ../backend && ../.venv/bin/python -m uvicorn main:app --port 8011
```
