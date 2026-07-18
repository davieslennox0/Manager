import { useState } from "react";
import { api, setToken } from "../lib/api";
import { Link, navigate } from "../lib/router";

export default function Login({ mode }) {
  const signup = mode === "signup";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const data = await api("POST", `/v1/auth/${signup ? "signup" : "login"}`, { email, password });
      setToken(data.token);
      const next = new URLSearchParams(window.location.search).get("next");
      navigate(next || "/jobs");
    } catch (error) {
      setErr(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-sm mx-auto panel mt-10">
      <h1 className="text-lg font-semibold mb-4">{signup ? "Create account" : "Log in"}</h1>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="label">Email</label>
          <input className="input" type="email" value={email} required
                 onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="label">Password</label>
          <input className="input" type="password" value={password} required minLength={8}
                 onChange={(e) => setPassword(e.target.value)} />
        </div>
        {err && <p className="text-sm text-red-700">{err}</p>}
        <button className="btn w-full" disabled={busy}>
          {busy ? "…" : signup ? "Sign up" : "Log in"}
        </button>
      </form>
      <p className="text-sm text-neutral-600 mt-4">
        {signup ? "Already have an account? " : "New here? "}
        <Link to={signup ? "/login" : "/signup"} className="underline">
          {signup ? "Log in" : "Create one"}
        </Link>
      </p>
    </div>
  );
}
