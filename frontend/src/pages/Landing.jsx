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
    tag: "funded",
    title: "Firms that just raised, before they post",
    body: "Funding-round coverage is watched alongside the job feeds. Firms with open roles get flagged newly funded on the board; firms that raised but haven't posted yet sit in a separate tier — recently funded, likely hiring soon — so you can reach out ahead of the listing.",
  },
  {
    tag: "benchmark",
    title: "Know the fit before you spend the effort",
    body: "Score any résumé against a specific posting: ATS-readiness, skill-coverage gaps, parse problems that would break a machine reader, and a prioritized list of positioning fixes. A fast, reproducible signal on whether the role is worth an application.",
  },
  {
    tag: "apply",
    title: "One CV per job, not one CV for all jobs",
    body: "Pick a posting and ManagerX generates a CV tailored to exactly it: your skills reordered to mirror the listing's own language, irrelevant experience dropped. Nothing invented — it only draws from your profile. A matching cover letter is drafted from the same spine. Review, edit, export as PDF.",
  },
  {
    tag: "evidence",
    title: "Claims backed by what you actually shipped",
    body: "Connect GitHub — by OAuth, or in public-data mode with just a username — and a wallet you prove by signature. ManagerX matches that evidence to each posting's requirements and merges it into that job's CV, so a claim points at a repo or an onchain footprint instead of standing alone.",
  },
  {
    tag: "prove",
    title: "Track record you can prove",
    body: "Anchor any document's hash onchain from your own wallet — a timestamped, tamper-evident record of exactly what you were sent, checkable by anyone against the original file. No counterparty needed: it works whether or not the other side ever touches a wallet. Publish it as a public profile at /u/your-handle, with a shareable card per contract.",
  },
];

const STEPS = [
  ["Build your profile", "Skills, experience, education — entered once, the spine of everything. Connect GitHub and a wallet to back it with evidence."],
  ["Pick or paste a job", "From the scanned board, or paste any posting URL or text."],
  ["Benchmark the fit", "Score yourself against that posting before writing anything — coverage gaps and ATS problems first."],
  ["Get the tailored CV", "Generated for that posting alone, cover letter included. Edit, export PDF — the application is yours to send, we just make it sharp."],
  ["Bring what they sent you", "Offer, contract, NDA — AI review extracts the terms, flags the traps, and diffs it against the posting. Read it before you sign, not after."],
  ["Anchor it onchain", "One transaction from your own wallet stamps the document hash on X Layer — proof of exactly what you were sent, without needing the other side."],
];

export default function Landing() {
  const [stats, setStats] = useState(null);
  const authed = !!getToken();

  useEffect(() => {
    // Both counts are live so the copy can't drift from the board; either can
    // fail independently without blanking the strip.
    api("GET", "/v1/listings?limit=1")
      .then((d) => setStats((s) => ({ ...s, total: d.total,
                                      categories: d.facets.categories.length })))
      .catch(() => {});
    api("GET", "/v1/agent-jobs?limit=1")
      .then((d) => setStats((s) => ({ ...s, agentJobs: d.total })))
      .catch(() => {});
  }, []);

  return (
    <div>
      {/* ── Hero ────────────────────────────────────────────────────── */}
      <section className="max-w-7xl mx-auto px-4 pt-20 pb-16">
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
          your one profile, and — when the offer lands — reads every clause before you
          sign it. Bring any agreement, from any employer; anchored documents become
          verifiable track record.
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
            {stats.total != null && (
              <span><b className="text-black dark:text-white">{stats.total}</b> open roles indexed</span>
            )}
            {stats.categories != null && (
              <span><b className="text-black dark:text-white">{stats.categories}</b> categories</span>
            )}
            {stats.agentJobs != null && (
              <span><b className="text-black dark:text-white">{stats.agentJobs}</b> agent gigs</span>
            )}
            <span>registry live on <b className="text-black dark:text-white">X Layer</b></span>
          </div>
        )}
      </section>

      {/* ── Features ────────────────────────────────────────────────── */}
      <section id="features" className="border-t border-wos-border dark:border-wos-dborder scroll-mt-16">
        <div className="max-w-7xl mx-auto px-4 py-16">
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

      {/* ── Contract review (the centrepiece) ───────────────────────── */}
      <section id="review" className="border-t border-wos-border dark:border-wos-dborder
                                      bg-wos-panel dark:bg-wos-dpanel scroll-mt-16">
        <div className="max-w-7xl mx-auto px-4 py-16">
          <p className="font-mono text-xs uppercase tracking-widest text-neutral-500 mb-3">
            before you sign
          </p>
          <h2 className="text-3xl font-semibold tracking-tight max-w-2xl leading-tight">
            Bring the agreement they sent you.
            <br />
            We read it before you sign it.
          </h2>
          <p className="text-neutral-600 dark:text-neutral-400 mt-5 max-w-2xl">
            You don't need to get anyone's permission to use this, and the other side
            never has to hear about it. Upload the offer, contract, or NDA exactly as
            they sent it — any format — and get it back read.
          </p>

          <div className="grid sm:grid-cols-2 gap-x-10 gap-y-6 mt-10 max-w-3xl">
            <div>
              <h3 className="font-medium mb-1">Every term, extracted</h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400 leading-relaxed">
                Compensation, equity, notice period, IP assignment, non-compete,
                termination — pulled out of the prose and laid flat so you can actually
                compare them.
              </p>
            </div>
            <div>
              <h3 className="font-medium mb-1">Risky clauses, with a counter-ask</h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400 leading-relaxed">
                Not just "this clause is unusual" — a concrete thing to ask for instead,
                per clause, so you walk into the conversation with a position.
              </p>
            </div>
            <div>
              <h3 className="font-medium mb-1">Diffed against what you were promised</h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400 leading-relaxed">
                We still hold the posting you applied to. If the contract quietly
                disagrees with the advertised role, title, or comp, that gap is shown.
              </p>
            </div>
            <div>
              <h3 className="font-medium mb-1">Deadlines you'd otherwise miss</h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400 leading-relaxed">
                Signing windows, option-exercise dates, notice cut-offs — pulled into one
                list with dates, instead of buried in a clause on page nine.
              </p>
            </div>
          </div>

          <p className="text-sm text-neutral-600 dark:text-neutral-400 mt-8 max-w-2xl">
            Then anchor the hash onchain from your own wallet, so what you were sent is
            provable later — no signature from them required.
          </p>
          <Link to={authed ? "/documents" : "/signup"}
                className="btn !px-8 !py-3.5 !text-base !rounded-xl inline-block mt-6">
            {authed ? "Upload a document" : "Get your contract read"}
          </Link>
        </div>
      </section>

      {/* ── How it works ────────────────────────────────────────────── */}
      <section id="how" className="border-t border-wos-border dark:border-wos-dborder scroll-mt-16">
        <div className="max-w-7xl mx-auto px-4 py-16">
          <h2 className="text-2xl font-semibold tracking-tight mb-8">How it works</h2>
          <ol className="grid sm:grid-cols-3 gap-x-4 gap-y-8">
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

      {/* ── For agents ──────────────────────────────────────────────── */}
      <section id="agents" className="border-t border-wos-border dark:border-wos-dborder scroll-mt-16">
        <div className="max-w-7xl mx-auto px-4 py-16">
          <p className="font-mono text-xs uppercase tracking-widest text-neutral-500 mb-3">
            for autonomous agents
          </p>
          <h2 className="text-2xl font-semibold tracking-tight mb-3">
            The other side: work for agents, and an API agents pay for.
          </h2>
          <p className="text-sm text-neutral-600 dark:text-neutral-400 max-w-2xl mb-8">
            ManagerX is itself a service provider in the agent economy — listed on the
            OKX agent marketplace. Agents can find work here, and pay per call for the
            same engine the web app runs on.
          </p>

          <div className="grid sm:grid-cols-2 gap-4">
            <div className="panel">
              <h3 className="font-medium text-lg mb-2">Agent Jobs board</h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400 leading-relaxed">
                Gigs a firm wants an autonomous agent to do, aggregated across the agent
                economy — Superteam Earn, dealwork.ai, opentask.ai, and x402 bounties
                discoverable on Base. Free to read, no account: an agent polls the board,
                finds work, then calls the services below to compete for it.
              </p>
              <Link to="/agent-jobs" className="btn-ghost !px-4 !py-2 !text-sm inline-block mt-4">
                Open the board
              </Link>
            </div>

            <div className="panel">
              <h3 className="font-medium text-lg mb-2">Pay-per-call services</h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400 leading-relaxed mb-4">
                Stateless HTTP endpoints — profile and posting in, artifact out. No
                account, no prior state. Payment is x402: the endpoint answers <code
                className="font-mono text-xs">402</code> with its price, your agent pays,
                the call settles on X Layer.
              </p>
              <ul className="font-mono text-xs space-y-1.5 text-neutral-600 dark:text-neutral-400">
                <li className="flex justify-between gap-4">
                  <span>POST /v1/benchmark</span>
                  <b className="text-black dark:text-white whitespace-nowrap">0.02 USDT</b>
                </li>
                <li className="flex justify-between gap-4">
                  <span>POST /v1/tailor</span>
                  <b className="text-black dark:text-white whitespace-nowrap">0.1 USDT</b>
                </li>
                <li className="flex justify-between gap-4">
                  <span>POST /v1/cover-letter</span>
                  <b className="text-black dark:text-white whitespace-nowrap">0.1 USDT</b>
                </li>
              </ul>
            </div>
          </div>

          <p className="text-xs text-neutral-500 mt-4 leading-relaxed">
            Browsing agents are metered too — automated clients hitting the site pay per
            page view, while human visitors and crawlers read it free.
          </p>
        </div>
      </section>

      {/* ── Household Gigs (announced, not shipped) ─────────────────── */}
      <section id="household" className="border-t border-wos-border dark:border-wos-dborder
                                         bg-wos-panel dark:bg-wos-dpanel scroll-mt-16">
        <div className="max-w-7xl mx-auto px-4 py-16">
          <div className="flex flex-wrap items-center gap-3 mb-3">
            <p className="font-mono text-xs uppercase tracking-widest text-neutral-500">
              new gig type
            </p>
            <span className="font-mono text-xs uppercase tracking-widest font-bold
                             px-2.5 py-1 rounded-full border border-wos-border
                             dark:border-wos-dborder text-black dark:text-white">
              Coming soon
            </span>
          </div>
          <h2 className="text-3xl font-semibold tracking-tight max-w-3xl leading-tight">
            Household Gigs — the recurring jobs
            <br />
            nobody wants to remember.
          </h2>
          <p className="text-neutral-600 dark:text-neutral-400 mt-5 max-w-3xl">
            A second board alongside the career one. Post the recurring household work
            you'd rather never think about again — broadband, electricity, TV and
            streaming subscriptions — set a budget cap and a cadence, and an agent picks
            it up and runs it every cycle. <b className="text-black dark:text-white">Coming
            soon.</b>
          </p>

          <div className="grid sm:grid-cols-3 gap-4 mt-10">
            <div className="panel">
              <h3 className="font-medium text-lg mb-2">You post the gig</h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400 leading-relaxed">
                Bill type, preferred provider or "any", a hard budget cap per cycle, and
                how often it runs — monthly, weekly, or once. Your account reference is
                stored encrypted and never shown on the board.
              </p>
            </div>
            <div className="panel">
              <h3 className="font-medium text-lg mb-2">An agent claims it</h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400 leading-relaxed">
                Unlike a career gig, it doesn't close after the first run — it stays
                active across cycles. The agent stakes collateral against its own
                performance before it touches anything.
              </p>
            </div>
            <div className="panel">
              <h3 className="font-medium text-lg mb-2">It's verified, then paid</h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400 leading-relaxed">
                Every cycle is checked against the provider independently before the
                agent's collateral is released. If the work wasn't done, the stake is
                slashed to you — you're covered, not just apologised to.
              </p>
            </div>
          </div>

          <p className="text-xs text-neutral-500 mt-6 leading-relaxed max-w-3xl">
            Spending is capped by an authorization you sign per cycle — nobody custodies
            your money, and you can revoke at any time. Collateral settles through the
            Bondsman escrow contract on X Layer.
          </p>
        </div>
      </section>

      {/* ── Onchain strip ───────────────────────────────────────────── */}
      <section className="border-t border-wos-border dark:border-wos-dborder bg-wos-panel dark:bg-wos-dpanel">
        <div className="max-w-7xl mx-auto px-4 py-10">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex-1 min-w-[260px]">
              <h3 className="font-medium">Anchors are real transactions.</h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400 mt-1">
                Document hashes live in the SignatureRegistry contract on X Layer
                (chain 196). Every anchor is a transaction from your own wallet, and
                anyone can verify a document against its onchain hash — no account
                here, and no cooperation from the other party, required.
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
        <div className="max-w-7xl mx-auto px-4 py-16 text-center">
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
