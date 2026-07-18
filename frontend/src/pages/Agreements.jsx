import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Link, navigate } from "../lib/router";
import { explorerTx } from "../lib/wallet";

export default function Agreements() {
  const [agreements, setAgreements] = useState([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api("GET", "/v1/agreements").then((d) => setAgreements(d.agreements)).catch((e) => {
      if (e.message.includes("Login")) navigate("/login?next=/agreements");
      else setErr(e.message);
    });
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-semibold mb-6">Work agreements</h1>
      {err && <p className="text-sm text-red-700 dark:text-red-400">{err}</p>}
      <div className="space-y-3">
        {agreements.map((a) => (
          <Link key={a.agreement_id} to={`/job/${a.job_id}`}
                className="panel block hover:border-wos-accent dark:hover:border-white">
            <div className="flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="font-medium">{a.content.title || "Work Agreement"}</div>
                <div className="text-xs text-neutral-600 dark:text-neutral-400 mt-0.5">
                  {a.privacy_mode}
                  {a.chain_agreement_id && ` · onchain #${a.chain_agreement_id}`}
                  {" · "}{new Date(a.created_at + "Z").toLocaleDateString()}
                </div>
                {a.doc_hash && (
                  <div className="font-mono text-xs mt-1 break-all text-neutral-500">
                    {a.doc_hash}
                  </div>
                )}
              </div>
              <span className={`tag ${a.status === "executed" ? "text-wos-ok dark:text-green-400" : ""}`}>
                {a.status.replaceAll("_", " ")}
              </span>
            </div>
            {a.create_tx && (
              <span className="text-xs underline"
                    onClick={(e) => { e.preventDefault(); window.open(explorerTx(a.create_tx)); }}>
                view tx ↗
              </span>
            )}
          </Link>
        ))}
        {agreements.length === 0 && !err && (
          <p className="text-sm text-neutral-500">
            No agreements yet — they draft from accepted jobs in “My applications”.
          </p>
        )}
      </div>
    </div>
  );
}
