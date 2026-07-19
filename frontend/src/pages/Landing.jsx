import { useEffect, useState } from "react";
import { api, getToken } from "../lib/api";
import { Link } from "../lib/router";

const FEATURES = [
  {
    tag: "discover",
    title: "A job board that scans for you",
    body: "Career pages and Web3 job feeds are polled continuously — Greenhouse, Lever, crypto-native aggregators — normalized, deduplicated, and categorized. Filter by ecosystem, category, or firm; or get digest emails matched to your filters.",
  },
  {
    tag: "apply",
    title: "One CV per job, not one CV for all jobs",
    body: "Pick a posting and ManagerX generates a CV tailored to exactly it: your skills reordered to mirror the listing's own language, irrelevant experience dropped. Nothing invented — it only draws from your profile. Review, edit, export as PDF.",
  },
  {
    tag: "review",
    title: "The offer gets read before you sign",
    body: "Upload the offer, contract, or NDA they sent. ManagerX extracts the terms, flags risky clauses with a concrete counter-ask for each, pulls every deadline — and diffs the document against the posting you applied to, because we hold what was promised.",
  },
  {
    tag: "prove",
    title: "Track record you can prove",
    body: "Anchor any document's hash onchain from your wallet — a timestamped, tamper-evident record of exactly what you were sent, checkable by anyone against the original file. No counterparty needed. Every anchored document strengthens the next application.",
  },
];

const STEPS = [
  ["Build your profile", "Skills, experience, education — entered once, the spine of everything."],
  ["Pick or paste a job", "From the scanned board, or paste any posting URL or text."],
  ["Get the tailored CV", "Generated for that posting alone. Edit, export PDF — the application is yours to send, we just make it sharp."],
  ["Upload what they send back", "Offer, contract, NDA — AI review extracts the terms, flags the traps, and diffs it against the posting."],
  ["Anchor it onchain", "One wallet transaction stamps the document hash on X Layer — proof of what you were sent, forever."],
];

export default function Landing() {
  const [stats, setStats] = useState(null);
  const authed = !!getToken();

  useEffect(() => {
    api("GET", "/v1/listings?limit=1")
      .then((d) => setStats({ total: d.total, categories: d.facets.categories.length }))
      .catch(() => {});
  }, []);

  return (
    <div>
      {/* ── Hero ────────────────────────────────────────────────────── */}
      <section className="max-w-5xl mx-auto px-4 pt-20 pb-16">
        <p className="font-mono text-xs uppercase tracking-widest text-neutral-500 mb-4">
          Job → tailored CV → offer review → anchored proof
        </p>
        <h1 className="text-5xl sm:text-6xl font-semibold tracking-tight leading-[1.05] max-w-3xl">
          Your next Web3 role,
          <br />
          handled end to end.
        </h1>
        <p className="text-lg text-neutral-600 dark:text-neutral-400 mt-6 max-w-2xl">
          ManagerX scans the Web3 job market, writes a CV tuned to each posting from
          your one profile, and — when the offer lands — reads every clause before
          you sign it. Anchored documents become verifiable track record.
        </p>
        <div className="flex flex-wrap gap-3 mt-8">
          <Link to={authed ? "/jobs" : "/signup"}
                className="btn !px-8 !py-3.5 !text-base !rounded-xl">
            {authed ? "Open my pipeline" : "Sign in / create account"}
          </Link>
          <Link to="/board" className="btn-ghost !px-8 !py-3.5 !text-base !rounded-xl">
            Browse the job board
          </Link>
        </div>
        {stats && (
          <div className="flex flex-wrap gap-x-8 gap-y-2 mt-10 font-mono text-sm text-neutral-600 dark:text-neutral-400">
            <span><b className="text-black dark:text-white">{stats.total}</b> open roles indexed</span>
            <span><b className="text-black dark:text-white">{stats.categories}</b> categories</span>
            <span>registry live on <b className="text-black dark:text-white">X Layer</b></span>
          </div>
        )}
      </section>

      {/* ── Features ────────────────────────────────────────────────── */}
      <section id="features" className="border-t border-wos-border dark:border-wos-dborder scroll-mt-16">
        <div className="max-w-5xl mx-auto px-4 py-16">
          <h2 className="text-2xl font-semibold tracking-tight mb-8">
            One profile in. Everything else is generated.
          </h2>
          <div className="grid sm:grid-cols-2 gap-4">
            {FEATURES.map((f) => (
              <div key={f.tag} className="panel">
                <p className="font-mono text-xs uppercase tracking-widest text-neutral-500 mb-2">
                  {f.tag}
                </p>
                <h3 className="font-medium text-lg mb-2">{f.title}</h3>
                <p className="text-sm text-neutral-600 dark:text-neutral-400 leading-relaxed">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How it works ────────────────────────────────────────────── */}
      <section id="how" className="border-t border-wos-border dark:border-wos-dborder scroll-mt-16">
        <div className="max-w-5xl mx-auto px-4 py-16">
          <h2 className="text-2xl font-semibold tracking-tight mb-8">How it works</h2>
          <ol className="grid sm:grid-cols-5 gap-4">
            {STEPS.map(([title, body], i) => (
              <li key={title} className="relative">
                <div className="font-mono text-3xl text-neutral-300 dark:text-neutral-600 mb-2">
                  {String(i + 1).padStart(2, "0")}
                </div>
                <div className="font-medium text-sm mb-1">{title}</div>
                <p className="text-xs text-neutral-600 dark:text-neutral-400 leading-relaxed">{body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── Onchain strip ───────────────────────────────────────────── */}
      <section className="border-t border-wos-border dark:border-wos-dborder bg-wos-panel dark:bg-wos-dpanel">
        <div className="max-w-5xl mx-auto px-4 py-10">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex-1 min-w-[260px]">
              <h3 className="font-medium">Anchors are real transactions.</h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400 mt-1">
                Document hashes live in the SignatureRegistry contract on X Layer
                (chain 196). Every anchor is a transaction from your own wallet;
                anyone can verify a document against its onchain hash.
              </p>
            </div>
            <a className="font-mono text-xs underline break-all"
               href="https://www.okx.com/web3/explorer/xlayer/address/0x78fBD5B1b50B80045a03D272D12B357a374a01c3"
               target="_blank" rel="noreferrer">
              0x78fBD5B1b50B80045a03D272D12B357a374a01c3 ↗
            </a>
          </div>
        </div>
      </section>

      {/* ── Final CTA ───────────────────────────────────────────────── */}
      <section className="border-t border-wos-border dark:border-wos-dborder">
        <div className="max-w-5xl mx-auto px-4 py-16 text-center">
          <h2 className="text-3xl font-semibold tracking-tight">
            Start with your profile.
          </h2>
          <p className="text-neutral-600 dark:text-neutral-400 mt-3 max-w-xl mx-auto">
            Ten minutes of setup, then every application and every offer review is a
            projection of the same data — and every anchored document strengthens it.
          </p>
          <Link to={authed ? "/profile" : "/signup"}
                className="btn !px-10 !py-4 !text-base !rounded-xl inline-block mt-7">
            {authed ? "Go to my profile" : "Create your account"}
          </Link>
        </div>
      </section>
    </div>
  );
}
