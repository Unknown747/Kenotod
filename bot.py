"""
Stake.com Keno Bot
==================
Strategy:
  - Starting Bet   : Rp160    → $0.01 USD
  - Reset Threshold: Rp160    → $0.01 USD

Bet adjustment per round:
  WIN  → next_bet × 0.78
  LOSE → next_bet × 1.25

Reset rule (checked BEFORE applying win/loss multiplier):
  If current_bet > reset_threshold → reset to starting_bet, rotate client seed

Jeda otomatis (pause lalu lanjut):
  session profit ≥ Rp5.000   → jeda 1 menit, reset sesi
  session loss   ≥ Rp32.000  → jeda 5 menit, reset sesi
  setiap 1.000 spin           → jeda 1 menit, lanjut
"""

import os
import sys
import time
import random
import string
import logging
import requests
from dotenv import load_dotenv

load_dotenv()  # Baca variabel dari file .env

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("keno-bot")

# ─── Configuration ──────────────────────────────────────────────────────────
API_KEY = os.environ.get("STAKE_API_KEY", "")
if not API_KEY:
    log.error("STAKE_API_KEY environment variable is not set. Exiting.")
    sys.exit(1)

API_URL = "https://stake.com/_api/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "x-access-token": API_KEY,
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0",
}

# Currency on Stake — harus huruf kecil sesuai CurrencyEnum API
# Sesuaikan dengan currency akun kamu (lihat saldo di Stake)
# Contoh: "trx", "eth", "btc", "usdt", "ltc", "doge", "xrp", "bnb"
CURRENCY = "trx"

# IDR → USD conversion
IDR_PER_USD = 16_000

# Keno spot selection (1–10 numbers from 1–40).
# Adjust these to match your preferred picks.
KENO_SELECTIONS = [12, 13, 19, 20, 21, 22, 27, 28, 29, 30]   # 10 spots

# Betting parameters (USD)
STARTING_BET    = 160   / IDR_PER_USD   # $0.01
RESET_THRESHOLD = 160   / IDR_PER_USD   # $0.01

WIN_MULTIPLIER  = 0.78
LOSE_MULTIPLIER = 1.25

# ── Jeda otomatis ──────────────────────────────────────────────────────────
PAUSE_PROFIT_IDR  = 5_000    # Jeda 1 menit jika profit sesi ≥ Rp5.000
PAUSE_LOSS_IDR    = 32_000   # Jeda 5 menit jika loss sesi  ≥ Rp32.000
PAUSE_SPIN_EVERY  = 1_000    # Jeda 1 menit setiap N spin

PAUSE_PROFIT_SECS = 60       # 1 menit
PAUSE_LOSS_SECS   = 300      # 5 menit
PAUSE_SPIN_SECS   = 60       # 1 menit

# Konversi ke USD untuk perbandingan internal
PAUSE_PROFIT_USD  = PAUSE_PROFIT_IDR / IDR_PER_USD
PAUSE_LOSS_USD    = PAUSE_LOSS_IDR   / IDR_PER_USD

# Minimum bet Stake accepts (usually $0.0001 for USD)
MIN_BET = 0.0001

# Delay between bets (seconds) – be kind to the API
BET_DELAY = 1.0

# ─── GraphQL helpers ────────────────────────────────────────────────────────

class BetTooSmallError(Exception):
    """Stake menolak bet karena jumlahnya di bawah minimum."""


# Kata kunci error "amount too small" dari Stake API
_TOO_SMALL_KEYWORDS = ("too small", "minimum", "minim", "terlalu kecil", "below")


def _gql(query: str, variables: dict) -> dict:
    """Execute a GraphQL request and return the 'data' portion."""
    payload = {"query": query, "variables": variables}
    try:
        response = requests.post(API_URL, json=payload, headers=HEADERS, timeout=15)
        if not response.ok:
            log.error("HTTP %s — body: %s", response.status_code, response.text[:500])
            response.raise_for_status()
    except requests.RequestException as exc:
        log.error("HTTP error: %s", exc)
        raise

    result = response.json()
    if "errors" in result:
        msgs = " ".join(e.get("message", "").lower() for e in result["errors"])
        if any(k in msgs for k in _TOO_SMALL_KEYWORDS):
            raise BetTooSmallError(msgs)
        log.error("GraphQL errors: %s", result["errors"])
        raise RuntimeError(f"GraphQL error: {result['errors']}")
    return result.get("data", {})


# ─── Seed management ────────────────────────────────────────────────────────

def _random_seed(length: int = 32) -> str:
    """Generate a cryptographically adequate random alphanumeric string."""
    alphabet = string.ascii_letters + string.digits
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(length))


UPDATE_SEED_MUTATION = """
mutation ChangeClientSeed($seed: String!) {
  changeClientSeed(seed: $seed) {
    seed
  }
}
"""


def reset_seed() -> str:
    """
    Rotate the client seed on Stake via API.
    Returns the new seed string that was applied.
    """
    new_seed = _random_seed()
    log.info("🔄 Rotating client seed → %s…", new_seed[:8] + "…")
    data = _gql(UPDATE_SEED_MUTATION, {"seed": new_seed})
    applied = data.get("changeClientSeed", {}).get("seed", new_seed)
    log.info("   Seed updated: %s", applied[:8] + "…")
    return applied


# ─── Keno bet ───────────────────────────────────────────────────────────────

KENO_BET_MUTATION = """
mutation KenoBet(
  $amount: Float!
  $currency: CurrencyEnum!
  $identifier: String!
  $numbers: [Int!]!
  $risk: CasinoGameKenoRisk!
) {
  kenoBet(
    amount: $amount
    currency: $currency
    identifier: $identifier
    numbers: $numbers
    risk: $risk
  ) {
    id
    amount
    payout
    state {
      ... on CasinoGameKeno {
        __typename
      }
    }
    user {
      balances {
        available {
          amount
          currency
        }
      }
    }
  }
}
"""


def place_bet(amount_usd: float) -> dict:
    """
    Place a single Keno bet and return the parsed result dict:
      { 'id', 'amount', 'payout', 'profit', 'multiplier', 'balance' }
    The active client seed (set via changeClientSeed) is used automatically.
    """
    amount_usd = max(round(amount_usd, 8), MIN_BET)
    identifier = _random_seed(16)        # unique nonce per bet

    data = _gql(KENO_BET_MUTATION, {
        "amount":     amount_usd,
        "currency":   CURRENCY,
        "identifier": identifier,
        "numbers":    KENO_SELECTIONS,
        "risk":       "high",
    })

    bet = data["kenoBet"]
    payout   = float(bet.get("payout", 0))
    amount   = float(bet.get("amount", amount_usd))
    profit   = payout - amount          # API has no 'profit' field; derive it

    balances = bet.get("user", {}).get("balances", [{}])
    balance  = balances[0].get("available", {}).get("amount", 0) if balances else 0

    return {
        "id":      bet["id"],
        "amount":  amount,
        "payout":  payout,
        "profit":  profit,
        "balance": float(balance),
    }


# ─── Main bot loop ──────────────────────────────────────────────────────────

def pause_countdown(seconds: int, label: str):
    """Tampilkan countdown jeda di terminal."""
    log.info("⏸  %s — Jeda %d menit %d detik…",
             label, seconds // 60, seconds % 60)
    for remaining in range(seconds, 0, -10):
        mins, secs = divmod(remaining, 60)
        log.info("   ⏳ Lanjut dalam %02d:%02d …", mins, secs)
        time.sleep(min(10, remaining))
    log.info("▶  Jeda selesai — melanjutkan bot…")


def reset_session(current_bet_ref):
    """Reset statistik sesi dan kembalikan bet awal."""
    log.info("🔄 Reset sesi — bet kembali ke Rp%.0f", STARTING_BET * IDR_PER_USD)
    reset_seed()
    return STARTING_BET   # current_bet baru


def run_bot():
    log.info("=" * 60)
    log.info("  Stake Keno Bot starting")
    log.info("  Selections   : %s", KENO_SELECTIONS)
    log.info("  Start bet    : Rp%.0f", STARTING_BET * IDR_PER_USD)
    log.info("  Reset thresh : Rp%.0f", RESET_THRESHOLD * IDR_PER_USD)
    log.info("  Jeda profit  : Rp%.0f → %d menit", PAUSE_PROFIT_IDR, PAUSE_PROFIT_SECS // 60)
    log.info("  Jeda loss    : Rp%.0f → %d menit", PAUSE_LOSS_IDR, PAUSE_LOSS_SECS // 60)
    log.info("  Jeda spin    : setiap %d spin → %d menit", PAUSE_SPIN_EVERY, PAUSE_SPIN_SECS // 60)
    log.info("=" * 60)

    # Initialise client seed
    reset_seed()

    current_bet    = STARTING_BET

    # ── Statistik sesi (reset setiap jeda profit/loss) ──────────────────
    ses_profit     = 0.0
    ses_wins       = 0
    ses_losses     = 0

    # ── Statistik global (akumulasi sepanjang script jalan) ─────────────
    total_wager    = 0.0
    total_wins     = 0
    total_losses   = 0
    total_rounds   = 0

    def stats_line() -> str:
        profit_idr = ses_profit * IDR_PER_USD
        wager_idr  = total_wager * IDR_PER_USD
        profit_str = f"+{profit_idr:,.0f}" if profit_idr >= 0 else f"{profit_idr:,.0f}"
        return (
            f"Wager : Rp{wager_idr:,.0f}  |  "
            f"Profit : {profit_str}  |  "
            f"W/L : {total_wins}/{total_losses}"
        )

    while True:
        total_rounds += 1

        # ── Reset taruhan jika melebihi threshold ────────────────────────
        if current_bet > RESET_THRESHOLD + 1e-9:
            log.info("↩  Reset bet ke Rp%.0f & rotasi seed", STARTING_BET * IDR_PER_USD)
            current_bet = STARTING_BET
            reset_seed()

        # ── Proactive: bet terlalu kecil → reset ke base ─────────────────
        if current_bet < MIN_BET - 1e-10:
            log.warning(
                "⚠️  Bet Rp%.4f di bawah minimum — reset ke base Rp%.0f",
                current_bet * IDR_PER_USD,
                STARTING_BET * IDR_PER_USD,
            )
            current_bet = STARTING_BET

        bet_amount = round(current_bet, 8)

        # ── Place bet ────────────────────────────────────────────────────
        log.info("Spin #%d | Bet: Rp%.0f", total_rounds, bet_amount * IDR_PER_USD)

        try:
            result = place_bet(bet_amount)
        except BetTooSmallError:
            log.warning(
                "⚠️  Amount too small (Rp%.4f) — reset ke base Rp%.0f & lanjut",
                bet_amount * IDR_PER_USD,
                STARTING_BET * IDR_PER_USD,
            )
            current_bet = STARTING_BET
            continue
        except Exception as exc:
            log.error("Bet gagal: %s — retry 5 detik…", exc)
            time.sleep(5)
            continue

        profit_ronde  = result["profit"]
        ses_profit   += profit_ronde
        total_wager  += result["amount"]
        won           = profit_ronde > 0

        if won:
            ses_wins    += 1
            total_wins  += 1
            current_bet  = current_bet * WIN_MULTIPLIER
        else:
            ses_losses  += 1
            total_losses += 1
            current_bet  = current_bet * LOSE_MULTIPLIER

        log.info("       → %s | %s", "WIN 🟢" if won else "LOSE 🔴", stats_line())

        # ── Jeda setiap 1.000 spin ───────────────────────────────────────
        if total_rounds % PAUSE_SPIN_EVERY == 0:
            log.info("🔁 %d spin tercapai!", total_rounds)
            log.info("   %s", stats_line())
            pause_countdown(PAUSE_SPIN_SECS, f"{total_rounds} Spin")
            current_bet = reset_session(current_bet)
            ses_profit  = 0.0
            ses_wins    = 0
            ses_losses  = 0
            continue

        # ── Jeda profit sesi ─────────────────────────────────────────────
        if ses_profit >= PAUSE_PROFIT_USD:
            log.info("🎯 Profit sesi Rp%.0f tercapai!", ses_profit * IDR_PER_USD)
            log.info("   %s", stats_line())
            pause_countdown(PAUSE_PROFIT_SECS, "Profit Rp{:,.0f}".format(ses_profit * IDR_PER_USD))
            current_bet = reset_session(current_bet)
            ses_profit  = 0.0
            ses_wins    = 0
            ses_losses  = 0
            continue

        # ── Jeda stop loss sesi ──────────────────────────────────────────
        if ses_profit <= -PAUSE_LOSS_USD:
            log.info("🛑 Stop loss sesi Rp%.0f tercapai!", abs(ses_profit) * IDR_PER_USD)
            log.info("   %s", stats_line())
            pause_countdown(PAUSE_LOSS_SECS, "Stop Loss Rp{:,.0f}".format(abs(ses_profit) * IDR_PER_USD))
            current_bet = reset_session(current_bet)
            ses_profit  = 0.0
            ses_wins    = 0
            ses_losses  = 0
            continue

        time.sleep(BET_DELAY)


if __name__ == "__main__":
    run_bot()
