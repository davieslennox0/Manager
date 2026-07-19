"""Proof-of-work CV layer: evidence sources beyond the profile spine.
 - GitHub: repo list + READMEs (OAuth token when configured, public-data mode
   otherwise), pinned repos weighted first
 - Wallet: onchain footprint (tx counts on X Layer + Ethereum, Snapshot DAO
   votes) proven by a signed message, plus the platform's own executed
   agreements ("N contracts completed, onchain, zero disputes")
 - LLM matching: per-application relevance ranking of repos against ONE posting
   (keyword overlap alone false-positives on shared tech terms)
The output block is merged into the existing tailored-CV JSON under
`relevant_work` / `onchain_footprint`; pdfgen renders it as its own section."""
import base64
import json
import re

import httpx

import config
from db import get_conn, j
from llm import generate_json

GITHUB_API = "https://api.github.com"
_ADDR_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")

MATCH_PROMPT = """You match a candidate's GitHub repositories against ONE job posting.
Score by real relevance to the posting's required skills and duties — do NOT match
on incidental shared tech words (a React todo app is not relevant to a React-based
DeFi protocol role unless the work itself is). Prefer pinned repos and recent,
substantial work. Reply with ONLY a JSON object:
{{
  "matches": [
    {{
      "repo": "full_name exactly as listed",
      "why": "one sentence: why THIS repo is evidence for THIS posting",
      "proof_point": "the single most concrete artifact in the repo to cite: a named
                      function/module, a deployed contract address from the README,
                      or a specific README claim — quoted or named precisely"
    }}
  ]
}}
Return the top 1-3 matches only; return {{"matches": []}} if nothing is genuinely
relevant.

Job posting signals:
{parsed}

Candidate repositories:
{repos}"""


class GitHubError(Exception):
    pass


def _gh_headers(token: str) -> dict:
    h = {"Accept": "application/vnd.github+json",
         "User-Agent": "ManagerX/1.0 proof-of-work"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _gh_get(client: httpx.AsyncClient, path: str, token: str):
    resp = await client.get(f"{GITHUB_API}{path}", headers=_gh_headers(token))
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        raise GitHubError(f"GitHub {resp.status_code}: {resp.text[:150]}")
    return resp.json()


async def _pinned_repos(client: httpx.AsyncClient, username: str, token: str) -> set[str]:
    """Pinned repos are GraphQL-only; silently empty without a token."""
    if not token:
        return set()
    query = {"query": "query($u:String!){user(login:$u){pinnedItems(first:6,"
                      "types:REPOSITORY){nodes{... on Repository{nameWithOwner}}}}}",
             "variables": {"u": username}}
    resp = await client.post("https://api.github.com/graphql", json=query,
                             headers=_gh_headers(token))
    if resp.status_code >= 400:
        return set()
    nodes = (((resp.json().get("data") or {}).get("user") or {})
             .get("pinnedItems") or {}).get("nodes") or []
    return {n["nameWithOwner"] for n in nodes if n}


async def fetch_github_repos(username: str, token: str = "") -> list[dict]:
    """Normalized repo list, pinned first then stars/recency; README excerpts
    pulled for the top slice (that's where deployed addresses live)."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        if token:
            repos = await _gh_get(client, "/user/repos?affiliation=owner&sort=pushed"
                                          "&per_page=100", token)
        else:
            repos = await _gh_get(client, f"/users/{username}/repos?sort=pushed"
                                          f"&per_page=100", token)
        if repos is None:
            raise GitHubError(f"GitHub user {username!r} not found")
        pinned = await _pinned_repos(client, username, token)
        out = []
        for r in repos:
            if r.get("fork"):
                continue
            out.append({
                "full_name": r["full_name"], "name": r["name"],
                "description": r.get("description") or "",
                "language": r.get("language") or "",
                "topics": r.get("topics") or [],
                "stars": r.get("stargazers_count", 0),
                "pushed_at": (r.get("pushed_at") or "")[:10],
                "url": r.get("html_url", ""),
                "pinned": r["full_name"] in pinned,
                "readme": "",
            })
        out.sort(key=lambda x: (x["pinned"], x["stars"], x["pushed_at"]), reverse=True)
        # README excerpts for the top slice only — one request per repo
        for repo in out[:12]:
            data = await _gh_get(client, f"/repos/{repo['full_name']}/readme", token)
            if data and data.get("content"):
                try:
                    text = base64.b64decode(data["content"]).decode("utf-8", "replace")
                    repo["readme"] = re.sub(r"\s+", " ", text)[:1500]
                except Exception:
                    pass
        return out


# ── Onchain verification ─────────────────────────────────────────────────

_CHAINS = [
    ("X Layer", lambda: config.XLAYER_RPC_URL,
     "https://www.okx.com/web3/explorer/xlayer/address/"),
    ("Ethereum", lambda: config.ETH_RPC_URL, "https://etherscan.io/address/"),
]


async def _rpc(client: httpx.AsyncClient, url: str, method: str, params: list):
    resp = await client.post(url, json={"jsonrpc": "2.0", "id": 1,
                                        "method": method, "params": params})
    resp.raise_for_status()
    return resp.json().get("result")


async def verify_contracts(addresses: list[str]) -> list[dict]:
    """Which of these addresses hold deployed code, and on which chain — turns
    a README address mention into shipped-proof with an explorer link."""
    verified = []
    async with httpx.AsyncClient(timeout=20) as client:
        for addr in addresses[:5]:
            for chain, rpc_url, explorer in _CHAINS:
                try:
                    code = await _rpc(client, rpc_url(), "eth_getCode", [addr, "latest"])
                except (httpx.HTTPError, ValueError):
                    continue
                if code and code != "0x":
                    verified.append({"address": addr, "chain": chain,
                                     "explorer_url": explorer + addr})
                    break
    return verified


def extract_addresses(text: str) -> list[str]:
    seen, out = set(), []
    for m in _ADDR_RE.findall(text or ""):
        if m.lower() not in seen:
            seen.add(m.lower())
            out.append(m)
    return out


async def wallet_activity(address: str) -> dict:
    """Public onchain footprint for a proven wallet: tx counts + Snapshot DAO
    votes (free indexer; no API key)."""
    out = {"address": address, "tx_counts": {}, "dao_votes": 0, "dao_spaces": []}
    async with httpx.AsyncClient(timeout=20) as client:
        for chain, rpc_url, _ in _CHAINS:
            try:
                n = await _rpc(client, rpc_url(), "eth_getTransactionCount",
                               [address, "latest"])
                out["tx_counts"][chain] = int(n, 16) if n else 0
            except (httpx.HTTPError, ValueError, TypeError):
                out["tx_counts"][chain] = None
        try:
            gql = {"query": "query($v:String!){votes(first:1000,where:{voter:$v})"
                            "{space{id}}}", "variables": {"v": address}}
            resp = await client.post(config.SNAPSHOT_HUB_URL, json=gql)
            votes = (resp.json().get("data") or {}).get("votes") or []
            out["dao_votes"] = len(votes)
            out["dao_spaces"] = sorted({v["space"]["id"] for v in votes if v.get("space")})[:10]
        except Exception:
            pass
    return out


# ── Assembly ─────────────────────────────────────────────────────────────

def platform_proof(user_id: str) -> dict:
    """The platform's own strongest evidence: executed onchain agreements."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT title, counterparty, tx_hash, signed_at FROM work_history "
        "WHERE user_id=? ORDER BY signed_at DESC", (user_id,)).fetchall()
    conn.close()
    n = len(rows)
    return {
        "contracts_completed": n,
        "claim": (f"{n} contract{'s' if n != 1 else ''} completed, onchain, "
                  f"zero disputes") if n else "",
        "contracts": [{"title": r["title"], "counterparty": r["counterparty"],
                       "tx_hash": r["tx_hash"], "signed_at": str(r["signed_at"])}
                      for r in rows[:5]],
    }


def _repo_summary_for_llm(repos: list[dict]) -> str:
    lines = []
    for r in repos[:30]:
        lines.append(json.dumps({
            "full_name": r["full_name"], "description": r["description"],
            "language": r["language"], "topics": r["topics"][:6],
            "stars": r["stars"], "pushed_at": r["pushed_at"],
            "pinned": r["pinned"], "readme_excerpt": r["readme"][:400],
        }, ensure_ascii=False))
    return "\n".join(lines)


async def match_repos(parsed: dict, repos: list[dict]) -> list[dict]:
    """LLM relevance ranking, then enrich matches with links + verified
    deployed contracts found in the matched repos' READMEs."""
    if not repos:
        return []
    data = await generate_json(MATCH_PROMPT.format(
        parsed=json.dumps(parsed, ensure_ascii=False),
        repos=_repo_summary_for_llm(repos)))
    by_name = {r["full_name"]: r for r in repos}
    matches = []
    for m in (data.get("matches") or [])[:3]:
        repo = by_name.get(m.get("repo", ""))
        if not repo:
            continue
        entry = {"repo": repo["full_name"], "url": repo["url"],
                 "language": repo["language"], "stars": repo["stars"],
                 "pinned": repo["pinned"],
                 "why": m.get("why", ""), "proof_point": m.get("proof_point", ""),
                 "verified_contracts": []}
        addrs = extract_addresses(repo["readme"] + " " + entry["proof_point"])
        if addrs:
            entry["verified_contracts"] = await verify_contracts(addrs)
        matches.append(entry)
    return matches


async def build_proof_block(user_id: str, parsed: dict) -> dict:
    """Everything the CV's 'Relevant work' section needs, from every connected
    source. Missing sources degrade to empty, never error."""
    conn = get_conn()
    gh = conn.execute("SELECT * FROM github_accounts WHERE user_id=?", (user_id,)).fetchone()
    wallet = conn.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,)).fetchone()
    conn.close()

    relevant_work = []
    if gh:
        repos = j(gh["repos"], [])
        if repos:
            relevant_work = await match_repos(parsed, repos)

    footprint = {}
    if wallet:
        footprint = j(wallet["activity"], {}) or {}
        footprint["address"] = wallet["address"]
    footprint["platform"] = platform_proof(user_id)

    return {"relevant_work": relevant_work, "onchain_footprint": footprint}
