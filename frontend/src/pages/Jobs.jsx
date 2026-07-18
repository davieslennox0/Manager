import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Link, navigate } from "../lib/router";

const STATUS_LABEL = {
  parsed: "Posting parsed",
  cv_ready: "CV ready",
  accepted: "Offer accepted",
  contracted: "Contracted ✓",
};

export default function Jobs() {
  const [jobs, setJobs] = useState([]);
  const [url, setUrl] = useState("");
  const [rawText, setRawText] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("GET", "/v1/jobs").then((d) => setJobs(d.jobs)).catch((e) => {
      if (e.message.includes("Login")) navigate("/login?next=/jobs");
      else setErr(e.message);
    });
  }, []);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const job = await api("POST", "/v1/jobs", { url, raw_text: rawText });
      navigate(`/job/${job.job_id}`);
    } catch (error) {
      setErr(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold mb-6">My applications</h1>

      <div className="panel mb-8">
        <h2 className="font-medium mb-2">Start from a posting</h2>
        <form onSubmit={submit} className="space-y-3">
          <input className="input" placeholder="Posting URL (optional if you paste text)"
                 value={url} onChange={(e) => setUrl(e.target.value)} />
          <textarea className="input font-mono min-h-[120px]"
                    placeholder="…or paste the raw job posting text here"
                    value={rawText} onChange={(e) => setRawText(e.target.value)} />
          {err && <p className="text-sm text-red-700 dark:text-red-400">{err}</p>}
          <button className="btn" disabled={busy || (!url && !rawText)}>
            {busy ? "Parsing posting…" : "Parse posting"}
          </button>
        </form>
      </div>

      <div className="space-y-3">
        {jobs.map((job) => (
          <Link key={job.job_id} to={`/job/${job.job_id}`}
                className="panel flex items-center gap-4 hover:border-wos-accent dark:hover:border-white block">
            <div className="flex-1 min-w-0">
              <div className="font-medium">{job.parsed.role || "Untitled role"}</div>
              <div className="text-sm text-neutral-600 dark:text-neutral-400">
                {job.parsed.firm || "—"} · {new Date(job.created_at + "Z").toLocaleDateString()}
              </div>
            </div>
            <span className="tag">{STATUS_LABEL[job.status] || job.status}</span>
          </Link>
        ))}
        {jobs.length === 0 && !err && (
          <p className="text-sm text-neutral-500">
            Nothing yet — parse a posting above or pick one from the job board.
          </p>
        )}
      </div>
    </div>
  );
}
