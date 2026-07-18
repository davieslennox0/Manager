import { getToken, setToken } from "./lib/api";
import { Link, navigate, usePath } from "./lib/router";
import Agreements from "./pages/Agreements.jsx";
import Board from "./pages/Board.jsx";
import JobDetail from "./pages/JobDetail.jsx";
import Jobs from "./pages/Jobs.jsx";
import Landing from "./pages/Landing.jsx";
import Login from "./pages/Login.jsx";
import Profile from "./pages/Profile.jsx";

function Nav() {
  const authed = !!getToken();
  return (
    <nav className="sticky top-0 z-20 bg-white/90 backdrop-blur border-b border-wos-border">
      <div className="max-w-5xl mx-auto px-4 h-14 flex items-center gap-6">
        <Link to="/" className="font-semibold tracking-tight text-lg">
          Manager<span className="text-neutral-500">X</span>
        </Link>
        <div className="hidden sm:flex items-center gap-5">
          <Link to="/board" className="text-sm text-neutral-600 hover:text-black">Job board</Link>
          <a href="/#features" className="text-sm text-neutral-600 hover:text-black">Features</a>
          <a href="/#how" className="text-sm text-neutral-600 hover:text-black">How it works</a>
        </div>
        {authed && (
          <div className="flex items-center gap-5">
            <Link to="/jobs" className="text-sm text-neutral-600 hover:text-black">My applications</Link>
            <Link to="/agreements" className="text-sm text-neutral-600 hover:text-black">Agreements</Link>
            <Link to="/profile" className="text-sm text-neutral-600 hover:text-black">Profile</Link>
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          {authed ? (
            <button className="btn-ghost"
                    onClick={() => { setToken(null); navigate("/"); }}>
              Log out
            </button>
          ) : (
            <>
              <Link to="/login" className="hidden sm:block text-sm text-neutral-600 hover:text-black">
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
  else if (path === "/jobs") page = <Jobs />;
  else if (path.startsWith("/job/")) page = <JobDetail jobId={path.split("/")[2]} />;
  else if (path === "/agreements") page = <Agreements />;
  else if (path === "/profile") page = <Profile />;
  else page = <Landing />;
  const landing = page.type === Landing;
  return (
    <div className="min-h-screen flex flex-col">
      <Nav />
      {landing ? <main className="flex-1">{page}</main> : (
        <main className="flex-1 max-w-5xl mx-auto px-4 py-8 w-full">{page}</main>
      )}
      <footer className="border-t border-wos-border">
        <div className="max-w-5xl mx-auto px-4 py-8 flex flex-wrap gap-x-8 gap-y-2 text-xs text-neutral-500">
          <span className="font-medium text-neutral-700">ManagerX</span>
          <Link to="/board" className="hover:text-black">Job board</Link>
          <a href="/#features" className="hover:text-black">Features</a>
          <a href="/#how" className="hover:text-black">How it works</a>
          <span className="ml-auto">
            Agreements sign onchain via SignatureRegistry · X Layer (196)
          </span>
        </div>
      </footer>
    </div>
  );
}
