import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Link } from "../lib/router";
import { Money, SettlementNote, StatusPill, label } from "./HouseholdGigs.jsx";

export default function HouseholdGigDetail({ gigId }) {
  const [gig, setGig] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [details, setDetails] = useState("");

  async function load() {
    try {
      const next = await api("GET", `/v1/household-gigs/${gigId}/dashboard`);
      setGig(next);
      setDetails(next.service_details || "");
      setErr("");
    } catch (error) { setErr(error.message); }
  }
  useEffect(() => { load(); }, [gigId]);

  async function act(fn) {
    setBusy(true);
    try { await fn(); await load(); }
    catch (error) { setErr(error.message); }
    setBusy(false);
  }

  const ack = (cycleId) =>
    act(() => api("POST", `/v1/household-gigs/${gigId}/cycles/${cycleId}/ack`));
  const setStatus = (status) =>
    act(() => api("PATCH", `/v1/household-gigs/${gigId}`, { status }));
  const cancel = () => {
    if (!window.confirm("Cancel this gig? No further cycles will open. Nothing "
                        + "financial happens — ManagerX never held any funds for it."))
      return;
    act(() => api("POST", `/v1/household-gigs/${gigId}/cancel`));
  };

  if (err && !gig) return <p className="text-sm text-red-600">{err}</p>;
  if (!gig) return <p className="text-sm text-neutral-500">Loading…</p>;

  const live = ["claimed", "active", "paused"].includes(gig.status);

  return (
    <div>
      <Link to="/household-gigs" className="text-xs text-neutral-500 hover:text-black dark:hover:text-white">
        ← Household Gigs
      </Link>

      <div className="flex items-start justify-between gap-4 flex-wrap mt-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{gig.title}</h1>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {gig.bill_types.map((bt) => <span key={bt} className="chip">{label(bt)}</span>)}
            <span className="chip">{label(gig.cadence)}</span>
          </div>
        </div>
        <StatusPill status={gig.status} />
      </div>

      {err && <p className="text-sm text-red-600 mt-4">{err}</p>}

      <div className="grid sm:grid-cols-2 gap-4 mt-6">
        <div className="panel">
          <h2 className="font-medium mb-3">Terms</h2>
          <dl className="text-sm space-y-2">
            <div className="flex justify-between gap-4">
              <dt className="text-neutral-500">Budget</dt>
              <dd><Money gig={gig} /></dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-neutral-500">Next cycle</dt>
              <dd>{gig.next_cycle_date || "—"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-neutral-500">Posted</dt>
              <dd>{(gig.created_at || "").slice(0, 10)}</dd>
            </div>
          </dl>
          {gig.status === "open" && (
            <p className="text-xs text-neutral-500 mt-3">
              Editable until an agent claims it. After that the terms are fixed —
              cancel and repost to change them.
            </p>
          )}
        </div>

        <div className="panel">
          <h2 className="font-medium mb-3">The agent</h2>
          {gig.agent ? (
            <>
              <dl className="text-sm space-y-2">
                <div className="flex justify-between gap-4">
                  <dt className="text-neutral-500">Contact</dt>
                  <dd className="break-all">{gig.agent.email}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-neutral-500">Claimed</dt>
                  <dd>{(gig.claimed_at || "").slice(0, 10)}</dd>
                </div>
              </dl>
              {gig.pay_the_agent && (
                <div className="card-inner mt-3">
                  <p className="text-xs uppercase tracking-wide text-neutral-500 mb-1">
                    Pay this agent directly
                  </p>
                  <code className="font-mono text-xs break-all">
                    {gig.pay_the_agent.address}
                  </code>
                  <p className="text-xs text-neutral-500 mt-2">
                    {gig.pay_the_agent.instruction}
                  </p>
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-neutral-500">
              Not claimed yet — it's on the open board.
            </p>
          )}
        </div>
      </div>

      <div className="panel mt-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h2 className="font-medium">What the agent works with</h2>
            <p className="text-xs text-neutral-500 mt-1">
              Meter number, the phone your token goes to, account references. Private
              to you and the agent who claimed this gig — never on the public board.
            </p>
          </div>
          {!editing && (
            <button className="btn-ghost !py-1 !text-xs" onClick={() => setEditing(true)}>
              {gig.service_details ? "Edit" : "Add details"}
            </button>
          )}
        </div>

        {editing ? (
          <div className="mt-3">
            <textarea className="input min-h-[120px] resize-y" value={details}
                      placeholder={"Meter number: 04123456789\n"
                                   + "Send token to: 0803 000 0000\n"
                                   + "DisCo: Ikeja Electric"}
                      onChange={(e) => setDetails(e.target.value)} />
            <div className="flex gap-2 mt-2">
              <button className="btn !py-1.5" disabled={busy}
                      onClick={() => act(async () => {
                        await api("PATCH", `/v1/household-gigs/${gigId}`,
                                  { service_details: details });
                        setEditing(false);
                      })}>
                Save
              </button>
              <button className="btn-ghost !py-1.5" disabled={busy}
                      onClick={() => { setDetails(gig.service_details || ""); setEditing(false); }}>
                Cancel
              </button>
            </div>
            <p className="text-xs text-neutral-500 mt-2">
              Editable at any time, including after a claim — a mistyped meter number
              has to be fixable, or every cycle after it fails.
            </p>
          </div>
        ) : gig.service_details ? (
          <pre className="card-inner mt-3 text-sm whitespace-pre-wrap font-sans">
            {gig.service_details}
          </pre>
        ) : (
          <p className="text-sm text-neutral-500 mt-3">
            Nothing added yet — without this an agent can't act on the first cycle.
          </p>
        )}
      </div>

      <div className="flex items-center justify-between gap-4 flex-wrap mt-8">
        <h2 className="font-medium">Cycle history</h2>
        {live && (
          <div className="flex gap-2">
            {gig.status !== "paused" ? (
              <button className="btn-ghost !py-1.5" disabled={busy}
                      onClick={() => setStatus("paused")}>Pause</button>
            ) : (
              <button className="btn-ghost !py-1.5" disabled={busy}
                      onClick={() => setStatus("active")}>Resume</button>
            )}
            <button className="btn-ghost !py-1.5" disabled={busy} onClick={cancel}>
              Cancel gig
            </button>
          </div>
        )}
      </div>

      <div className="space-y-2 mt-4">
        {gig.cycles.map((c) => (
          <div key={c.cycle_id} className="card-inner">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <span className="text-sm">Cycle #{c.cycle_index} · {c.cycle_date}</span>
              <div className="flex items-center gap-2">
                <StatusPill status={c.status} />
                {c.household_ack ? (
                  <span className="text-xs text-neutral-500">reviewed</span>
                ) : (
                  <button className="btn-ghost !py-1 !text-xs" disabled={busy}
                          onClick={() => ack(c.cycle_id)}>
                    Mark reviewed
                  </button>
                )}
              </div>
            </div>
            {c.agent_note && (
              <p className="text-xs text-neutral-500 mt-1">
                Agent's note: “{c.agent_note}”
              </p>
            )}
            {c.status !== "pending" && (
              <p className="text-[11px] text-neutral-400 mt-1">
                Self-reported by the agent — ManagerX does not verify this. Check with
                your provider before treating it as settled.
              </p>
            )}
          </div>
        ))}
        {gig.cycles.length === 0 && (
          <p className="text-sm text-neutral-500">
            No cycles yet — the first opens on {gig.next_cycle_date || "its start date"},
            once an agent has claimed the gig.
          </p>
        )}
      </div>

      <SettlementNote className="mt-8 border-t border-wos-border dark:border-wos-dborder pt-4" />
    </div>
  );
}
