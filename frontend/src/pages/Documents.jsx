import { useEffect, useRef, useState } from "react";
import { api, apiUpload } from "../lib/api";
import { navigate } from "../lib/router";
import { connectWallet, explorerTx, sendCreateAgreement, sendSign } from "../lib/wallet";

const SEVERITY_CLS = {
  high: "text-red-700 dark:text-red-400",
  medium: "text-amber-700 dark:text-amber-400",
  low: "text-neutral-600 dark:text-neutral-400",
};

function Deadlines({ deadlines }) {
  if (!deadlines.length) return null;
  return (
    <div className="panel mb-6">
      <h2 className="font-medium mb-2">Coming up</h2>
      <div className="space-y-1">
        {deadlines.map((d, i) => (
          <div key={i} className="text-sm flex flex-wrap items-baseline gap-x-2">
            <span className={d.days_left <= 7 && d.days_left >= 0 ? "font-medium text-amber-700 dark:text-amber-400" : ""}>
              {d.date}
            </span>
            <span>{d.label}</span>
            <span className="text-xs text-neutral-500">
              {d.days_left < 0 ? "passed" : d.days_left === 0 ? "today" : `in ${d.days_left} day(s)`}
              {" · "}{d.filename || d.kind}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TermRow({ label, value }) {
  if (!value || (Array.isArray(value) && !value.length)) return null;
  return (
    <div className="text-sm">
      <span className="text-neutral-500">{label}: </span>
      {Array.isArray(value) ? value.join("; ") : value}
    </div>
  );
}

function Review({ review }) {
  const t = review.terms || {};
  const comp = t.compensation || {};
  return (
    <div className="space-y-4 mt-3">
      {review.summary && <p className="text-sm">{review.summary}</p>}
      <div className="space-y-1">
        <TermRow label="Position" value={t.position} />
        <TermRow label="Employer" value={t.employer} />
        <TermRow label="Type" value={t.employment_type} />
        <TermRow label="Compensation"
                 value={[comp.base && `${comp.base} ${comp.currency || ""} ${comp.period || ""}`.trim(),
                         comp.bonus && `bonus: ${comp.bonus}`,
                         comp.equity_or_tokens && `equity/tokens: ${comp.equity_or_tokens}`]
                        .filter(Boolean).join(" · ")} />
        <TermRow label="Location" value={t.location_or_remote} />
        <TermRow label="Start" value={t.start_date} />
        <TermRow label="Probation" value={t.probation?.length && `${t.probation.length} ${t.probation.terms || ""}`.trim()} />
        <TermRow label="Notice period" value={t.notice_period} />
        <TermRow label="Termination" value={t.termination} />
        <TermRow label="Non-compete" value={t.non_compete?.present &&
          `${t.non_compete.scope || "yes"}${t.non_compete.duration ? `, ${t.non_compete.duration}` : ""}`} />
        <TermRow label="IP assignment" value={t.ip_assignment} />
        <TermRow label="Governing law" value={t.governing_law} />
        <TermRow label="Benefits" value={t.benefits} />
        <TermRow label="Notable" value={t.other_notable} />
      </div>

      {(review.red_flags || []).length > 0 && (
        <div>
          <h3 className="font-medium text-sm mb-1">Red flags</h3>
          <div className="space-y-2">
            {review.red_flags.map((f, i) => (
              <div key={i} className="text-sm border-l-2 border-wos-border dark:border-wos-dborder pl-3">
                <span className={`uppercase text-xs font-medium ${SEVERITY_CLS[f.severity] || ""}`}>
                  {f.severity}
                </span>{" "}
                {f.clause}
                <div className="text-xs text-neutral-600 dark:text-neutral-400">{f.why}</div>
                {f.negotiation_pointer && (
                  <div className="text-xs mt-0.5">Ask: {f.negotiation_pointer}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {(review.posting_diff || []).length > 0 && (
        <div>
          <h3 className="font-medium text-sm mb-1">Against the posting you applied to</h3>
          <div className="space-y-1">
            {review.posting_diff.map((d, i) => (
              <div key={i} className="text-sm">
                <span className={d.assessment === "discrepancy"
                  ? "text-red-700 dark:text-red-400"
                  : d.assessment === "match" ? "text-wos-ok dark:text-green-400" : "text-neutral-500"}>
                  {d.assessment === "discrepancy" ? "≠" : d.assessment === "match" ? "=" : "+"}
                </span>{" "}
                <span className="font-medium">{d.aspect}</span>
                {d.assessment !== "new_info" && d.posting_said && (
                  <span className="text-neutral-500"> — posting: {d.posting_said};</span>
                )}
                {d.document_says && <span> document: {d.document_says}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Documents() {
  const [docs, setDocs] = useState([]);
  const [deadlines, setDeadlines] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [open, setOpen] = useState(null); // doc_id of the expanded card
  const [text, setText] = useState("");
  const [jobId, setJobId] = useState("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const fileRef = useRef();

  function load() {
    api("GET", "/v1/documents").then((d) => setDocs(d.documents)).catch((e) => {
      if (e.message.includes("Login")) navigate("/login?next=/documents");
      else setErr(e.message);
    });
    api("GET", "/v1/documents/deadlines").then((d) => setDeadlines(d.deadlines)).catch(() => {});
    api("GET", "/v1/jobs").then((d) => setJobs(d.jobs)).catch(() => {});
  }
  useEffect(load, []);

  async function run(name, fn) {
    setBusy(name); setErr("");
    try { await fn(); load(); } catch (e) { setErr(e.message); }
    setBusy("");
  }

  async function upload() {
    const file = fileRef.current?.files?.[0];
    if (!file && !text.trim()) { setErr("Choose a file or paste the document text."); return; }
    const form = new FormData();
    if (file) form.append("file", file);
    else form.append("text", text);
    if (jobId) form.append("job_id", jobId);
    await run("upload", async () => {
      const doc = await apiUpload("/v1/documents", form);
      if (doc.review_error) setErr(doc.review_error);
      setText(""); setJobId("");
      if (fileRef.current) fileRef.current.value = "";
      setOpen(doc.doc_id);
    });
  }

  async function anchor(doc) {
    await run("anchor-" + doc.doc_id, async () => {
      const full = await api("GET", `/v1/documents/${doc.doc_id}`);
      const req = full.anchor_request;
      if (!req?.registry) throw new Error("Anchoring unavailable — registry not configured");
      const { address } = await connectWallet(req.chain_id);
      const created = await sendCreateAgreement({
        chain_id: req.chain_id, registry: req.registry,
        args: [req.doc_hash, [address], 0, ""],
      });
      await sendSign(req.registry, created.chainAgreementId);
      await api("POST", `/v1/documents/${doc.doc_id}/anchor`, {
        chain_agreement_id: created.chainAgreementId, create_tx: created.txHash,
      });
    });
  }

  const jobLabel = (id) => {
    const job = jobs.find((jb) => jb.job_id === id);
    const p = job?.parsed || {};
    return p.role ? `${p.role}${p.firm ? " @ " + p.firm : ""}` : id;
  };

  return (
    <div>
      <h1 className="text-2xl font-semibold mb-1">Documents</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400 mb-6">
        Offers, contracts and NDAs you received — AI-reviewed for terms, red flags and
        deadlines, diffed against the posting you applied to, and anchorable onchain.
      </p>
      {err && <p className="text-sm text-red-700 dark:text-red-400 mb-4">{err}</p>}

      <Deadlines deadlines={deadlines.filter((d) => d.days_left >= -7)} />

      <div className="panel mb-6">
        <h2 className="font-medium mb-3">Review a document</h2>
        <div className="space-y-3">
          <input ref={fileRef} type="file" accept=".pdf,.txt,.md" className="text-sm" />
          <textarea className="input w-full h-28" placeholder="…or paste the offer / contract text here"
                    value={text} onChange={(e) => setText(e.target.value)} />
          <div className="flex flex-wrap items-center gap-3">
            <select className="input" value={jobId} onChange={(e) => setJobId(e.target.value)}>
              <option value="">Not linked to an application</option>
              {jobs.map((jb) => (
                <option key={jb.job_id} value={jb.job_id}>{jobLabel(jb.job_id)}</option>
              ))}
            </select>
            <button className="btn" disabled={busy === "upload"} onClick={upload}>
              {busy === "upload" ? "Reviewing…" : "Upload & review"}
            </button>
            <span className="text-xs text-neutral-500">
              Linking the application unlocks the posting-vs-offer diff.
            </span>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {docs.map((doc) => (
          <div key={doc.doc_id} className="panel">
            <div className="flex items-center gap-3 cursor-pointer"
                 onClick={() => setOpen(open === doc.doc_id ? null : doc.doc_id)}>
              <div className="flex-1 min-w-0">
                <div className="font-medium">
                  {doc.filename || doc.review?.terms?.position || `${doc.kind} document`}
                </div>
                <div className="text-xs text-neutral-600 dark:text-neutral-400 mt-0.5">
                  {doc.kind}
                  {doc.job_id && ` · ${jobLabel(doc.job_id)}`}
                  {" · "}{new Date(doc.created_at + "Z").toLocaleDateString()}
                  {doc.deadlines.length > 0 && ` · ${doc.deadlines.length} deadline(s)`}
                </div>
                <div className="font-mono text-xs mt-1 break-all text-neutral-500">{doc.doc_hash}</div>
              </div>
              <span className={`tag ${doc.status === "anchored" ? "text-wos-ok dark:text-green-400" : ""}`}>
                {doc.status}
              </span>
            </div>

            {open === doc.doc_id && (
              <div className="mt-2 border-t border-wos-border dark:border-wos-dborder pt-3">
                {doc.status === "uploaded"
                  ? <p className="text-sm text-neutral-500">Not reviewed yet.</p>
                  : <Review review={doc.review} />}
                <div className="flex flex-wrap items-center gap-3 mt-4">
                  {doc.status !== "anchored" && (
                    <button className="btn" disabled={busy === "anchor-" + doc.doc_id}
                            onClick={() => anchor(doc)}>
                      {busy === "anchor-" + doc.doc_id ? "Anchoring…" : "Anchor onchain"}
                    </button>
                  )}
                  {doc.anchor_tx && (
                    <a className="text-xs underline" href={explorerTx(doc.anchor_tx)}
                       target="_blank" rel="noreferrer">
                      anchor tx ↗
                    </a>
                  )}
                  <button className="btn-ghost text-sm" disabled={busy === "rereview"}
                          onClick={() => run("rereview", () =>
                            api("POST", `/v1/documents/${doc.doc_id}/review`))}>
                    Re-review
                  </button>
                  <button className="btn-ghost text-sm text-red-700 dark:text-red-400"
                          onClick={() => run("delete", () =>
                            api("DELETE", `/v1/documents/${doc.doc_id}`))}>
                    Delete
                  </button>
                  {doc.status !== "anchored" && (
                    <span className="text-xs text-neutral-500">
                      Anchoring writes the document hash to SignatureRegistry from your
                      wallet — tamper-evident proof of what you were sent.
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
        {docs.length === 0 && !err && (
          <p className="text-sm text-neutral-500">
            Nothing in the vault yet — upload the first offer or contract you receive.
          </p>
        )}
      </div>
    </div>
  );
}
