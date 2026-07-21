"""Central env-var access. Required vars raise at first use with a clear message;
optional vars gate features off cleanly when unset (see .env.example for the split)."""
import os

from dotenv import load_dotenv

load_dotenv()


def require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var {name} (see .env.example)")
    return val


DATABASE_PATH = os.getenv("DATABASE_PATH", "./workos.db")
PORT = int(os.getenv("PORT", "8011"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", f"http://localhost:{PORT}")

SECRET_KEY = require("WORKOS_SECRET_KEY")
ADMIN_EMAIL = os.getenv("WORKOS_ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.getenv("WORKOS_ADMIN_PASSWORD", "")

# X Layer mainnet — SignatureRegistry lives here; browser wallets write, we read.
XLAYER_RPC_URL = os.getenv("XLAYER_RPC_URL", "https://rpc.xlayer.tech")
CHAIN_ID = int(os.getenv("CHAIN_ID", "196"))
REGISTRY_ADDRESS = os.getenv("SIGNATURE_REGISTRY_ADDRESS", "")

# x402: ManagerX's paid agentic surface (the /v1/benchmark ASP service). Gated on
# a payTo + operator key being present, so the app boots and the whole product
# still works without them — payment just isn't required. Same pattern as SMTP.
X402_PAY_TO = os.getenv("MANAGERX_X402_PAY_TO", "")
X402_OPERATOR_KEY = os.getenv("OPERATOR_WALLET_PRIVATE_KEY", "")
X402_USDT_CONTRACT = os.getenv("XLAYER_X402_USDT_CONTRACT_ADDRESS", "")
X402_ENABLED = bool(X402_PAY_TO and X402_OPERATOR_KEY and X402_USDT_CONTRACT)

# Paywall the website itself: agent/programmatic clients pay 0.1 USDT0 per page
# view (per request, no session — a return visit pays again); human browsers and
# crawlers pass through free. On by default when x402 is on; set 0 to lift it.
WEBSITE_WALL_ENABLED = os.getenv("WEBSITE_WALL_ENABLED", "1") == "1"
PAGE_FEE_ATOMIC = os.getenv("X402_PAGE_FEE_ATOMIC", "100000")  # 0.1 USDT0

# Second x402 rail: Base/USDC settled through Coinbase's CDP Facilitator. This is
# the ONLY way into the x402 Bazaar discovery index (Bazaar can't see our
# self-hosted X Layer/USDT0 rail). Inert until the CDP API key lands — the X Layer
# rail (OKX #7120) is unaffected. Needs `pip install cdp-sdk` for request auth.
CDP_FACILITATOR_URL = os.getenv("CDP_FACILITATOR_URL",
                                "https://api.cdp.coinbase.com/platform/v2/x402")
CDP_API_KEY_ID = os.getenv("CDP_API_KEY_ID", "")
CDP_API_KEY_SECRET = os.getenv("CDP_API_KEY_SECRET", "")
BASE_X402_PAY_TO = os.getenv("BASE_X402_PAY_TO", "")   # EVM addr to receive USDC on Base
BASE_USDC_CONTRACT = os.getenv("BASE_USDC_CONTRACT",
                               "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")  # USDC on Base
X402_CDP_ENABLED = bool(CDP_API_KEY_ID and CDP_API_KEY_SECRET and BASE_X402_PAY_TO)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# Digest email is optional: unset SMTP -> subscriptions are captured but sends
# are skipped (same gate-off pattern as x402 in the sibling services).
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "ManagerX <no-reply@localhost>")
SMTP_ENABLED = bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)

SCANNER_ENABLED = os.getenv("SCANNER_ENABLED", "1") == "1"
SCANNER_TICK_SECONDS = int(os.getenv("SCANNER_TICK_SECONDS", "300"))

# Newly-funded pipeline: funding feeds poll on their own (slower) loop; a firm
# counts as "newly funded" for FRESH_DAYS after its announcement.
FUNDING_ENABLED = os.getenv("FUNDING_ENABLED", "1") == "1"
FUNDING_TICK_SECONDS = int(os.getenv("FUNDING_TICK_SECONDS", "21600"))
FUNDING_FRESH_DAYS = int(os.getenv("FUNDING_FRESH_DAYS", "90"))

# GitHub OAuth for the proof-of-work CV layer. Unset -> the OAuth button hides
# and users connect in public-data mode (public repos only, no token stored).
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_OAUTH_ENABLED = bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)

# Read-side RPCs for wallet-footprint lookups beyond X Layer.
ETH_RPC_URL = os.getenv("ETH_RPC_URL", "https://cloudflare-eth.com")
SNAPSHOT_HUB_URL = os.getenv("SNAPSHOT_HUB_URL", "https://hub.snapshot.org/graphql")
