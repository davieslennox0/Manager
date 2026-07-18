import { useEffect, useState } from "react";
import { api, getToken } from "../lib/api";
import { navigate } from "../lib/router";

export default function Board() {
  const [data, setData] = useState({ total: 0, listings: [], facets: { ecosystems: [] } });
  const [q, setQ] = useState("");
  const [eco, setEco] = useState("");
  const [remote, setRemote] = useState("");
  const [err, setErr] = useState("");
  const [busyId, setBusyId] = useState("");
  const [subEmail, setSubEmail] = useState("");
  const [subKeywords, setSubKeywords] = useState("");
  const [subMsg, setSubMsg] = useState("");

  async function load() {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (eco) params.set("ecosystem", eco);
    if (remote) params.set("remote", remote);
    try {
      setData(await api("GET", `/v1/listings?${params}`));
    } catch (error) {
      setErr(error.message);
    }
  }
  useEffect(() => { load(); }, [eco, remote]);

  async function tailor(listing) {
    if (!getToken()) {
      navigate("/login?next=/");
      return;
    }
    setBusyId(listing.listing_id);
    try {
      const job = await api("POST", "/v1/jobs", { listing_id: listing.listing_id });
      navigate(`/job/${job.job_id}`);
    } catch (error) {
      setErr(error.message);
    } finally {
      setBusyId("");
    }
  }

  async function subscribe(e) {
    e.preventDefault();
    setSubMsg("");
    try {
      await api("POST", "/v1/subscriptions", {
        email: subEmail,
        ecosystem: eco,
        keywords: subKeywords.split(",").map((s) => s.trim()).filter(Boolean),
      });
      setSubMsg("Subscribed — digests send as matching listings appear.");
    } catch (error) {
      setSubMsg(error.message);
    }
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight">
          Web3 jobs, scanned continuously.
        </h1>
        <p className="text-neutral-600 mt-2 max-w-2xl">
          Pick a listing (or paste your own) and WorkOS generates a CV tailored to that
          posting from your profile. When the offer lands, the work agreement drafts
          itself from the same data and signs onchain.
        </p>
      </div>

      <div className="flex flex-wrap gap-3 mb-5">
        <input className="input max-w-xs" placeholder="Search role, firm, skill…"
               value={q} onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && load()} />
        <select className="input max-w-[180px]" value={eco} onChange={(e) => setEco(e.target.value)}>
          <option value="">All ecosystems</option>
          {data.facets.ecosystems.map((f) => (
            <option key={f.name} value={f.name}>{f.name} ({f.count})</option>
          ))}
        </select>
        <select className="input max-w-[140px]" value={remote} onChange={(e) => setRemote(e.target.value)}>
          <option value="">Any location</option>
          <option value="yes">Remote</option>
        </select>
        <button className="btn-ghost" onClick={load}>Search</button>
        <span className="text-sm text-neutral-500 self-center">{data.total} open listings</span>
      </div>

      {err && <p className="text-sm text-red-700 mb-4">{err}</p>}

      <div className="space-y-3">
        {data.listings.map((listing) => (
          <div key={listing.listing_id} className="panel flex items-start gap-4">
            <div className="flex-1 min-w-0">
              <div className="font-medium">{listing.role}</div>
              <div className="text-sm text-neutral-600">
                {listing.firm}
                {listing.location && ` · ${listing.location}`}
                {listing.remote === "yes" && " · Remote"}
                {listing.comp_range && ` · ${listing.comp_range}`}
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {listing.ecosystem && <span className="tag">{listing.ecosystem}</span>}
                {listing.skills.slice(0, 6).map((s) => <span key={s} className="tag">{s}</span>)}
              </div>
            </div>
            <div className="flex flex-col gap-2 shrink-0">
              <button className="btn" disabled={busyId === listing.listing_id}
                      onClick={() => tailor(listing)}>
                {busyId === listing.listing_id ? "Parsing…" : "Tailor CV"}
              </button>
              <a className="btn-ghost text-center" href={listing.url} target="_blank" rel="noreferrer">
                View posting
              </a>
            </div>
          </div>
        ))}
      </div>

      <div className="panel mt-10 max-w-xl">
        <h2 className="font-medium mb-1">Email digests</h2>
        <p className="text-sm text-neutral-600 mb-3">
          Get new listings matching your filters. Uses the ecosystem selected above
          plus any keywords.
        </p>
        <form onSubmit={subscribe} className="flex flex-wrap gap-2">
          <input className="input max-w-[220px]" type="email" required placeholder="you@example.com"
                 value={subEmail} onChange={(e) => setSubEmail(e.target.value)} />
          <input className="input max-w-[220px]" placeholder="keywords, comma-separated"
                 value={subKeywords} onChange={(e) => setSubKeywords(e.target.value)} />
          <button className="btn">Subscribe</button>
        </form>
        {subMsg && <p className="text-sm mt-2">{subMsg}</p>}
      </div>
    </div>
  );
}
