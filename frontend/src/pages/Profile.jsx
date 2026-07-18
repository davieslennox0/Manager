import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { navigate } from "../lib/router";
import { explorerTx } from "../lib/wallet";

const EMPTY_EXP = { title: "", org: "", start: "", end: "", bullets: [] };

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
