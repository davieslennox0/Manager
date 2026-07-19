import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { navigate } from "../lib/router";
import { explorerTx, signMessage } from "../lib/wallet";

const EMPTY_EXP = { title: "", org: "", start: "", end: "", bullets: [] };

function GitHubConnect() {
  const [status, setStatus] = useState(null);
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => { api("GET", "/v1/proof/github").then(setStatus).catch(() => {}); }, []);

  async function connectPublic(e) {
    e.preventDefault();
    setBusy(true); setMsg("");
    try {
      setStatus(await api("POST", "/v1/proof/github/public", { username }));
    } catch (error) { setMsg(error.message); }
    setBusy(false);
  }
  async function oauth() {
    try {
      const { url } = await api("GET", "/v1/proof/github/login");
      window.location.href = url;
    } catch (error) { setMsg(error.message); }
  }
  async function refresh() {
    setBusy(true); setMsg("");
    try { setStatus(await api("POST", "/v1/proof/github/refresh")); }
    catch (error) { setMsg(error.message); }
    setBusy(false);
  }
  async function disconnect() {
    await api("DELETE", "/v1/proof/github").catch(() => {});
    setStatus({ connected: false, oauth_enabled: status?.oauth_enabled });
  }

  if (!status) return null;
  return (
    <div className="card-inner">
      <div className="font-medium text-sm mb-1">GitHub</div>
      {status.connected ? (
        <div className="text-sm">
          <span className="text-neutral-600 dark:text-neutral-400">
            @{status.username} · {status.repo_count} repos cached
            {status.mode === "public" && " (public data)"}
          </span>
          <div className="flex gap-2 mt-2">
            <button className="btn-ghost !py-1 text-xs" disabled={busy} onClick={refresh}>
              {busy ? "Refreshing…" : "Refresh repos"}
            </button>
            <button className="text-xs text-red-700 dark:text-red-400 underline" onClick={disconnect}>
              Disconnect
            </button>
          </div>
        </div>
      ) : (
        <div>
          <p className="text-xs text-neutral-600 dark:text-neutral-400 mb-2">
            Repos, READMEs and pinned projects become matchable proof-of-work for
            every application.
          </p>
          {status.oauth_enabled && (
            <button className="btn !py-1.5 text-sm mb-2" onClick={oauth}>
              Connect with GitHub (read-only)
            </button>
          )}
          <form onSubmit={connectPublic} className="flex gap-2">
            <input className="input max-w-[200px]" placeholder="github username"
                   value={username} onChange={(e) => setUsername(e.target.value)} />
            <button className="btn-ghost" disabled={busy || !username}>
              {busy ? "Fetching…" : status.oauth_enabled ? "Or public-only" : "Connect (public repos)"}
            </button>
          </form>
        </div>
      )}
      {msg && <p className="text-xs mt-2 text-red-700 dark:text-red-400">{msg}</p>}
    </div>
  );
}

function WalletConnect() {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => { api("GET", "/v1/proof/wallet").then(setStatus).catch(() => {}); }, []);

  async function connect() {
    setBusy(true); setMsg("");
    try {
      const { nonce, message } = await api("GET", "/v1/proof/wallet/nonce");
      const { address, signature } = await signMessage(message);
      setStatus(await api("POST", "/v1/proof/wallet", { address, signature, nonce }));
    } catch (error) { setMsg(error.message); }
    setBusy(false);
  }
  async function disconnect() {
    await api("DELETE", "/v1/proof/wallet").catch(() => {});
    setStatus({ connected: false });
  }

  if (!status) return null;
  const act = status.activity || {};
  return (
    <div className="card-inner">
      <div className="font-medium text-sm mb-1">Wallet</div>
      {status.connected ? (
        <div className="text-sm">
          <span className="font-mono text-xs break-all">{status.address}</span>
          <div className="text-xs text-neutral-600 dark:text-neutral-400 mt-1">
            {Object.entries(act.tx_counts || {}).map(([chain, n]) =>
              n !== null ? `${chain}: ${n} txs` : null).filter(Boolean).join(" · ")}
            {act.dao_votes > 0 && ` · ${act.dao_votes} DAO votes (Snapshot)`}
          </div>
          <button className="text-xs text-red-700 dark:text-red-400 underline mt-2" onClick={disconnect}>
            Disconnect
          </button>
        </div>
      ) : (
        <div>
          <p className="text-xs text-neutral-600 dark:text-neutral-400 mb-2">
            Sign one message (free, offchain) to attach your onchain activity —
            tx history and DAO votes — as evidence.
          </p>
          <button className="btn !py-1.5 text-sm" disabled={busy} onClick={connect}>
            {busy ? "Waiting for wallet…" : "Connect + sign"}
          </button>
        </div>
      )}
      {msg && <p className="text-xs mt-2 text-red-700 dark:text-red-400">{msg}</p>}
    </div>
  );
}

function PublicTrackRecord({ profile }) {
  const [handle, setHandle] = useState("");
  const [isPublic, setIsPublic] = useState(false);
  const [msg, setMsg] = useState("");
  const [url, setUrl] = useState("");

  useEffect(() => {
    setHandle(profile.handle || "");
    setIsPublic(!!profile.public_profile);
    if (profile.handle && profile.public_profile) setUrl(`/u/${profile.handle}`);
  }, [profile.handle, profile.public_profile]);

  async function save(nextPublic) {
    setMsg("");
    try {
      const res = await api("PUT", "/v1/public/settings", { handle, public: nextPublic });
      setIsPublic(nextPublic);
      setUrl(nextPublic && res.handle ? `/u/${res.handle}` : "");
      setMsg(nextPublic ? "Live." : "Unpublished.");
    } catch (error) { setMsg(error.message); }
  }

  return (
    <div className="panel">
      <h2 className="font-medium mb-1">Public track record</h2>
      <p className="text-sm text-neutral-600 dark:text-neutral-400 mb-3">
        A shareable page of your onchain-verified contracts, proof-of-work repos
        and tailored-CV stats — with a proof card per completed contract.
      </p>
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-sm text-neutral-500">managerx.xyz/u/</span>
        <input className="input max-w-[180px]" placeholder="your-handle"
               value={handle}
               onChange={(e) => setHandle(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))} />
        {isPublic ? (
          <button className="btn-ghost" onClick={() => save(false)}>Unpublish</button>
        ) : (
          <button className="btn" disabled={!handle} onClick={() => save(true)}>Publish</button>
        )}
        {url && (
          <a className="text-sm underline" href={url} target="_blank" rel="noreferrer">
            View public page ↗
          </a>
        )}
      </div>
      {msg && <p className="text-sm mt-2">{msg}</p>}
    </div>
  );
}

export default function Profile() {
  const [p, setP] = useState(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api("GET", "/v1/profile").then(setP).catch((e) => {
      if (e.message.includes("Login")) navigate("/login?next=/profile");
      else setMsg(e.message);
    });
  }, []);

  if (!p) return <p className="text-sm text-neutral-500">{msg || "Loading…"}</p>;

  function set(field, value) {
    setP({ ...p, [field]: value });
  }

  async function save() {
    setMsg("");
    try {
      const { verified_work_history, ...body } = p;
      await api("PUT", "/v1/profile", body);
      setMsg("Saved.");
    } catch (error) {
      setMsg(error.message);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <h1 className="text-2xl font-semibold">Profile — your data spine</h1>
        <button className="btn ml-auto" onClick={save}>Save</button>
      </div>
      <p className="text-sm text-neutral-600 dark:text-neutral-400 -mt-3 max-w-2xl">
        Every tailored CV and every work agreement is generated from this one object.
        Executed onchain agreements append verified entries below automatically.
      </p>
      {msg && <p className="text-sm">{msg}</p>}

      <div className="panel grid sm:grid-cols-2 gap-4">
        {[["full_name", "Full name"], ["headline", "Headline"], ["location", "Location"]].map(([f, label]) => (
          <div key={f}>
            <label className="label">{label}</label>
            <input className="input" value={p[f] || ""} onChange={(e) => set(f, e.target.value)} />
          </div>
        ))}
        <div>
          <label className="label">Links (label=url, one per line)</label>
          <textarea className="input font-mono" rows={2}
                    value={(p.links || []).map((l) => `${l.label}=${l.url}`).join("\n")}
                    onChange={(e) => set("links", e.target.value.split("\n").filter(Boolean).map((line) => {
                      const [label, ...rest] = line.split("=");
                      return { label: label.trim(), url: rest.join("=").trim() };
                    }))} />
        </div>
        <div className="sm:col-span-2">
          <label className="label">Summary</label>
          <textarea className="input" rows={3} value={p.summary || ""}
                    onChange={(e) => set("summary", e.target.value)} />
        </div>
        <div className="sm:col-span-2">
          <label className="label">Skills (comma-separated)</label>
          <input className="input" value={(p.skills || []).join(", ")}
                 onChange={(e) => set("skills", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
        </div>
      </div>

      <div className="panel">
        <div className="flex items-center mb-3">
          <h2 className="font-medium">Experience</h2>
          <button className="btn-ghost ml-auto"
                  onClick={() => set("experience", [...(p.experience || []), { ...EMPTY_EXP }])}>
            + Add
          </button>
        </div>
        <div className="space-y-4">
          {(p.experience || []).map((exp, i) => (
            <div key={i} className="card-inner space-y-2">
              <div className="grid sm:grid-cols-4 gap-2">
                {[["title", "Title"], ["org", "Organisation"], ["start", "Start"], ["end", "End"]].map(([f, ph]) => (
                  <input key={f} className="input" placeholder={ph} value={exp[f] || ""}
                         onChange={(e) => {
                           const next = [...p.experience];
                           next[i] = { ...exp, [f]: e.target.value };
                           set("experience", next);
                         }} />
                ))}
              </div>
              <textarea className="input font-mono" rows={2}
                        placeholder="Achievements, one per line"
                        value={(exp.bullets || []).join("\n")}
                        onChange={(e) => {
                          const next = [...p.experience];
                          next[i] = { ...exp, bullets: e.target.value.split("\n").filter(Boolean) };
                          set("experience", next);
                        }} />
              <button className="text-xs text-red-700 dark:text-red-400 underline"
                      onClick={() => set("experience", p.experience.filter((_, k) => k !== i))}>
                Remove
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <h2 className="font-medium mb-2">Education (degree | school | year, one per line)</h2>
        <textarea className="input font-mono" rows={2}
                  value={(p.education || []).map((ed) => `${ed.degree} | ${ed.school} | ${ed.year}`).join("\n")}
                  onChange={(e) => set("education", e.target.value.split("\n").filter(Boolean).map((line) => {
                    const [degree = "", school = "", year = ""] = line.split("|").map((s) => s.trim());
                    return { degree, school, year };
                  }))} />
      </div>

      <div className="panel">
        <h2 className="font-medium mb-1">Proof-of-work sources</h2>
        <p className="text-sm text-neutral-600 dark:text-neutral-400 mb-3">
          Connected sources are matched per-application by the LLM against each
          posting — the top hits land in the CV's "Relevant work" section.
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          <GitHubConnect />
          <WalletConnect />
        </div>
      </div>

      <PublicTrackRecord profile={p} />

      <div className="panel">
        <h2 className="font-medium mb-3">Verified work history (onchain)</h2>
        {(p.verified_work_history || []).length === 0 && (
          <p className="text-sm text-neutral-500">
            None yet — fully executed work agreements land here as signed, timestamped,
            unfakeable entries and strengthen every future CV.
          </p>
        )}
        <div className="space-y-3">
          {(p.verified_work_history || []).map((h, i) => (
            <div key={i} className="card-inner">
              <div className="font-medium text-sm">{h.title}</div>
              <div className="text-xs text-neutral-600 dark:text-neutral-400">
                {h.counterparty && `${h.counterparty} · `}{h.start} – {h.end}
              </div>
              <div className="text-xs font-mono mt-1 break-all">
                <a className="underline" href={explorerTx(h.onchain_tx)} target="_blank" rel="noreferrer">
                  {h.onchain_tx.slice(0, 18)}… ↗
                </a>
                <span className="text-wos-ok dark:text-green-400 ml-2">verified ✓</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
