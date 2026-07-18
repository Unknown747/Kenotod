"""
test_bot.py — Simulasi Keno Bot (Tanpa API, Saldo Bohongan)
============================================================
Semua logika identik dengan bot.py:
  • Strategi taruhan (WIN ×0.78 / LOSE ×1.25)
  • Reset threshold
  • Jeda otomatis (profit / stop-loss / spin)

Perbedaan:
  • Tidak ada koneksi ke Stake — bet disimulasikan secara lokal
  • Saldo awal bisa diatur (default Rp500.000)
  • Jeda dipersingkat: 1 menit → 3 detik, 5 menit → 5 detik
  • Jumlah spin bisa diatur (default 50)
"""

import random
import time
import logging
import sys
from math import comb

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("keno-test")

# ─── Konfigurasi (sama persis dengan bot.py) ─────────────────────────────────
IDR_PER_USD     = 16_000
KENO_SELECTIONS = [12, 13, 19, 20, 21, 22, 27, 28, 29, 30]   # 10 spot

STARTING_BET    = 160   / IDR_PER_USD
RESET_THRESHOLD = 160   / IDR_PER_USD
WIN_MULTIPLIER  = 0.78
LOSE_MULTIPLIER = 1.25
MIN_BET         = 0.0001

PAUSE_PROFIT_IDR  = 5_000
PAUSE_LOSS_IDR    = 32_000
PAUSE_SPIN_EVERY  = 1_000
PAUSE_PROFIT_USD  = PAUSE_PROFIT_IDR / IDR_PER_USD
PAUSE_LOSS_USD    = PAUSE_LOSS_IDR   / IDR_PER_USD

# ─── Pengaturan khusus TEST ───────────────────────────────────────────────────
SALDO_AWAL_IDR  = 500_000              # Rp500.000 saldo bohongan
TOTAL_SPIN_TEST = 50                   # Jumlah spin simulasi
PAUSE_SIM_SECS  = 3                    # Semua jeda diperpendek jadi 3 detik

# ─── Tabel payout Keno 10-spot, Risk: HIGH (Stake) ───────────────────────────
# Sesuai screenshot: 10 angka dipilih, difficulty high
# matches → multiplier (berapa kali lipat dari bet)
KENO_PAYOUT = {
    0:  0.0,
    1:  0.0,
    2:  0.0,
    3:  1.6,
    4:  2.0,
    5:  4.0,
    6:  7.0,
    7:  26.0,
    8:  100.0,
    9:  500.0,
    10: 1000.0,
}
KENO_RISK = "high"

# ─── Simulasi Keno draw ───────────────────────────────────────────────────────

def simulate_keno(picks: list[int]) -> dict:
    """
    Simulasi satu ronde Keno:
    - Undian 20 angka dari 1–40 secara acak
    - Hitung berapa picks yang cocok
    - Return payout multiplier & angka yang keluar
    """
    drawn   = random.sample(range(1, 41), 20)
    matches = sum(1 for p in picks if p in drawn)
    mult    = KENO_PAYOUT.get(matches, 0.0)
    return {
        "drawn":    sorted(drawn),
        "matches":  matches,
        "mult":     mult,
    }


def sim_bet(amount_usd: float, balance_usd: float) -> dict:
    """
    Tempatkan satu bet simulasi.
    Return: { amount, payout, profit, balance, drawn, matches, mult }
    """
    amount_usd = max(round(amount_usd, 8), MIN_BET)
    keno       = simulate_keno(KENO_SELECTIONS)
    payout     = round(amount_usd * keno["mult"], 8)
    profit     = round(payout - amount_usd, 8)
    new_bal    = balance_usd - amount_usd + payout
    return {
        "amount":  amount_usd,
        "payout":  payout,
        "profit":  profit,
        "balance": new_bal,
        "drawn":   keno["drawn"],
        "matches": keno["matches"],
        "mult":    keno["mult"],
    }


# ─── Fungsi bantu ─────────────────────────────────────────────────────────────

def pause_sim(label: str):
    log.info("⏸  %s — [TEST] Jeda %d detik (asli: beberapa menit)…", label, PAUSE_SIM_SECS)
    time.sleep(PAUSE_SIM_SECS)
    log.info("▶  Jeda selesai — melanjutkan…")


def reset_session_sim():
    log.info("🔄 Reset sesi — bet kembali ke Rp%.0f", STARTING_BET * IDR_PER_USD)
    return STARTING_BET


# ─── Main simulasi ────────────────────────────────────────────────────────────

def run_test():
    balance_usd = SALDO_AWAL_IDR / IDR_PER_USD

    log.info("=" * 65)
    log.info("  [TEST MODE] Stake Keno Bot — Simulasi Tanpa API")
    log.info("  Saldo awal   : Rp%s  ($%.2f)", f"{SALDO_AWAL_IDR:,}", balance_usd)
    log.info("  Picks        : %s", KENO_SELECTIONS)
    log.info("  Difficulty   : %s", KENO_RISK.upper())
    log.info("  Start bet    : Rp%.0f", STARTING_BET * IDR_PER_USD)
    log.info("  Reset thresh : Rp%.0f", RESET_THRESHOLD * IDR_PER_USD)
    log.info("  Jeda profit  : Rp%s  → %d dtk (sim)", f"{PAUSE_PROFIT_IDR:,}", PAUSE_SIM_SECS)
    log.info("  Jeda loss    : Rp%s → %d dtk (sim)", f"{PAUSE_LOSS_IDR:,}", PAUSE_SIM_SECS)
    log.info("  Jeda spin    : setiap %d spin → %d dtk (sim)", PAUSE_SPIN_EVERY, PAUSE_SIM_SECS)
    log.info("  Total spin   : %d", TOTAL_SPIN_TEST)
    log.info("=" * 65)

    current_bet   = STARTING_BET

    ses_profit    = 0.0
    ses_wins      = 0
    ses_losses    = 0

    total_wager   = 0.0
    total_wins    = 0
    total_losses  = 0
    total_rounds  = 0

    def stats_line() -> str:
        profit_idr = ses_profit * IDR_PER_USD
        wager_idr  = total_wager * IDR_PER_USD
        profit_str = f"+{profit_idr:,.0f}" if profit_idr >= 0 else f"{profit_idr:,.0f}"
        return (
            f"Wager : Rp{wager_idr:,.0f}  |  "
            f"Profit : {profit_str}  |  "
            f"W/L : {total_wins}/{total_losses}"
        )

    while total_rounds < TOTAL_SPIN_TEST:
        total_rounds += 1

        # ── Reset bet jika di atas threshold ─────────────────────────────
        if current_bet > RESET_THRESHOLD + 1e-9:
            log.info("↩  Reset bet ke Rp%.0f (threshold terlampaui)", STARTING_BET * IDR_PER_USD)
            current_bet = STARTING_BET

        bet_amount = max(round(current_bet, 8), MIN_BET)

        # ── Simulasi bet ─────────────────────────────────────────────────
        if balance_usd < bet_amount:
            log.warning("💸 Saldo tidak cukup! Saldo: Rp%.0f | Bet: Rp%.0f",
                        balance_usd * IDR_PER_USD, bet_amount * IDR_PER_USD)
            break

        result = sim_bet(bet_amount, balance_usd)
        balance_usd = result["balance"]

        ses_profit   += result["profit"]
        total_wager  += result["amount"]
        won           = result["profit"] > 0

        if won:
            ses_wins    += 1
            total_wins  += 1
            current_bet  = current_bet * WIN_MULTIPLIER
        else:
            ses_losses  += 1
            total_losses += 1
            current_bet  = current_bet * LOSE_MULTIPLIER

        outcome = "WIN 🟢" if won else "LOSE 🔴"
        log.info(
            "Spin #%d | Bet: Rp%.0f | %s | Match: %d/%d (×%.0f) | Saldo: Rp%s",
            total_rounds,
            bet_amount * IDR_PER_USD,
            outcome,
            result["matches"],
            len(KENO_SELECTIONS),
            result["mult"],
            f"{balance_usd * IDR_PER_USD:,.0f}",
        )
        log.info("         %s", stats_line())

        # ── Jeda setiap 1.000 spin ───────────────────────────────────────
        if total_rounds % PAUSE_SPIN_EVERY == 0:
            log.info("🔁 %d spin tercapai! | %s", total_rounds, stats_line())
            pause_sim(f"{total_rounds} Spin")
            current_bet = reset_session_sim()
            ses_profit  = 0.0; ses_wins = 0; ses_losses = 0
            continue

        # ── Jeda profit sesi ─────────────────────────────────────────────
        if ses_profit >= PAUSE_PROFIT_USD:
            log.info("🎯 Profit sesi Rp%.0f tercapai! | %s",
                     ses_profit * IDR_PER_USD, stats_line())
            pause_sim("Profit Rp{:,.0f}".format(ses_profit * IDR_PER_USD))
            current_bet = reset_session_sim()
            ses_profit  = 0.0; ses_wins = 0; ses_losses = 0
            continue

        # ── Jeda stop loss sesi ──────────────────────────────────────────
        if ses_profit <= -PAUSE_LOSS_USD:
            log.info("🛑 Stop loss sesi Rp%.0f! | %s",
                     abs(ses_profit) * IDR_PER_USD, stats_line())
            pause_sim("Stop Loss Rp{:,.0f}".format(abs(ses_profit) * IDR_PER_USD))
            current_bet = reset_session_sim()
            ses_profit  = 0.0; ses_wins = 0; ses_losses = 0
            continue

    # ── Ringkasan akhir ──────────────────────────────────────────────────────
    net_idr      = (balance_usd - SALDO_AWAL_IDR / IDR_PER_USD) * IDR_PER_USD
    net_str      = f"+{net_idr:,.0f}" if net_idr >= 0 else f"{net_idr:,.0f}"
    win_rate     = (total_wins / total_rounds * 100) if total_rounds else 0

    log.info("")
    log.info("=" * 65)
    log.info("  ✅ SIMULASI SELESAI — Ringkasan")
    log.info("  Total Spin    : %d", total_rounds)
    log.info("  W/L           : %d / %d  (Win rate: %.1f%%)", total_wins, total_losses, win_rate)
    log.info("  Total Wager   : Rp%s", f"{total_wager * IDR_PER_USD:,.0f}")
    log.info("  Saldo Awal    : Rp%s", f"{SALDO_AWAL_IDR:,}")
    log.info("  Saldo Akhir   : Rp%s", f"{balance_usd * IDR_PER_USD:,.0f}")
    log.info("  Net P/L       : %s", net_str)
    log.info("=" * 65)


if __name__ == "__main__":
    run_test()
