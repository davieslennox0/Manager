import { useEffect, useState } from "react";
import { api, getToken } from "../lib/api";
import { Link, navigate } from "../lib/router";
import { explorerTx, sendCreateAgreement, sendSign } from "../lib/wallet";

export default function JobDetail({ jobId }) {
  const [job, setJob] = useState(null);
  const [agreement, setAgreement] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [privacyMode, setPrivacyMode] = useState("HASH_ONLY");
  const [signersText, setSignersText] = useState("");
  const [applyTo, setApplyTo] = useState("");
  const [letter, setLetter] = useState("");
  const [sentTo, setSentTo] = useState("");

  async function load() {
    try {
      const jobData = await api("GET", `/v1/jobs/${jobId}`);
      setJob(jobData);
      setApplyTo((prev) => prev || jobData.parsed?.apply_email || "");
      setLetter((prev) => prev || jobData.cover_letter || "");
      const all = await api("GET", "/v1/agreements");
      setAgreement(all.agreements.find((a) => a.job_id === jobId) || null);
    } catch (error) {
      if (error.message.includes("Login")) navigate(`/login?next=/job/${jobId}`);
      else setErr(error.message);
    }
  }
  useEffect(() => { load(); }, [jobId]);

  async function run(name, fn) {
    setBusy(name);
    setErr("");
    try {
      await fn();
      await load();
    } catch (error) {
      setErr(error.message);
    } finally {
      setBusy("");
    }
  }

  if (!job) return <p className="text-sm text-neutral-500">{err || "Loading…"}</p>;
  const parsed = job.parsed || {};
  const cv = job.cv?.content;

  function setCvField(field, value) {
    setJob({ ...job, cv: { ...job.cv, content: { ...cv, [field]: value } } });
  }

  async function downloadPdf() {
    const resp = await fetch(`/v1/jobs/${jobId}/cv.pdf`,
      { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!resp.ok) { setErr("Export failed — generate the CV first"); return; }
    const blob = await resp.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `cv-${(parsed.role || "role").replaceAll(" ", "-")}.pdf`;
    a.click();
  }

  return (
    <div className="space-y-6">
      {/* ── Posting signals ─────────────────────────────────────────── */}
      <div className="panel">
        <div className="flex items-start gap-3">
          <div>
            <h1 className="text-xl font-semibold">{parsed.role || "Role"}</h1>
            <p className="text-sm text-neutral-600 dark:text-neutral-400">
              {parsed.firm || "Unknown firm"}
              {parsed.ecosystem && ` · ${parsed.ecosystem}`}
              {parsed.comp_range && ` · ${parsed.comp_range}`}
              {parsed.duration && ` · ${parsed.duration}`}
            </p>
          </div>
          <span className="tag ml-auto">{job.status}</span>
        </div>
        <p className="text-sm mt-2">{parsed.summary}</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {(parsed.required_skills || []).map((s) => <span key={s} className="tag font-medium">{s}</span>)}
          {(parsed.nice_to_have || []).map((s) => <span key={s} className="tag text-neutral-500">{s}</span>)}
        </div>
        <p className="text-xs text-neutral-500 mt-2">
          Seniority: {parsed.seniority} · Tone: {parsed.tone} · Language: {parsed.language}
        </p>
      </div>

      {err && <p className="text-sm text-red-700 dark:text-red-400">{err}</p>}

      {/* ── Tailored CV ─────────────────────────────────────────────── */}
      <div className="panel">
        <div className="flex items-center gap-2 mb-3">
          <h2 className="font-medium">Tailored CV</h2>
          <div className="ml-auto flex gap-2">
            <button className="btn-ghost" disabled={busy === "cv"}
                    onClick={() => run("cv", () => api("POST", `/v1/jobs/${jobId}/cv`))}>
              {busy === "cv" ? "Generating…" : cv ? "Regenerate" : "Generate from profile"}
            </button>
            {cv && (
              <>
                <button className="btn-ghost" disabled={busy === "proof"}
                        title="LLM-ranks your connected GitHub repos + onchain history against THIS posting"
                        onClick={() => run("proof", () => api("POST", `/v1/proof/jobs/${jobId}/match`))}>
                  {busy === "proof" ? "Matching…" : "Match proof-of-work"}
                </button>
                <button className="btn-ghost" disabled={busy === "save"}
                        onClick={() => run("save", () => api("PUT", `/v1/jobs/${jobId}/cv`, { content: cv }))}>
                  Save edits
                </button>
                <button className="btn" onClick={downloadPdf}>Export PDF</button>
              </>
            )}
          </div>
        </div>
        {!cv && (
          <p className="text-sm text-neutral-500">
            One click generates a CV specific to this posting — your skills reordered to
            mirror its language, irrelevant experience dropped.
          </p>
        )}
        {cv && (
          <div className="space-y-3">
            <div>
              <label className="label">Headline</label>
              <input className="input" value={cv.headline || ""}
                     onChange={(e) => setCvField("headline", e.target.value)} />
            </div>
            <div>
              <label className="label">Summary</label>
              <textarea className="input" rows={3} value={cv.summary || ""}
                        onChange={(e) => setCvField("summary", e.target.value)} />
            </div>
            <div>
              <label className="label">Skills (ordered, comma-separated)</label>
              <input className="input" value={(cv.skills || []).join(", ")}
                     onChange={(e) => setCvField("skills",
                       e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
            </div>
            {(cv.experience || []).map((exp, i) => (
              <div key={i} className="card-inner">
                <div className="text-sm font-medium">
                  {exp.title} — {exp.org}
                  {exp.verified && <span className="text-wos-ok dark:text-green-400 text-xs ml-2">onchain-verified ✓</span>}
                  <span className="text-neutral-500 font-normal ml-2">{exp.start} – {exp.end}</span>
                </div>
                <textarea className="input font-mono mt-2" rows={Math.max(2, (exp.bullets || []).length)}
                          value={(exp.bullets || []).join("\n")}
                          onChange={(e) => {
                            const next = [...cv.experience];
                            next[i] = { ...exp, bullets: e.target.value.split("\n").filter(Boolean) };
                            setCvField("experience", next);
                          }} />
              </div>
            ))}

            {(cv.relevant_work || []).length > 0 && (
              <div>
                <label className="label">Relevant work — proof (matched to this posting)</label>
                <div className="space-y-2">
                  {cv.relevant_work.map((rw) => (
                    <div key={rw.repo} className="card-inner">
                      <div className="text-sm font-medium">
                        <a className="underline" href={rw.url} target="_blank" rel="noreferrer">
                          {rw.repo}
                        </a>
                        {rw.pinned && <span className="tag ml-2">pinned</span>}
                        {rw.language && <span className="text-neutral-500 font-normal ml-2">{rw.language}</span>}
                        {rw.stars > 0 && <span className="text-neutral-500 font-normal ml-2">★ {rw.stars}</span>}
                      </div>
                      {rw.why && <p className="text-xs text-neutral-600 dark:text-neutral-400 mt-1">{rw.why}</p>}
                      {rw.proof_point && <p className="text-xs mt-1">Proof point: {rw.proof_point}</p>}
                      {(rw.verified_contracts || []).map((vc) => (
                        <p key={vc.address} className="text-xs font-mono mt-1 break-all">
                          <a className="underline" href={vc.explorer_url} target="_blank" rel="noreferrer">
                            {vc.address}
                          </a>
                          <span className="text-wos-ok dark:text-green-400 ml-2">
                            deployed on {vc.chain} ✓
                          </span>
                        </p>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {cv.onchain_footprint?.platform?.claim && (
              <p className="text-sm text-wos-ok dark:text-green-400">
                {cv.onchain_footprint.platform.claim} — auto-attached to the CV.
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── Email-apply (postings with an application address) ──────── */}
      {cv && (
        <div className="panel">
          <div className="flex items-center gap-2 mb-1">
            <h2 className="font-medium">Apply by email</h2>
            {job.applied_at && <span className="tag text-wos-ok dark:text-green-400">sent</span>}
          </div>
          <p className="text-sm text-neutral-600 dark:text-neutral-400 mb-3">
            {parsed.apply_email
              ? "This posting accepts email applications — we send the cover letter with your tailored CV attached, replies go straight to your inbox."
              : "No application address found in this posting — export the PDF and apply on their site, or enter an address if you have one."}
          </p>
          <div className="space-y-3">
            <input className="input max-w-md" placeholder="applications@firm.xyz"
                   value={applyTo} onChange={(e) => setApplyTo(e.target.value)} />
            <textarea className="input w-full" rows={7}
                      placeholder="Cover letter — generate a draft or write your own"
                      value={letter} onChange={(e) => setLetter(e.target.value)} />
            <div className="flex flex-wrap items-center gap-3">
              <button className="btn-ghost" disabled={busy === "letter"}
                      onClick={() => run("letter", async () => {
                        const d = await api("POST", `/v1/jobs/${jobId}/cover-letter`);
                        setLetter(d.cover_letter);
                      })}>
                {busy === "letter" ? "Drafting…" : "Draft cover letter"}
              </button>
              <button className="btn" disabled={busy === "apply" || !applyTo}
                      onClick={() => run("apply", async () => {
                        const d = await api("POST", `/v1/jobs/${jobId}/apply`,
                          { to_email: applyTo, cover_letter: letter });
                        setSentTo(d.sent_to);
                      })}>
                {busy === "apply" ? "Sending…" : "Send application"}
              </button>
              {sentTo && (
                <span className="text-sm text-wos-ok dark:text-green-400">
                  Sent to {sentTo} — replies come to your email.
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Offer accepted → agreement ──────────────────────────────── */}
      {job.status !== "accepted" && job.status !== "contracted" && (
        <div className="panel flex items-center gap-4">
          <div className="flex-1">
            <h2 className="font-medium">Got the offer / gig?</h2>
            <p className="text-sm text-neutral-600 dark:text-neutral-400">
              Marking it accepted unlocks the work-agreement stage — scope of work drafts
              from the same profile data the CV used.
            </p>
          </div>
          <button className="btn" disabled={busy === "accept"}
                  onClick={() => run("accept", () => api("POST", `/v1/jobs/${jobId}/accept`))}>
            Mark accepted
          </button>
        </div>
      )}

      {(job.status === "accepted" || job.status === "contracted") && (
        <div className="panel flex items-center gap-4">
          <div className="flex-1">
            <h2 className="font-medium">Offer in writing?</h2>
            <p className="text-sm text-neutral-600 dark:text-neutral-400">
              Upload the offer or contract they sent — AI review extracts the terms,
              flags risky clauses, and diffs it against this posting.
            </p>
          </div>
          <Link to="/documents" className="btn">Review it</Link>
        </div>
      )}

      {(job.status === "accepted" || job.status === "contracted") && (
        <div className="panel">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="font-medium">Work agreement</h2>
            {agreement && <span className="tag">{agreement.status.replaceAll("_", " ")}</span>}
            {!agreement && (
              <button className="btn ml-auto" disabled={busy === "draft"}
                      onClick={() => run("draft", () => api("POST", `/v1/agreements/draft/${jobId}`))}>
                {busy === "draft" ? "Drafting…" : "Draft agreement"}
              </button>
            )}
          </div>

          {agreement && (
            <AgreementPanel
              agreement={agreement}
              busy={busy}
              run={run}
              privacyMode={privacyMode}
              setPrivacyMode={setPrivacyMode}
              signersText={signersText}
              setSignersText={setSignersText}
            />
          )}
        </div>
      )}
    </div>
  );
}

function AgreementPanel({ agreement, busy, run, privacyMode, setPrivacyMode, signersText, setSignersText }) {
  const content = agreement.content || {};
  const draft = agreement.status === "draft";
  const [local, setLocal] = useState(content);
  useEffect(() => { setLocal(content); }, [agreement.agreement_id, agreement.status]);

  function setField(field, value) {
    setLocal({ ...local, [field]: value });
  }

  return (
    <div className="space-y-3">
      <div>
        <label className="label">Title</label>
        <input className="input" value={local.title || ""} disabled={!draft}
               onChange={(e) => setField("title", e.target.value)} />
      </div>
      <div>
        <label className="label">Scope of work (one clause per line — derived from your claimed skills)</label>
        <textarea className="input font-mono" rows={Math.max(3, (local.scope_of_work || []).length)}
                  value={(local.scope_of_work || []).join("\n")} disabled={!draft}
                  onChange={(e) => setField("scope_of_work", e.target.value.split("\n").filter(Boolean))} />
      </div>
      <div className="grid sm:grid-cols-3 gap-2">
        <div>
          <label className="label">Payment amount</label>
          <input className="input" value={local.payment?.amount || ""} disabled={!draft}
                 onChange={(e) => setField("payment", { ...local.payment, amount: e.target.value })} />
        </div>
        <div>
          <label className="label">Schedule</label>
          <input className="input" value={local.payment?.schedule || ""} disabled={!draft}
                 onChange={(e) => setField("payment", { ...local.payment, schedule: e.target.value })} />
        </div>
        <div>
          <label className="label">Currency</label>
          <input className="input" value={local.payment?.currency || ""} disabled={!draft}
                 onChange={(e) => setField("payment", { ...local.payment, currency: e.target.value })} />
        </div>
      </div>
      <div className="grid sm:grid-cols-2 gap-2">
        <div>
          <label className="label">Start</label>
          <input className="input" value={local.duration?.start || ""} disabled={!draft}
                 onChange={(e) => setField("duration", { ...local.duration, start: e.target.value })} />
        </div>
        <div>
          <label className="label">End / term</label>
          <input className="input" value={local.duration?.end_or_term || ""} disabled={!draft}
                 onChange={(e) => setField("duration", { ...local.duration, end_or_term: e.target.value })} />
        </div>
      </div>
      <p className="text-xs text-neutral-500">
        {content.termination} · {content.ip_and_confidentiality}
      </p>

      {draft && (
        <div className="border-t border-wos-border dark:border-wos-dborder pt-3 space-y-3">
          <button className="btn-ghost" disabled={busy === "saveagr"}
                  onClick={() => run("saveagr", () =>
                    api("PUT", `/v1/agreements/${agreement.agreement_id}`, { content: local }))}>
            Save edits
          </button>
          <div className="flex flex-wrap gap-2 items-end">
            <div>
              <label className="label">Privacy mode</label>
              <select className="input" value={privacyMode}
                      onChange={(e) => setPrivacyMode(e.target.value)}>
                <option value="HASH_ONLY">HASH_ONLY — only the doc hash goes onchain</option>
                <option value="WITH_METADATA">WITH_METADATA — title + parties too</option>
              </select>
            </div>
            <div className="flex-1 min-w-[260px]">
              <label className="label">Signer wallets (comma-separated 0x…)</label>
              <input className="input font-mono" placeholder="0xyou…, 0xclient…"
                     value={signersText} onChange={(e) => setSignersText(e.target.value)} />
            </div>
            <button className="btn" disabled={busy === "finalize" || !signersText.trim()}
                    onClick={() => run("finalize", () =>
                      api("POST", `/v1/agreements/${agreement.agreement_id}/finalize`, {
                        privacy_mode: privacyMode,
                        signers: signersText.split(",").map((s) => s.trim()).filter(Boolean),
                      }))}>
              Finalize — lock hash
            </button>
          </div>
        </div>
      )}

      {agreement.status === "pending_signatures" && (
        <PendingSignatures agreement={agreement} busy={busy} run={run} />
      )}

      {agreement.status === "executed" && (
        <div className="border-t border-wos-border dark:border-wos-dborder pt-3 text-sm">
          <p className="text-wos-ok dark:text-green-400 font-medium">
            Fully executed onchain ✓ — added to your verified work history.
          </p>
          <p className="font-mono text-xs mt-1 break-all">
            doc hash {agreement.doc_hash}
            {agreement.create_tx && (
              <a className="underline ml-2" href={explorerTx(agreement.create_tx)}
                 target="_blank" rel="noreferrer">tx ↗</a>
            )}
          </p>
        </div>
      )}
    </div>
  );
}

function PendingSignatures({ agreement, busy, run }) {
  const onchain = agreement.onchain;
  return (
    <div className="border-t border-wos-border dark:border-wos-dborder pt-3 space-y-3">
      <p className="text-sm">
        Doc hash locked: <span className="font-mono text-xs break-all">{agreement.doc_hash}</span>
      </p>
      {!agreement.chain_agreement_id ? (
        <button className="btn" disabled={busy === "chain"}
                onClick={() => run("chain", async () => {
                  const fin = await api("GET", `/v1/agreements/${agreement.agreement_id}`);
                  if (!fin.tx_request) throw new Error("No pending transaction for this agreement");
                  const result = await sendCreateAgreement(fin.tx_request);
                  await api("POST", `/v1/agreements/${agreement.agreement_id}/anchor`, {
                    chain_agreement_id: result.chainAgreementId,
                    create_tx: result.txHash,
                  });
                })}>
          {busy === "chain" ? "Confirm in wallet…" : "Create onchain (wallet)"}
        </button>
      ) : (
        <div className="space-y-2">
          <p className="text-sm">
            Onchain agreement #{agreement.chain_agreement_id} —{" "}
            {onchain ? `${onchain.signed_count}/${onchain.signers.length} signatures` : "…"}
          </p>
          {onchain && onchain.signers.map((s) => (
            <p key={s} className="font-mono text-xs">
              {s.slice(0, 10)}…{s.slice(-6)} {onchain.signed_at[s] ? "✓ signed" : "— pending"}
            </p>
          ))}
          <div className="flex gap-2">
            <button className="btn" disabled={busy === "sign"}
                    onClick={() => run("sign", async () => {
                      const health = await api("GET", "/health");
                      await sendSign(health.registry, agreement.chain_agreement_id);
                      await api("POST", `/v1/agreements/${agreement.agreement_id}/refresh`);
                    })}>
              {busy === "sign" ? "Confirm in wallet…" : "Sign (wallet)"}
            </button>
            <button className="btn-ghost" disabled={busy === "refresh"}
                    onClick={() => run("refresh", () =>
                      api("POST", `/v1/agreements/${agreement.agreement_id}/refresh`))}>
              Refresh status
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
