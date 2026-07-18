import { useEffect, useState } from "react";
import { api, getToken } from "../lib/api";
import { navigate } from "../lib/router";

export default function Board() {
  const [data, setData] = useState({ total: 0, listings: [],
                                     facets: { ecosystems: [], categories: [] } });
  const [q, setQ] = useState("");
  const [eco, setEco] = useState("");
  const [remote, setRemote] = useState("");
  const [category, setCategory] = useState("");
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
    if (category) params.set("category", category);
    try {
      setData(await api("GET", `/v1/listings?${params}`));
    } catch (error) {
      setErr(error.message);
    }
  }
  useEffect(() => { load(); }, [eco, remote, category]);

  async function tailor(listing) {
    if (!getToken()) {
      navigate("/login?next=/board");
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
        role_keywords: category ? [category.split(" ")[0]] : [],
        keywords: subKeywords.split(",").map((s) => s.trim()).filter(Boolean),
      });
      setSubMsg("Subscribed — digests send as matching listings appear.");
    } catch (error) {
      setSubMsg(error.message);
    }
  }

  const allCount = data.facets.categories.reduce((n, f) => n + f.count, 0);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-3xl font-semibold tracking-tight">Job board</h1>
        <p className="text-neutral-600 dark:text-neutral-400 mt-1">
          Scanned continuously from Web3 career pages and aggregators. Pick a listing
          and get a CV tailored to it in one click.
        </p>
      </div>

      {/* Category pills */}
      <div className="flex flex-wrap gap-2 mb-4">
        <button onClick={() => setCategory("")}
                className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
                  category === "" ? "bg-wos-accent text-white border-wos-accent"
                                  : "border-wos-border hover:border-wos-accent"}`}>
          All {allCount > 0 && <span className="opacity-60">({allCount})</span>}
        </button>
        {data.facets.categories.map((f) => (
          <button key={f.name} onClick={() => setCategory(f.name === category ? "" : f.name)}
                  className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
                    category === f.name ? "bg-wos-accent text-white border-wos-accent"
                                        : "border-wos-border hover:border-wos-accent"}`}>
            {f.name} <span className="opacity-60">({f.count})</span>
          </button>
        ))}
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
        <span className="text-sm text-neutral-500 self-center">{data.total} listings</span>
      </div>

      {err && <p className="text-sm text-red-700 dark:text-red-400 mb-4">{err}</p>}

      <div className="space-y-3">
        {data.listings.map((listing) => (
          <div key={listing.listing_id} className="panel flex items-start gap-4">
            <div className="flex-1 min-w-0">
              <div className="font-medium">{listing.role}</div>
              <div className="text-sm text-neutral-600 dark:text-neutral-400">
                {listing.firm}
                {listing.location && ` · ${listing.location}`}
                {listing.remote === "yes" && " · Remote"}
                {listing.comp_range && ` · ${listing.comp_range}`}
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {listing.category && <span className="tag font-medium">{listing.category}</span>}
                {listing.ecosystem && <span className="tag">{listing.ecosystem}</span>}
                {listing.skills.slice(0, 5).map((s) => <span key={s} className="tag">{s}</span>)}
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
        {data.listings.length === 0 && !err && (
          <p className="text-sm text-neutral-500">No listings match these filters.</p>
        )}
      </div>

      <div className="panel mt-10 max-w-xl">
        <h2 className="font-medium mb-1">Email digests</h2>
        <p className="text-sm text-neutral-600 dark:text-neutral-400 mb-3">
          Get new listings matching your filters — uses the category and ecosystem
          selected above, plus any keywords.
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
