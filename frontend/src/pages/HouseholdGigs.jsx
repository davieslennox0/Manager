import { useEffect, useState } from "react";
import { api, getToken } from "../lib/api";
import { Link, navigate } from "../lib/router";

const BILL_TYPES = ["electricity", "gas", "water", "broadband", "tv_subscription",
                    "streaming", "mobile", "waste", "other"];
const CADENCES = ["monthly", "weekly", "one_time"];

const label = (s) => (s || "").replace(/_/g, " ");

// The one thing every view of this feature has to say out loud: ManagerX lists
// the work and tracks what the agent claims — it is not in the money path.
function SettlementNote({ className = "" }) {
  return (
    <p className={`text-xs text-neutral-500 leading-relaxed ${className}`}>
      Budgets and payment addresses here are <b>listed information only</b>. The
      household pays the agent directly — ManagerX never holds, moves, or verifies
      these payments, and cycle statuses are the agent's own report, not a check.
    </p>
  );
}

function Money({ gig }) {
  if (!gig.budget_amount) return <span className="text-neutral-500">Budget not stated</span>;
  return (
    <span className="font-semibold text-neutral-900 dark:text-neutral-100">
      {gig.budget_amount} {gig.budget_currency}
      <span className="font-normal text-neutral-500"> / {label(gig.cadence)}</span>
    </span>
  );
}

function StatusPill({ status }) {
  const tone = {
    open: "bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900",
    claimed: "bg-indigo-50 dark:bg-indigo-950/50 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-900",
    active: "bg-indigo-50 dark:bg-indigo-950/50 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-900",
    paused: "bg-amber-50 dark:bg-amber-950/50 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-900",
    cancelled: "bg-neutral-100 dark:bg-neutral-900 text-neutral-500 border-neutral-200 dark:border-neutral-800",
    done: "bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900",
    not_done: "bg-red-50 dark:bg-red-950/50 text-red-700 dark:text-red-300 border-red-200 dark:border-red-900",
    pending: "bg-amber-50 dark:bg-amber-950/50 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-900",
    skipped: "bg-neutral-100 dark:bg-neutral-900 text-neutral-500 border-neutral-200 dark:border-neutral-800",
  }[status] || "bg-neutral-100 dark:bg-neutral-900 text-neutral-500 border-neutral-200";
  return (
    <span className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border
                      whitespace-nowrap ${tone}`}>{label(status)}</span>
  );
}

// ── Browse: the public board ────────────────────────────────────────────────
function Board({ authed, onClaimed }) {
  const [data, setData] = useState({ total: 0, household_gigs: [], note: "",
                                     facets: { bill_types: [], cadences: [] } });
  const [billType, setBillType] = useState("");
  const [cadence, setCadence] = useState("");
  const [claiming, setClaiming] = useState(null);
  const [address, setAddress] = useState("");
  const [err, setErr] = useState("");

  async function load() {
    const params = new URLSearchParams();
    if (billType) params.set("bill_type", billType);
    if (cadence) params.set("cadence", cadence);
    try {
      setData(await api("GET", `/v1/household-gigs?${params}`));
      setErr("");
    } catch (error) { setErr(error.message); }
  }
  useEffect(() => { load(); }, [billType, cadence]);

  async function claim(gigId) {
    if (!address.trim()) return setErr("Enter the address the household should pay you at.");
    try {
      await api("POST", `/v1/household-gigs/${gigId}/claim`,
                { agent_payment_address: address.trim() });
      setClaiming(null);
      setAddress("");
      setErr("");
      await load();
      onClaimed?.();
    } catch (error) { setErr(error.message); }
  }

  return (
    <div>
      <div className="flex gap-2 flex-wrap items-center">
        <select value={billType} onChange={(e) => setBillType(e.target.value)}
                className="input !py-2 !w-auto">
          <option value="">All bill types</option>
          {data.facets.bill_types.map((b) => (
            <option key={b.name} value={b.name}>{label(b.name)} ({b.count})</option>
          ))}
        </select>
        <select value={cadence} onChange={(e) => setCadence(e.target.value)}
                className="input !py-2 !w-auto">
          <option value="">Any cadence</option>
          {data.facets.cadences.map((c) => (
            <option key={c.name} value={c.name}>{label(c.name)} ({c.count})</option>
          ))}
        </select>
        <span className="text-xs text-neutral-500">{data.total} open</span>
      </div>

      {err && <p className="text-sm text-red-600 mt-4">{err}</p>}

      <div className="grid sm:grid-cols-2 gap-3 mt-6">
        {data.household_gigs.map((gig) => (
          <div key={gig.gig_id}
               className="p-4 rounded-xl border border-wos-border dark:border-wos-dborder
                          bg-white dark:bg-wos-dcard">
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-medium leading-snug">{gig.title}</h3>
              <StatusPill status={gig.status} />
            </div>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {gig.bill_types.map((bt) => (
                <span key={bt} className="chip">{label(bt)}</span>
              ))}
            </div>
            <div className="mt-3 text-sm"><Money gig={gig} /></div>

            {claiming === gig.gig_id ? (
              <div className="mt-3 flex gap-2 flex-wrap">
                <input value={address} onChange={(e) => setAddress(e.target.value)}
                       placeholder="Where should they pay you? (wallet or account ref)"
                       className="input !py-2 flex-1 !w-auto min-w-[220px]" />
                <button className="btn" onClick={() => claim(gig.gig_id)}>Confirm</button>
                <button className="btn-ghost" onClick={() => setClaiming(null)}>Cancel</button>
              </div>
            ) : (
              <button className="btn-ghost !py-1.5 mt-3"
                      onClick={() => (authed ? setClaiming(gig.gig_id) : navigate("/signup"))}>
                {authed ? "Claim this gig" : "Sign in to claim"}
              </button>
            )}
          </div>
        ))}
      </div>

      {data.household_gigs.length === 0 && !err && (
        <p className="text-sm text-neutral-500 mt-8">
          No open household gigs right now.
        </p>
      )}
      {data.note && (
        <p className="text-xs text-neutral-400 dark:text-neutral-500 mt-8 border-t
                      border-wos-border dark:border-wos-dborder pt-4">{data.note}</p>
      )}
    </div>
  );
}

// ── Post a gig ──────────────────────────────────────────────────────────────
function PostGig({ onPosted }) {
  const [form, setForm] = useState({ title: "", cadence: "monthly",
                                     budget_amount: "", budget_currency: "NGN" });
  const [types, setTypes] = useState([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  function toggle(bt) {
    setTypes((t) => (t.includes(bt) ? t.filter((x) => x !== bt) : [...t, bt]));
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("POST", "/v1/household-gigs", { ...form, bill_types: types });
      setForm({ title: "", cadence: "monthly", budget_amount: "", budget_currency: "NGN" });
      setTypes([]);
      setErr("");
      onPosted?.();
    } catch (error) { setErr(error.message); }
    setBusy(false);
  }

  return (
    <form onSubmit={submit} className="panel">
      <h3 className="font-medium mb-4">Post a household gig</h3>
      <div className="grid sm:grid-cols-2 gap-4">
        <div className="sm:col-span-2">
          <label className="label">Title</label>
          <input className="input" value={form.title} placeholder="Flat 4 — utilities bundle"
                 onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </div>
        <div className="sm:col-span-2">
          <label className="label">Bill types</label>
          <div className="flex flex-wrap gap-2">
            {BILL_TYPES.map((bt) => (
              <button type="button" key={bt} onClick={() => toggle(bt)}
                      className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                        types.includes(bt)
                          ? "bg-wos-accent text-white border-wos-accent dark:bg-white dark:text-black dark:border-white"
                          : "border-wos-border dark:border-wos-dborder hover:border-wos-accent dark:hover:border-white"}`}>
                {label(bt)}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="label">Cadence</label>
          <select className="input" value={form.cadence}
                  onChange={(e) => setForm({ ...form, cadence: e.target.value })}>
            {CADENCES.map((c) => <option key={c} value={c}>{label(c)}</option>)}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="label">Budget / cycle</label>
            <input className="input" value={form.budget_amount} placeholder="45000"
                   onChange={(e) => setForm({ ...form, budget_amount: e.target.value })} />
          </div>
          <div>
            <label className="label">Currency</label>
            <input className="input" value={form.budget_currency} placeholder="NGN"
                   onChange={(e) => setForm({ ...form, budget_currency: e.target.value })} />
          </div>
        </div>
      </div>
      {err && <p className="text-sm text-red-600 mt-3">{err}</p>}
      <div className="flex items-center gap-4 mt-4 flex-wrap">
        <button className="btn" disabled={busy}>{busy ? "Posting…" : "Post gig"}</button>
        <SettlementNote className="flex-1 min-w-[260px] !mt-0" />
      </div>
    </form>
  );
}

// ── Household's own posted gigs ─────────────────────────────────────────────
function MyPosted({ refreshKey, onPosted }) {
  const [gigs, setGigs] = useState([]);
  const [err, setErr] = useState("");

  async function load() {
    try {
      setGigs((await api("GET", "/v1/household-gigs/mine")).household_gigs);
      setErr("");
    } catch (error) { setErr(error.message); }
  }
  useEffect(() => { load(); }, [refreshKey]);

  return (
    <div>
      <PostGig onPosted={() => { load(); onPosted?.(); }} />
      {err && <p className="text-sm text-red-600 mt-4">{err}</p>}
      <div className="grid sm:grid-cols-2 gap-3 mt-6">
        {gigs.map((gig) => (
          <Link key={gig.gig_id} to={`/household-gigs/${gig.gig_id}`}
                className="block p-4 rounded-xl border border-wos-border dark:border-wos-dborder
                           bg-white dark:bg-wos-dcard hover:border-indigo-300
                           dark:hover:border-indigo-800 transition">
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-medium leading-snug">{gig.title}</h3>
              <StatusPill status={gig.status} />
            </div>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {gig.bill_types.map((bt) => <span key={bt} className="chip">{label(bt)}</span>)}
            </div>
            <div className="mt-3 text-sm"><Money gig={gig} /></div>
            <div className="mt-2 text-xs text-neutral-500">
              {gig.unacked_cycles > 0
                ? `${gig.unacked_cycles} cycle(s) need your review`
                : "Nothing waiting on you"}
              {gig.next_cycle_date && ` · next cycle ${gig.next_cycle_date}`}
            </div>
          </Link>
        ))}
      </div>
      {gigs.length === 0 && !err && (
        <p className="text-sm text-neutral-500 mt-6">
          You haven't posted a household gig yet.
        </p>
      )}
    </div>
  );
}

// ── Agent's claimed gigs + the cycles waiting on them ───────────────────────
function MyClaimed({ refreshKey }) {
  const [gigs, setGigs] = useState([]);
  const [notes, setNotes] = useState({});
  const [err, setErr] = useState("");

  async function load() {
    try {
      setGigs((await api("GET", "/v1/household-gigs/claimed")).household_gigs);
      setErr("");
    } catch (error) { setErr(error.message); }
  }
  useEffect(() => { load(); }, [refreshKey]);

  async function report(gigId, cycleId, status) {
    try {
      await api("POST", `/v1/household-gigs/${gigId}/cycles/${cycleId}/status`,
                { status, agent_note: notes[cycleId] || "" });
      setNotes((n) => ({ ...n, [cycleId]: "" }));
      await load();
    } catch (error) { setErr(error.message); }
  }

  return (
    <div>
      {err && <p className="text-sm text-red-600 mb-4">{err}</p>}
      <div className="space-y-4">
        {gigs.map((gig) => (
          <div key={gig.gig_id} className="panel">
            <div className="flex items-start justify-between gap-2 flex-wrap">
              <div>
                <h3 className="font-medium">{gig.title}</h3>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {gig.bill_types.map((bt) => <span key={bt} className="chip">{label(bt)}</span>)}
                </div>
              </div>
              <div className="text-right text-sm">
                <Money gig={gig} />
                <div className="text-xs text-neutral-500 mt-1">
                  paid to you at <code className="font-mono">{gig.agent_payment_address}</code>
                </div>
              </div>
            </div>

            <div className="mt-4 space-y-2">
              {gig.cycles.map((c) => (
                <div key={c.cycle_id} className="card-inner">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <span className="text-sm">
                      Cycle #{c.cycle_index} · {c.cycle_date}
                    </span>
                    <StatusPill status={c.status} />
                  </div>
                  {c.status === "pending" ? (
                    <div className="flex gap-2 mt-2 flex-wrap">
                      <input className="input !py-1.5 flex-1 !w-auto min-w-[200px]"
                             placeholder="Note for the household (optional)"
                             value={notes[c.cycle_id] || ""}
                             onChange={(e) => setNotes({ ...notes, [c.cycle_id]: e.target.value })} />
                      <button className="btn !py-1.5"
                              onClick={() => report(gig.gig_id, c.cycle_id, "done")}>
                        Mark done
                      </button>
                      <button className="btn-ghost !py-1.5"
                              onClick={() => report(gig.gig_id, c.cycle_id, "not_done")}>
                        Not done
                      </button>
                    </div>
                  ) : (
                    c.agent_note && (
                      <p className="text-xs text-neutral-500 mt-1">“{c.agent_note}”</p>
                    )
                  )}
                </div>
              ))}
              {gig.cycles.length === 0 && (
                <p className="text-xs text-neutral-500">
                  No cycles yet — the first opens on {gig.next_cycle_date || "its start date"}.
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
      {gigs.length === 0 && !err && (
        <p className="text-sm text-neutral-500">
          You haven't claimed a household gig yet — take one from the board.
        </p>
      )}
      <SettlementNote className="mt-6" />
    </div>
  );
}

// ── Page ────────────────────────────────────────────────────────────────────
export default function HouseholdGigs() {
  const authed = !!getToken();
  const [tab, setTab] = useState("board");
  const [refreshKey, setRefreshKey] = useState(0);
  const bump = () => setRefreshKey((k) => k + 1);

  const TABS = [["board", "Browse gigs"], ["posted", "My posted gigs"],
                ["claimed", "My claimed gigs"]];

  return (
    <div>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Household Gigs</h1>
          <p className="text-sm text-neutral-600 dark:text-neutral-400 mt-1 max-w-2xl">
            Recurring household work — utilities, broadband, subscriptions — posted by
            a household and handled each cycle by an agent. ManagerX is the meeting
            layer: it lists the gig, records who claimed it, and tracks the status the
            agent reports. The two of you settle directly.
          </p>
        </div>
        <div className="flex gap-2 text-sm">
          <Link to="/board" className="btn-ghost !py-1.5">Career board</Link>
          <Link to="/agent-jobs" className="btn-ghost !py-1.5">Agent Jobs</Link>
        </div>
      </div>

      <div className="flex gap-1 mt-6 border-b border-wos-border dark:border-wos-dborder">
        {TABS.map(([key, name]) => (
          <button key={key} onClick={() => setTab(key)}
                  className={`px-4 py-2 text-sm border-b-2 -mb-px transition-colors ${
                    tab === key
                      ? "border-wos-accent text-black dark:border-white dark:text-white font-medium"
                      : "border-transparent text-neutral-500 hover:text-black dark:hover:text-white"}`}>
            {name}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {tab === "board" && <Board authed={authed} onClaimed={bump} />}
        {tab !== "board" && !authed && (
          <p className="text-sm text-neutral-500">
            <Link to="/signup" className="underline">Sign in</Link> to post a gig or
            see the ones you've claimed.
          </p>
        )}
        {tab === "posted" && authed && <MyPosted refreshKey={refreshKey} onPosted={bump} />}
        {tab === "claimed" && authed && <MyClaimed refreshKey={refreshKey} />}
      </div>
    </div>
  );
}

export { SettlementNote, StatusPill, Money, label };
