import { getToken, setToken } from "./lib/api";
import { Link, navigate, usePath } from "./lib/router";
import Agreements from "./pages/Agreements.jsx";
import Board from "./pages/Board.jsx";
import JobDetail from "./pages/JobDetail.jsx";
import Jobs from "./pages/Jobs.jsx";
import Login from "./pages/Login.jsx";
import Profile from "./pages/Profile.jsx";

function Nav() {
  const authed = !!getToken();
  return (
    <nav className="border-b border-wos-border">
      <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-5">
        <Link to="/" className="font-semibold tracking-tight text-lg">
          Work<span className="text-neutral-500">OS</span>
        </Link>
        <Link to="/" className="text-sm text-neutral-600 hover:text-black">Job board</Link>
        {authed && (
          <>
            <Link to="/jobs" className="text-sm text-neutral-600 hover:text-black">My applications</Link>
            <Link to="/agreements" className="text-sm text-neutral-600 hover:text-black">Agreements</Link>
            <Link to="/profile" className="text-sm text-neutral-600 hover:text-black">Profile</Link>
          </>
        )}
        <div className="ml-auto">
          {authed ? (
            <button
              className="btn-ghost"
              onClick={() => { setToken(null); navigate("/"); }}
            >
              Log out
            </button>
          ) : (
            <Link to="/login" className="btn">Log in</Link>
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
  else if (path === "/jobs") page = <Jobs />;
  else if (path.startsWith("/job/")) page = <JobDetail jobId={path.split("/")[2]} />;
  else if (path === "/agreements") page = <Agreements />;
  else if (path === "/profile") page = <Profile />;
  else page = <Board />;
  return (
    <div className="min-h-screen">
      <Nav />
      <main className="max-w-5xl mx-auto px-4 py-8">{page}</main>
      <footer className="max-w-5xl mx-auto px-4 py-8 text-xs text-neutral-500 border-t border-wos-border">
        Agreements sign onchain via SignatureRegistry on X Layer (chain 196). Executed
        agreements become verified, timestamped work-history entries.
      </footer>
    </div>
  );
}
