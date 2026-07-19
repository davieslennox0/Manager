import { useEffect, useState } from "react";
import { api } from "../lib/api";

// Public verified-track-record page: /u/{handle}. Reads only what the owner
// chose to publish; every contract line is backed by an onchain tx link.
export default function TrackRecord({ handle }) {
  const [p, setP] = useState(null);
  const [err, setErr] = useState("");
  const [card, setCard] = useState(null); // contract whose proof card is open

  useEffect(() => {
    api("GET", `/v1/public/${handle}`).then(setP).catch((e) => setErr(e.message));
  }, [handle]);

  if (err) return <p className="text-sm text-neutral-500 py-12 text-center">{err}</p>;
  if (!p) return <p className="text-sm text-neutral-500">Loading…</p>;

  const stats = p.stats || {};
  return (
    <div className="space-y-8">
      <div>
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-3xl font-semibold tracking-tight">{p.full_name || `@${p.handle}`}</h1>
          <span className="tag !border-green-700/50 text-green-800 dark:text-green-400 font-medium">
            ✓ verified onchain
          </span>
        </div>
        {p.headline && <p className="text-neutral-600 dark:text-neutral-400 mt-1">{p.headline}</p>}
        {p.claim && (
          <p className="text-wos-ok dark:text-green-400 font-medium mt-2">{p.claim}</p>
        )}
        <div className="flex flex-wrap gap-x-6 gap-y-1 mt-3 text-sm text-neutral-600 dark:text-neutral-400">
          <span><b className="text-black dark:text-white">{stats.contracts_completed || 0}</b> contracts executed onchain</span>
          <span><b className="text-black dark:text-white">{stats.cvs_tailored || 0}</b> tailored CVs</span>
          {stats.dao_votes > 0 && (
            <span><b className="text-black dark:text-white">{stats.dao_votes}</b> DAO votes</span>
          )}
          {(p.links || []).map((l) => (
            <a key={l.url} className="underline hover:text-black dark:hover:text-white"
               href={l.url} target="_blank" rel="noreferrer">{l.label} ↗</a>
          ))}
        </div>
      </div>

      <div>
        <h2 className="font-medium mb-1">Onchain-signed contracts</h2>
        <p className="text-sm text-neutral-600 dark:text-neutral-400 mb-3">
          Each entry was signed by all parties via SignatureRegistry on X Layer —
          the transaction is the reference, not a claim.
        </p>
        {(p.contracts || []).length === 0 && (
          <p className="text-sm text-neutral-500">No executed contracts yet.</p>
        )}
        <div className="space-y-3">
          {(p.contracts || []).map((c) => (
            <div key={c.entry_id} className="panel flex items-start gap-4 flex-wrap">
              <div className="flex-1 min-w-[240px]">
                <div className="font-medium">{c.title}</div>
                <div className="text-sm text-neutral-600 dark:text-neutral-400">
                  {c.firm && `${c.firm} · `}
                  {[c.start, c.end].filter(Boolean).join(" – ") || c.signed_at.slice(0, 10)}
                </div>
                <p className="font-mono text-xs mt-1 break-all">
                  <a className="underline" href={c.tx_url} target="_blank" rel="noreferrer">
                    {c.tx_hash.slice(0, 18)}… ↗
                  </a>
                  <span className="text-wos-ok dark:text-green-400 ml-2">executed ✓</span>
                </p>
              </div>
              <button className="btn-ghost shrink-0" onClick={() => setCard(c)}>
                Proof card
              </button>
            </div>
          ))}
        </div>
      </div>

      {p.github && (
        <div>
          <h2 className="font-medium mb-1">
            Proof-of-work — <a className="underline" href={`https://github.com/${p.github.username}`}
                               target="_blank" rel="noreferrer">@{p.github.username}</a>
          </h2>
          <div className="grid sm:grid-cols-2 gap-3 mt-3">
            {(p.github.top_repos || []).map((r) => (
              <a key={r.full_name} className="card-inner block hover:border-wos-accent dark:hover:border-white transition-colors"
                 href={r.url} target="_blank" rel="noreferrer">
                <div className="text-sm font-medium">
                  {r.full_name}
                  {r.pinned && <span className="tag ml-2">pinned</span>}
                </div>
                {r.description && (
                  <p className="text-xs text-neutral-600 dark:text-neutral-400 mt-1 line-clamp-2">{r.description}</p>
                )}
                <p className="text-xs text-neutral-500 mt-1">
                  {[r.language, r.stars > 0 && `★ ${r.stars}`, r.pushed_at].filter(Boolean).join(" · ")}
                </p>
              </a>
            ))}
          </div>
        </div>
      )}

      {card && <ProofCardModal contract={card} onClose={() => setCard(null)} />}
    </div>
  );
}

function ProofCardModal({ contract, onClose }) {
  const [copied, setCopied] = useState(false);
  const cardUrl = contract.card_url;
  const shareText = encodeURIComponent(
    `${contract.title}${contract.firm ? ` @ ${contract.firm}` : ""} — completed and signed onchain. Verified: ${contract.tx_url}`);

  function copy() {
    navigator.clipboard.writeText(cardUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <div className="fixed inset-0 z-30 bg-black/60 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="bg-white dark:bg-wos-dpanel rounded-xl p-4 max-w-2xl w-full"
           onClick={(e) => e.stopPropagation()}>
        <img src={cardUrl} alt={`Proof card — ${contract.title}`}
             className="w-full rounded-lg border border-wos-border dark:border-wos-dborder" />
        <div className="flex flex-wrap gap-2 mt-3">
          <button className="btn-ghost" onClick={copy}>
            {copied ? "Copied ✓" : "Copy card link"}
          </button>
          <a className="btn-ghost" href={cardUrl} download>Download SVG</a>
          <a className="btn" target="_blank" rel="noreferrer"
             href={`https://twitter.com/intent/tweet?text=${shareText}`}>
            Share on X
          </a>
          <button className="btn-ghost ml-auto" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
