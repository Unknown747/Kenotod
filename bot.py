"""
Stake.com Keno Bot
==================
Strategy:
  - Starting Bet : Rp160  → $0.01 USD
  - Target Profit: Rp320  → $0.02 USD
  - Loss Limit   : Rp32000 → $2.00 USD
  - Reset Threshold: Rp160 → $0.01 USD

Bet adjustment per round:
  WIN  → next_bet × 0.78
  LOSE → next_bet × 1.25

Reset rule (checked BEFORE applying win/loss multiplier):
  If current_bet > reset_threshold → reset to starting_bet, rotate client seed

Auto-stop:
  net_profit ≥ target_profit  → stop + rotate seed
  total_loss ≥ loss_limit     → stop
"""

import os
import sys
import time
import random
import string
import logging
import requests

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

# Currency on Stake for real-money play (lowercase enum value)
CURRENCY = "usd"

# IDR → USD conversion
IDR_PER_USD = 16_000

# Keno spot selection (1–10 numbers from 1–40).
# Adjust these to match your preferred picks.
KENO_SELECTIONS = [3, 7, 14, 22, 36]   # 5 spots

# Betting parameters (USD)
STARTING_BET   = 160   / IDR_PER_USD   # $0.01
TARGET_PROFIT  = 320   / IDR_PER_USD   # $0.02
LOSS_LIMIT     = 32_000 / IDR_PER_USD  # $2.00
RESET_THRESHOLD = 160  / IDR_PER_USD   # $0.01

WIN_MULTIPLIER  = 0.78
LOSE_MULTIPLIER = 1.25

# Minimum bet Stake accepts (usually $0.0001 for USD)
MIN_BET = 0.0001

# Delay between bets (seconds) – be kind to the API
BET_DELAY = 1.0

# ─── GraphQL helpers ────────────────────────────────────────────────────────

def _gql(query: str, variables: dict) -> dict:
    """Execute a GraphQL request and return the 'data' portion."""
    payload = {"query": query, "variables": variables}
    try:
        response = requests.post(API_URL, json=payload, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        log.error("HTTP error: %s", exc)
        raise

    result = response.json()
    if "errors" in result:
        log.error("GraphQL errors: %s", result["errors"])
        raise RuntimeError(f"GraphQL error: {result['errors']}")
    return result.get("data", {})


# ─── Seed management ────────────────────────────────────────────────────────

def _random_seed(length: int = 32) -> str:
    """Generate a cryptographically adequate random alphanumeric string."""
    alphabet = string.ascii_letters + string.digits
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(length))


UPDATE_SEED_MUTATION = """
mutation UpdateClientSeed($seed: String!) {
  updateClientSeed(seed: $seed) {
    clientSeed
    nextServerSeedHash
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
    applied = data.get("updateClientSeed", {}).get("clientSeed", new_seed)
    log.info("   Seed updated: %s", applied[:8] + "…")
    return applied


# ─── Keno bet ───────────────────────────────────────────────────────────────

KENO_BET_MUTATION = """
mutation KenoBet(
  $amount: Float!
  $currency: CurrencyEnum!
  $identifier: String!
  $clientSeed: String!
  $selections: [Int!]!
) {
  kenobet(
    amount: $amount
    currency: $currency
    identifier: $identifier
    clientSeed: $clientSeed
    selections: $selections
  ) {
    bet {
      id
      amount
      payout
      profit
      state {
        ... on CasinoGameKeno {
          result
          selections
          payoutMultiplier
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
}
"""


def place_bet(amount_usd: float, client_seed: str) -> dict:
    """
    Place a single Keno bet and return the parsed result dict:
      { 'id', 'amount', 'payout', 'profit', 'multiplier', 'result', 'balance' }
    """
    amount_usd = max(round(amount_usd, 8), MIN_BET)
    identifier = _random_seed(16)        # unique nonce per bet

    data = _gql(KENO_BET_MUTATION, {
        "amount":      amount_usd,
        "currency":    CURRENCY,
        "identifier":  identifier,
        "clientSeed":  client_seed,
        "selections":  KENO_SELECTIONS,
    })

    bet = data["kenobet"]["bet"]
    state = bet.get("state", {})
    balances = bet.get("user", {}).get("balances", [{}])
    balance = balances[0].get("available", {}).get("amount", 0) if balances else 0

    return {
        "id":         bet["id"],
        "amount":     float(bet["amount"]),
        "payout":     float(bet["payout"]),
        "profit":     float(bet["profit"]),
        "multiplier": float(state.get("payoutMultiplier", 0)),
        "result":     state.get("result", []),
        "balance":    float(balance),
    }


# ─── Main bot loop ──────────────────────────────────────────────────────────

def run_bot():
    log.info("=" * 60)
    log.info("  Stake Keno Bot starting")
    log.info("  Selections  : %s", KENO_SELECTIONS)
    log.info("  Start bet   : Rp%.0f ($%.4f)", STARTING_BET * IDR_PER_USD, STARTING_BET)
    log.info("  Target gain : Rp%.0f ($%.4f)", TARGET_PROFIT * IDR_PER_USD, TARGET_PROFIT)
    log.info("  Loss limit  : Rp%.0f ($%.2f)", LOSS_LIMIT * IDR_PER_USD, LOSS_LIMIT)
    log.info("  Reset thresh: Rp%.0f ($%.4f)", RESET_THRESHOLD * IDR_PER_USD, RESET_THRESHOLD)
    log.info("=" * 60)

    # Initialise client seed
    current_seed = reset_seed()

    current_bet = STARTING_BET
    net_profit  = 0.0          # cumulative profit/loss
    round_num   = 0

    while True:
        round_num += 1

        # ── Determine next bet amount ────────────────────────────────────
        # (Reset logic applied BEFORE win/loss multiplier)
        if current_bet > RESET_THRESHOLD + 1e-9:
            log.info("↩  Bet above reset threshold — resetting to starting bet & rotating seed")
            current_bet = STARTING_BET
            current_seed = reset_seed()

        # Clamp to minimum
        bet_amount = max(round(current_bet, 8), MIN_BET)

        # ── Place bet ────────────────────────────────────────────────────
        log.info(
            "Round %d | Bet: Rp%.0f ($%.5f) | Net P/L: Rp%.0f ($%.5f)",
            round_num,
            bet_amount * IDR_PER_USD,
            bet_amount,
            net_profit * IDR_PER_USD,
            net_profit,
        )

        try:
            result = place_bet(bet_amount, current_seed)
        except Exception as exc:
            log.error("Bet failed: %s — retrying in 5 s…", exc)
            time.sleep(5)
            continue

        profit_this_round = result["profit"]
        net_profit += profit_this_round
        won = profit_this_round > 0

        log.info(
            "       → %s | Payout: $%.5f | Multiplier: %.2fx | Round P/L: Rp%.0f | Net: Rp%.0f",
            "WIN 🟢" if won else "LOSE 🔴",
            result["payout"],
            result["multiplier"],
            profit_this_round * IDR_PER_USD,
            net_profit * IDR_PER_USD,
        )

        # ── Stop conditions ──────────────────────────────────────────────
        if net_profit >= TARGET_PROFIT:
            log.info("🎯 Target profit reached! Net gain: Rp%.0f ($%.4f)", net_profit * IDR_PER_USD, net_profit)
            log.info("🔄 Rotating seed before exit…")
            reset_seed()
            log.info("✅ Bot stopped — target achieved.")
            break

        if net_profit <= -LOSS_LIMIT:
            log.info("🛑 Loss limit hit! Net loss: Rp%.0f ($%.2f)", abs(net_profit) * IDR_PER_USD, abs(net_profit))
            log.info("✅ Bot stopped — loss limit reached.")
            break

        # ── Adjust bet for next round ─────────────────────────────────
        if won:
            current_bet = current_bet * WIN_MULTIPLIER
        else:
            current_bet = current_bet * LOSE_MULTIPLIER

        time.sleep(BET_DELAY)

    log.info("=" * 60)
    log.info("  Final net P/L: Rp%.0f ($%.5f)", net_profit * IDR_PER_USD, net_profit)
    log.info("  Total rounds : %d", round_num)
    log.info("=" * 60)


if __name__ == "__main__":
    run_bot()
