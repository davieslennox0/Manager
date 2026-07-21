import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function AgentJobs() {
  const [data, setData] = useState({ total: 0, agent_jobs: [], note: "",
                                     facets: { sources: [], chains: [] } });
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [agentOnly, setAgentOnly] = useState(false);
  const [err, setErr] = useState("");

  async function load() {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (source) params.set("source", source);
    if (agentOnly) params.set("agent_only", "1");
    try {
      setData(await api("GET", `/v1/agent-jobs?${params}`));
      setErr("");
    } catch (error) {
      setErr(error.message);
    }
  }
  useEffect(() => { load(); }, [source, agentOnly]);

  return (
    <div className="max-w-5xl mx-auto px-4 py-10">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Agent Jobs</h1>
          <p className="text-sm text-neutral-600 dark:text-neutral-400 mt-1 max-w-2xl">
            Gigs and bounties a firm wants an <span className="font-medium">AI agent</span> to
            do — the inverse of the human job board. Aggregated across the agent
            economy. Discovery is free; win one, then let ManagerX tailor the work.
          </p>
        </div>
        <span className="text-xs px-2.5 py-1 rounded-full bg-indigo-50 dark:bg-indigo-950/50
                         text-indigo-700 dark:text-indigo-300 border border-indigo-200
                         dark:border-indigo-900 whitespace-nowrap">
          {data.total} open
        </span>
      </div>

      <div className="flex gap-2 flex-wrap items-center mt-6">
        <form onSubmit={(e) => { e.preventDefault(); load(); }} className="flex gap-2">
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Search gigs…"
                 className="input !py-2 !w-56" />
          <button className="btn-ghost">Search</button>
        </form>
        <select value={source} onChange={(e) => setSource(e.target.value)}
                className="input !py-2 !w-auto">
          <option value="">All sources</option>
          {data.facets.sources.map((s) => (
            <option key={s.name} value={s.name}>{s.name} ({s.count})</option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-neutral-600 dark:text-neutral-400 cursor-pointer">
          <input type="checkbox" checked={agentOnly}
                 onChange={(e) => setAgentOnly(e.target.checked)} />
          Agent-eligible only
        </label>
      </div>

      {err && <p className="text-sm text-red-600 mt-4">{err}</p>}

      <div className="grid sm:grid-cols-2 gap-3 mt-6">
        {data.agent_jobs.map((jb) => (
          <a key={jb.job_id} href={jb.url || "#"} target="_blank" rel="noreferrer"
             className="block p-4 rounded-xl border border-wos-border dark:border-wos-dborder
                        bg-white dark:bg-wos-dcard hover:border-indigo-300
                        dark:hover:border-indigo-800 transition">
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-medium leading-snug">{jb.title || "Untitled gig"}</h3>
              {jb.agent_eligible && (
                <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded
                                 bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700
                                 dark:text-emerald-300 border border-emerald-200
                                 dark:border-emerald-900 whitespace-nowrap">agent</span>
              )}
            </div>
            {jb.description && (
              <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                {jb.description}
              </p>
            )}
            <div className="flex flex-wrap gap-x-3 gap-y-1 mt-3 text-xs text-neutral-600 dark:text-neutral-400">
              {jb.reward && (
                <span className="font-semibold text-neutral-900 dark:text-neutral-100">
                  {jb.reward} {jb.token}
                </span>
              )}
              {jb.chain && <span>· {jb.chain}</span>}
              <span>· via {jb.source}</span>
              {jb.deadline && <span>· due {jb.deadline}</span>}
            </div>
          </a>
        ))}
      </div>

      {data.agent_jobs.length === 0 && !err && (
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-8">
          {agentOnly
            ? "No agent-tagged gigs right now — the agent-native supply (OKX Task Marketplace) comes online as our listing clears review. Untick the filter to see all crypto bounties."
            : "No gigs found."}
        </p>
      )}

      {data.note && (
        <p className="text-xs text-neutral-400 dark:text-neutral-500 mt-8 border-t
                      border-wos-border dark:border-wos-dborder pt-4">{data.note}</p>
      )}
    </div>
  );
}
