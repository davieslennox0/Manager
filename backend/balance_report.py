"""End-of-business-day balance of the x402 PayTo wallet, pushed to Telegram.

Reports the balance of each accepted settlement token at the PayTo address (where
paywall + service revenue lands), plus native gas as an ops signal. Extensible: as
more rails are accepted (e.g. Base/USDC), add them to RAILS and they roll into the
same daily total.

The loop wakes on an interval and fires once per weekday at/after the target hour
(UTC). Last-sent date is persisted next to the DB so a process restart doesn't
re-send the same day's report."""
import asyncio
import datetime
import os
from pathlib import Path

from eth_account import Account
from web3 import Web3

import config
from notify import send_telegram

# The relayer (operator) — a DIFFERENT wallet from payTo — submits each settlement
# and pays gas. payTo only receives tokens, so the gas that matters lives here.
_RELAYER = (Account.from_key(config.X402_OPERATOR_KEY).address
            if config.X402_OPERATOR_KEY else "")
LOW_GAS = float(os.getenv("RELAYER_LOW_GAS", "0.01"))  # warn below this much native gas

# One entry per accepted settlement rail. Only X Layer/USDT0 is live today; append
# here when a new rail (its RPC + token) goes live so it joins the daily total.
RAILS = [{
    "network": "X Layer",
    "token": "USDT0",
    "rpc": config.XLAYER_RPC_URL,
    "contract": config.X402_USDT_CONTRACT,
    "decimals": 6,
    "gas_symbol": "OKB",
}]

_ERC20_ABI = [{
    "constant": True, "name": "balanceOf", "type": "function",
    "inputs": [{"name": "_owner", "type": "address"}],
    "outputs": [{"name": "balance", "type": "uint256"}],
}]

_STATE = Path(config.DATABASE_PATH).parent / ".balance_report_last"


def _fmt(units: int, decimals: int) -> str:
    """Atomic units -> trimmed human string. '12340000',6 -> '12.34'."""
    s = f"{units / (10 ** decimals):.{decimals}f}".rstrip("0").rstrip(".")
    return s or "0"


def read_payto_balances() -> dict:
    """Read the PayTo wallet's token + gas balance on each rail. Per-rail failures
    are captured (not raised) so one dead RPC doesn't sink the whole report."""
    payto = config.X402_PAY_TO
    rails = []
    total_stable = 0.0
    for r in RAILS:
        row = {"network": r["network"], "token": r["token"], "gas_symbol": r["gas_symbol"]}
        try:
            w3 = Web3(Web3.HTTPProvider(r["rpc"], request_kwargs={"timeout": 20}))
            addr = Web3.to_checksum_address(payto)
            token = w3.eth.contract(address=Web3.to_checksum_address(r["contract"]),
                                    abi=_ERC20_ABI)
            bal = token.functions.balanceOf(addr).call()
            row["token_balance"] = _fmt(bal, r["decimals"])
            total_stable += bal / (10 ** r["decimals"])
            if _RELAYER:  # gas lives on the relayer, not payTo
                gas_wei = w3.eth.get_balance(Web3.to_checksum_address(_RELAYER))
                row["relayer_gas"] = _fmt(gas_wei, 18)
                row["low_gas"] = gas_wei / 1e18 < LOW_GAS
        except Exception as e:
            row["error"] = f"{type(e).__name__}"
        rails.append(row)
    return {"payto": payto, "relayer": _RELAYER, "rails": rails,
            "total_stable": total_stable}


def format_report(data: dict, day: str) -> str:
    payto = data["payto"]
    short = f"{payto[:6]}…{payto[-4:]}" if payto else "(unset)"
    lines = [f"\U0001F4CA ManagerX — PayTo balance (EOD {day} UTC)", f"Wallet: {short}", ""]
    for r in data["rails"]:
        if r.get("error"):
            lines.append(f"{r['network']} · {r['token']}: ⚠️ read failed ({r['error']})")
            continue
        lines.append(f"{r['network']} · {r['token']}: {r['token_balance']}")
        if "relayer_gas" in r:
            warn = " ⚠️ LOW — top up to keep settling" if r.get("low_gas") else ""
            lines.append(f"    relayer gas ({r['gas_symbol']}): {r['relayer_gas']}{warn}")
    lines.append("")
    lines.append(f"Total: ≈ {data['total_stable']:.2f} (USD-stable)")
    return "\n".join(lines)


def send_balance_report(day: str | None = None) -> bool:
    day = day or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    return send_telegram(format_report(read_payto_balances(), day))


def _last_sent() -> str:
    try:
        return _STATE.read_text().strip()
    except Exception:
        return ""


def _mark_sent(day: str) -> None:
    try:
        _STATE.write_text(day)
    except Exception:
        pass


async def balance_report_loop() -> None:
    """Fire once per weekday at/after BALANCE_REPORT_HOUR_UTC. Re-checks on an
    interval so a restart within the day still catches up (persisted last-sent
    date prevents a duplicate)."""
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        today = now.date().isoformat()
        if (now.weekday() < 5 and now.hour >= config.BALANCE_REPORT_HOUR_UTC
                and _last_sent() != today):
            if await asyncio.to_thread(send_balance_report, today):
                _mark_sent(today)
        await asyncio.sleep(1800)  # 30 min
