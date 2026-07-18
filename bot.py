"""
Stake.com Keno Bot
==================
Strategi:
  - Starting Bet   : Rp160
  - Reset Threshold: Rp160
  - WIN  → bet berikutnya × 0.78  (turun 22%)
  - LOSE → bet berikutnya × 1.25  (naik 25%)

Reset rule (dicek SETELAH bet ditempatkan):
  Jika bet_amount yang baru saja dipakai > reset_threshold
  → ronde berikutnya dimulai dari starting_bet & rotasi seed

Jeda otomatis (pause lalu lanjut):
  profit sesi ≥ Rp5.000  → jeda 1 menit, reset sesi
  loss sesi   ≥ Rp32.000 → jeda 5 menit, reset sesi
  setiap 1.000 spin       → jeda 1 menit, lanjut
"""

import os
import sys
import time
import random
import string
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("keno-bot")

# ─── Konfigurasi API ──────────────────────────────────────────────────────────
API_KEY = os.environ.get("STAKE_API_KEY", "")
if not API_KEY:
    log.error("STAKE_API_KEY belum di-set. Jalankan setup.sh terlebih dahulu.")
    sys.exit(1)

API_URL = "https://stake.com/_api/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "x-access-token": API_KEY,
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0",
}

# ─── Konfigurasi Bot (semua dalam IDR) ───────────────────────────────────────
# Currency — huruf kecil, sesuai CurrencyEnum Stake
CURRENCY = "idr"

# Angka keno yang dipilih (10 spot, 1–40)
KENO_SELECTIONS = [12, 13, 19, 20, 21, 22, 27, 28, 29, 30]

# Bet (IDR) — selalu integer bulat karena IDR tidak pakai desimal
STARTING_BET    = 160      # Rp160
RESET_THRESHOLD = 160      # Rp160
MIN_BET         = 100      # Batas minimum — jika di bawah ini, reset ke STARTING_BET

WIN_MULTIPLIER  = 0.78
LOSE_MULTIPLIER = 1.25

# Jeda otomatis (IDR)
PAUSE_PROFIT    = 5_000    # Rp5.000  → jeda 1 menit
PAUSE_LOSS      = 32_000   # Rp32.000 → jeda 5 menit
PAUSE_SPIN_EVERY = 1_000   # setiap 1.000 spin → jeda 1 menit

PAUSE_PROFIT_SECS = 60
PAUSE_LOSS_SECS   = 300
PAUSE_SPIN_SECS   = 60

# Delay antar bet (detik)
BET_DELAY = 1.0

# Batas spin untuk testing (0 = unlimited / mode live)
MAX_SPINS = int(os.environ.get("MAX_SPINS", "0"))

# ─── Exception khusus ────────────────────────────────────────────────────────
class BetTooSmallError(Exception):
    """Stake menolak bet karena jumlahnya di bawah minimum."""

_TOO_SMALL_KEYWORDS = ("too small", "minimum", "minim", "terlalu kecil", "below")

# ─── GraphQL helper ───────────────────────────────────────────────────────────
def _gql(query: str, variables: dict) -> dict:
    payload = {"query": query, "variables": variables}
    try:
        resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=15)
        if not resp.ok:
            log.error("HTTP %s — %s", resp.status_code, resp.text[:400])
            resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("HTTP error: %s", exc)
        raise

    result = resp.json()
    if "errors" in result:
        msgs = " ".join(e.get("message", "").lower() for e in result["errors"])
        if any(k in msgs for k in _TOO_SMALL_KEYWORDS):
            raise BetTooSmallError(msgs)
        log.error("GraphQL errors: %s", result["errors"])
        raise RuntimeError(f"GraphQL error: {result['errors']}")
    return result.get("data", {})

# ─── Seed management ──────────────────────────────────────────────────────────
def _random_seed(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(length))

CHANGE_SEED_MUTATION = """
mutation ChangeClientSeed($seed: String!) {
  changeClientSeed(seed: $seed) {
    seed
  }
}
"""

def reset_seed() -> str:
    new_seed = _random_seed()
    log.info("🔄 Rotasi seed → %s…", new_seed[:8] + "…")
    data    = _gql(CHANGE_SEED_MUTATION, {"seed": new_seed})
    applied = data.get("changeClientSeed", {}).get("seed", new_seed)
    log.info("   Seed aktif : %s…", applied[:8])
    return applied

# ─── Keno bet ─────────────────────────────────────────────────────────────────
KENO_BET_MUTATION = """
mutation KenoBet(
  $amount: Float!
  $currency: CurrencyEnum!
  $identifier: String!
  $numbers: [Int!]!
  $risk: CasinoGameKenoRiskEnum!
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

def place_bet(amount_idr: float) -> dict:
    """
    Pasang satu bet Keno. Amount dalam IDR (dibulatkan ke integer bulat).
    Return: { id, amount, payout, profit, balance }  ← semua dalam IDR
    """
    # FIX #1: IDR tidak pakai desimal — kirim sebagai integer bulat
    amount_idr = max(int(round(amount_idr)), MIN_BET)
    identifier = _random_seed(16)

    data = _gql(KENO_BET_MUTATION, {
        "amount":     amount_idr,
        "currency":   CURRENCY,
        "identifier": identifier,
        "numbers":    KENO_SELECTIONS,
        "risk":       "high",
    })

    bet    = data["kenoBet"]
    payout = float(bet.get("payout", 0))
    amount = float(bet.get("amount", amount_idr))
    profit = payout - amount

    # FIX #3: Cari saldo sesuai currency yang dikonfigurasi, bukan langsung [0]
    balance = 0.0
    for bal in bet.get("user", {}).get("balances", []):
        avail = bal.get("available", {})
        if avail.get("currency", "").lower() == CURRENCY.lower():
            balance = float(avail.get("amount", 0))
            break

    return {
        "id":      bet["id"],
        "amount":  amount,
        "payout":  payout,
        "profit":  profit,
        "balance": balance,
    }

# ─── Countdown jeda ───────────────────────────────────────────────────────────
def pause_countdown(seconds: int, label: str):
    log.info("⏸  %s — Jeda %d menit %d detik…", label, seconds // 60, seconds % 60)
    for remaining in range(seconds, 0, -10):
        m, s = divmod(remaining, 60)
        log.info("   ⏳ Lanjut dalam %02d:%02d …", m, s)
        time.sleep(min(10, remaining))
    log.info("▶  Jeda selesai — melanjutkan bot…")

def reset_session():
    log.info("🔄 Reset sesi — bet kembali ke Rp%d", STARTING_BET)
    reset_seed()
    return STARTING_BET

# ─── Main bot loop ────────────────────────────────────────────────────────────
def run_bot():
    log.info("=" * 60)
    log.info("  Stake Keno Bot")
    log.info("  Currency     : %s", CURRENCY.upper())
    log.info("  Selections   : %s", KENO_SELECTIONS)
    log.info("  Start bet    : Rp%d", STARTING_BET)
    log.info("  Reset thresh : Rp%d", RESET_THRESHOLD)
    log.info("  Jeda profit  : Rp%s → %d menit", f"{PAUSE_PROFIT:,}", PAUSE_PROFIT_SECS // 60)
    log.info("  Jeda loss    : Rp%s → %d menit", f"{PAUSE_LOSS:,}", PAUSE_LOSS_SECS // 60)
    log.info("  Jeda spin    : setiap %d spin → %d menit", PAUSE_SPIN_EVERY, PAUSE_SPIN_SECS // 60)
    log.info("=" * 60)

    reset_seed()

    current_bet  = STARTING_BET

    # Statistik sesi (reset tiap jeda profit/loss)
    ses_profit   = 0.0
    ses_wins     = 0
    ses_losses   = 0

    # Statistik global
    total_wager  = 0.0
    total_wins   = 0
    total_losses = 0
    total_rounds = 0

    # FIX #4: Tampilkan ses_wins & ses_losses sesi, bukan hanya total global
    def stats_line() -> str:
        p = ses_profit
        profit_str = f"+Rp{p:,.0f}" if p >= 0 else f"-Rp{abs(p):,.0f}"
        return (
            f"Wager : Rp{total_wager:,.0f}  |  "
            f"Profit : {profit_str}  |  "
            f"Sesi W/L : {ses_wins}/{ses_losses}  |  "
            f"Total W/L : {total_wins}/{total_losses}"
        )

    # FIX #2: Lacak apakah STARTING_BET sudah pernah gagal agar tidak infinite loop
    _too_small_fallback_used = False

    while MAX_SPINS == 0 or total_rounds < MAX_SPINS:
        total_rounds += 1

        # ── Guard: bet terlalu kecil akibat win streak ────────────────────
        if current_bet < MIN_BET - 1e-6:
            log.warning("⚠️  Bet Rp%.2f di bawah minimum — reset ke Rp%d",
                        current_bet, STARTING_BET)
            current_bet = STARTING_BET
            _too_small_fallback_used = False

        bet_amount = int(round(current_bet))

        log.info("Spin #%d | Bet: Rp%d", total_rounds, bet_amount)

        # ── Pasang bet ────────────────────────────────────────────────────
        try:
            result = place_bet(bet_amount)
            # Reset flag fallback setelah bet berhasil
            _too_small_fallback_used = False
        except BetTooSmallError:
            # FIX #2: Proteksi infinite loop BetTooSmallError
            if not _too_small_fallback_used:
                log.warning(
                    "⚠️  Amount too small (Rp%d) — reset ke STARTING_BET Rp%d",
                    bet_amount, STARTING_BET,
                )
                current_bet = STARTING_BET
                _too_small_fallback_used = True
                continue
            else:
                # STARTING_BET pun ditolak — coba MIN_BET sebagai last resort
                if bet_amount != MIN_BET:
                    log.warning(
                        "⚠️  STARTING_BET Rp%d masih ditolak — coba MIN_BET Rp%d",
                        STARTING_BET, MIN_BET,
                    )
                    current_bet = MIN_BET
                    continue
                else:
                    log.error(
                        "❌ MIN_BET Rp%d juga ditolak oleh Stake. "
                        "Bot dihentikan untuk mencegah infinite loop.",
                        MIN_BET,
                    )
                    sys.exit(1)
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

        # FIX #5: Cek reset threshold SETELAH bet ditempatkan
        # → ronde berikutnya langsung dimulai dari STARTING_BET jika terlewati
        if bet_amount > RESET_THRESHOLD + 1e-6:
            log.info(
                "↩  Bet Rp%d > threshold Rp%d — ronde berikutnya reset ke Rp%d & rotasi seed",
                bet_amount, RESET_THRESHOLD, STARTING_BET,
            )
            current_bet = STARTING_BET
            reset_seed()
            _too_small_fallback_used = False

        # ── Jeda setiap N spin ────────────────────────────────────────────
        if total_rounds % PAUSE_SPIN_EVERY == 0:
            log.info("🔁 %d spin tercapai! | %s", total_rounds, stats_line())
            pause_countdown(PAUSE_SPIN_SECS, f"{total_rounds} Spin")
            current_bet = reset_session()
            ses_profit = 0.0; ses_wins = 0; ses_losses = 0
            _too_small_fallback_used = False
            continue

        # ── Jeda profit sesi ──────────────────────────────────────────────
        if ses_profit >= PAUSE_PROFIT:
            log.info("🎯 Profit sesi Rp%s tercapai! | %s",
                     f"{ses_profit:,.0f}", stats_line())
            pause_countdown(PAUSE_PROFIT_SECS,
                            f"Profit Rp{ses_profit:,.0f}")
            current_bet = reset_session()
            ses_profit = 0.0; ses_wins = 0; ses_losses = 0
            _too_small_fallback_used = False
            continue

        # ── Jeda stop loss sesi ───────────────────────────────────────────
        if ses_profit <= -PAUSE_LOSS:
            log.info("🛑 Stop loss sesi Rp%s! | %s",
                     f"{abs(ses_profit):,.0f}", stats_line())
            pause_countdown(PAUSE_LOSS_SECS,
                            f"Stop Loss Rp{abs(ses_profit):,.0f}")
            current_bet = reset_session()
            ses_profit = 0.0; ses_wins = 0; ses_losses = 0
            _too_small_fallback_used = False
            continue

        time.sleep(BET_DELAY)


if __name__ == "__main__":
    run_bot()
