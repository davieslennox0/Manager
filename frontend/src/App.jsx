import { useState } from "react";
import { getToken, setToken } from "./lib/api";
import { Link, navigate, usePath } from "./lib/router";
import AgentJobs from "./pages/AgentJobs.jsx";
import Agreements from "./pages/Agreements.jsx";
import Board from "./pages/Board.jsx";
import Documents from "./pages/Documents.jsx";
import HouseholdGigDetail from "./pages/HouseholdGigDetail.jsx";
import HouseholdGigs from "./pages/HouseholdGigs.jsx";
import JobDetail from "./pages/JobDetail.jsx";
import Jobs from "./pages/Jobs.jsx";
import Landing from "./pages/Landing.jsx";
import Login from "./pages/Login.jsx";
import Profile from "./pages/Profile.jsx";
import TrackRecord from "./pages/TrackRecord.jsx";

function ThemeToggle() {
  const [dark, setDark] = useState(document.documentElement.classList.contains("dark"));
  function toggle() {
    const next = document.documentElement.classList.toggle("dark");
    localStorage.setItem("workos_theme", next ? "dark" : "light");
    setDark(next);
  }
  return (
    <button className="w-9 h-9 rounded-lg border border-wos-border hover:border-wos-accent dark:border-wos-dborder dark:hover:border-white text-sm transition-colors"
            title={dark ? "Switch to light mode" : "Switch to dark mode"}
            onClick={toggle}>
      {dark ? "☀" : "☾"}
    </button>
  );
}

function Nav() {
  const authed = !!getToken();
  return (
    <nav className="sticky top-0 z-20 bg-white/90 dark:bg-wos-dbg/90 backdrop-blur border-b border-wos-border dark:border-wos-dborder">
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center gap-5">
        <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight text-lg">
          <img src="/managerx-logo.png" alt="" aria-hidden="true" className="h-6 w-auto" />
          <span>Manager<span className="text-neutral-500">X</span></span>
        </Link>
        {/* Real routes: always available. Marketing anchors: signed-out only, so a
            logged-in bar doesn't carry 11 links. */}
        <div className="hidden sm:flex items-center gap-4">
          <Link to="/board" className="text-sm text-neutral-600 dark:text-neutral-400 hover:text-black dark:hover:text-white">Job board</Link>
          <Link to="/agent-jobs" className="text-sm text-neutral-600 dark:text-neutral-400 hover:text-black dark:hover:text-white">Agent&nbsp;Jobs</Link>
          <Link to="/household-gigs" className="text-sm text-neutral-600 dark:text-neutral-400 hover:text-black dark:hover:text-white">Household&nbsp;Gigs</Link>
        </div>
        {!authed && (
          <div className="hidden lg:flex items-center gap-4">
            <a href="/#features" className="text-sm text-neutral-600 dark:text-neutral-400 hover:text-black dark:hover:text-white">Features</a>
            <a href="/#review" className="text-sm text-neutral-600 dark:text-neutral-400 hover:text-black dark:hover:text-white">Contract review</a>
            <a href="/#agents" className="text-sm text-neutral-600 dark:text-neutral-400 hover:text-black dark:hover:text-white">For agents</a>
            <a href="/#how" className="text-sm text-neutral-600 dark:text-neutral-400 hover:text-black dark:hover:text-white">How it works</a>
          </div>
        )}
        {authed && (
          <div className="flex items-center gap-5">
            <Link to="/jobs" className="text-sm text-neutral-600 dark:text-neutral-400 hover:text-black dark:hover:text-white">My applications</Link>
            <Link to="/documents" className="text-sm text-neutral-600 dark:text-neutral-400 hover:text-black dark:hover:text-white">Documents</Link>
            <Link to="/agreements" className="text-sm text-neutral-600 dark:text-neutral-400 hover:text-black dark:hover:text-white">Agreements</Link>
            <Link to="/profile" className="text-sm text-neutral-600 dark:text-neutral-400 hover:text-black dark:hover:text-white">Profile</Link>
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          {authed ? (
            <button className="btn-ghost"
                    onClick={() => { setToken(null); navigate("/"); }}>
              Log out
            </button>
          ) : (
            <>
              <Link to="/login" className="hidden sm:block text-sm text-neutral-600 dark:text-neutral-400 hover:text-black dark:hover:text-white">
                Log in
              </Link>
              <Link to="/signup" className="btn !px-5">Sign in</Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}

export default function App() {
  const path = usePath();
  let page;
  if (path === "/login" || path === "/signup") page = <Login mode={path.slice(1)} />;
  else if (path === "/board") page = <Board />;
  else if (path === "/agent-jobs") page = <AgentJobs />;
  else if (path === "/household-gigs") page = <HouseholdGigs />;
  else if (path.startsWith("/household-gigs/"))
    page = <HouseholdGigDetail gigId={path.split("/")[2]} />;
  else if (path === "/jobs") page = <Jobs />;
  else if (path.startsWith("/job/")) page = <JobDetail jobId={path.split("/")[2]} />;
  else if (path === "/documents") page = <Documents />;
  else if (path === "/agreements") page = <Agreements />;
  else if (path === "/profile") page = <Profile />;
  else if (path.startsWith("/u/")) page = <TrackRecord handle={path.split("/")[2]} />;
  else page = <Landing />;
  const landing = page.type === Landing;
  return (
    <div className="min-h-screen flex flex-col">
      <Nav />
      {landing ? <main className="flex-1">{page}</main> : (
        <main className="flex-1 max-w-7xl mx-auto px-4 py-8 w-full">{page}</main>
      )}
      <footer className="border-t border-wos-border dark:border-wos-dborder">
        <div className="max-w-7xl mx-auto px-4 py-8 flex flex-wrap gap-x-8 gap-y-2 text-xs text-neutral-500">
          <span className="font-medium text-neutral-700 dark:text-neutral-300">ManagerX</span>
          <Link to="/board" className="hover:text-black dark:hover:text-white">Job board</Link>
          <Link to="/agent-jobs" className="hover:text-black dark:hover:text-white">Agent Jobs</Link>
          <a href="/#features" className="hover:text-black dark:hover:text-white">Features</a>
          <a href="/#review" className="hover:text-black dark:hover:text-white">Contract review</a>
          <a href="/#agents" className="hover:text-black dark:hover:text-white">For agents</a>
          <Link to="/household-gigs" className="hover:text-black dark:hover:text-white">Household Gigs</Link>
          <a href="/#how" className="hover:text-black dark:hover:text-white">How it works</a>
          <span className="ml-auto">
            Documents anchor onchain via SignatureRegistry · X Layer (196)
          </span>
        </div>
      </footer>
    </div>
  );
}
