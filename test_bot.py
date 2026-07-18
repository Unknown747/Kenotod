"""
test_bot.py — Simulasi Keno Bot (Tanpa API, Saldo Bohongan)
============================================================
Semua logika identik dengan bot.py — semua angka dalam IDR:
  • CURRENCY     : idr
  • Strategi bet : WIN ×0.78 / LOSE ×1.25
  • Reset threshold, jeda otomatis, MIN_BET reset

Perbedaan:
  • Tidak ada koneksi ke Stake — hasil disimulasikan lokal
  • Saldo awal bohongan (default Rp500.000)
  • Jeda dipersingkat → 3 detik
  • Jumlah spin bisa diatur (default 50)
"""

import random
import time
import logging

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("keno-test")

# ─── Konfigurasi (sama persis dengan bot.py, semua IDR) ──────────────────────
CURRENCY        = "idr"
KENO_SELECTIONS = [12, 13, 19, 20, 21, 22, 27, 28, 29, 30]   # 10 spot

STARTING_BET    = 160
RESET_THRESHOLD = 160
MIN_BET         = 100
WIN_MULTIPLIER  = 0.78
LOSE_MULTIPLIER = 1.25

PAUSE_PROFIT    = 5_000
PAUSE_LOSS      = 32_000
PAUSE_SPIN_EVERY = 1_000

# ─── Pengaturan TEST ──────────────────────────────────────────────────────────
SALDO_AWAL      = 500_000   # Rp500.000
TOTAL_SPIN_TEST = 50
PAUSE_SIM_SECS  = 3         # Jeda diperpendek untuk testing

# ─── Tabel payout Keno 10-spot, Risk: HIGH ───────────────────────────────────
# Sesuai screenshot — matches → multiplier
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

# ─── Simulasi draw Keno ───────────────────────────────────────────────────────
def simulate_keno(picks: list) -> dict:
    drawn   = random.sample(range(1, 41), 20)
    matches = sum(1 for p in picks if p in drawn)
    mult    = KENO_PAYOUT.get(matches, 0.0)
    return {"drawn": sorted(drawn), "matches": matches, "mult": mult}

def sim_bet(amount_idr: float, balance: float) -> dict:
    amount_idr = max(round(amount_idr, 2), MIN_BET)
    keno       = simulate_keno(KENO_SELECTIONS)
    payout     = round(amount_idr * keno["mult"], 2)
    profit     = round(payout - amount_idr, 2)
    return {
        "amount":  amount_idr,
        "payout":  payout,
        "profit":  profit,
        "balance": balance - amount_idr + payout,
        "matches": keno["matches"],
        "mult":    keno["mult"],
    }

# ─── Fungsi bantu ─────────────────────────────────────────────────────────────
def pause_sim(label: str):
    log.info("⏸  %s — [TEST] Jeda %d detik…", label, PAUSE_SIM_SECS)
    time.sleep(PAUSE_SIM_SECS)
    log.info("▶  Jeda selesai — melanjutkan…")

def reset_session_sim():
    log.info("🔄 Reset sesi — bet kembali ke Rp%d", STARTING_BET)
    return STARTING_BET

# ─── Main simulasi ────────────────────────────────────────────────────────────
def run_test():
    balance = float(SALDO_AWAL)

    log.info("=" * 65)
    log.info("  [TEST MODE] Stake Keno Bot — Simulasi Tanpa API")
    log.info("  Currency     : %s", CURRENCY.upper())
    log.info("  Saldo awal   : Rp%s", f"{SALDO_AWAL:,}")
    log.info("  Picks        : %s", KENO_SELECTIONS)
    log.info("  Difficulty   : HIGH")
    log.info("  Start bet    : Rp%d", STARTING_BET)
    log.info("  Reset thresh : Rp%d", RESET_THRESHOLD)
    log.info("  Min bet      : Rp%d", MIN_BET)
    log.info("  Jeda profit  : Rp%s → %d dtk (sim)", f"{PAUSE_PROFIT:,}", PAUSE_SIM_SECS)
    log.info("  Jeda loss    : Rp%s → %d dtk (sim)", f"{PAUSE_LOSS:,}", PAUSE_SIM_SECS)
    log.info("  Jeda spin    : setiap %d spin → %d dtk (sim)", PAUSE_SPIN_EVERY, PAUSE_SIM_SECS)
    log.info("  Total spin   : %d", TOTAL_SPIN_TEST)
    log.info("=" * 65)

    current_bet  = float(STARTING_BET)
    ses_profit   = 0.0
    ses_wins     = 0
    ses_losses   = 0
    total_wager  = 0.0
    total_wins   = 0
    total_losses = 0
    total_rounds = 0

    def stats_line() -> str:
        p = ses_profit
        profit_str = f"+Rp{p:,.0f}" if p >= 0 else f"-Rp{abs(p):,.0f}"
        return (
            f"Wager : Rp{total_wager:,.0f}  |  "
            f"Profit : {profit_str}  |  "
            f"W/L : {total_wins}/{total_losses}"
        )

    while total_rounds < TOTAL_SPIN_TEST:
        total_rounds += 1

        # ── Reset jika bet > threshold (akibat loss streak) ───────────────
        if current_bet > RESET_THRESHOLD + 1e-6:
            log.info("↩  Bet Rp%.0f > threshold — reset ke Rp%d",
                     current_bet, STARTING_BET)
            current_bet = STARTING_BET

        # ── Reset jika bet < minimum (akibat win streak) ──────────────────
        if current_bet < MIN_BET - 1e-6:
            log.warning("⚠️  Bet Rp%.2f di bawah minimum — reset ke Rp%d",
                        current_bet, STARTING_BET)
            current_bet = STARTING_BET

        bet_amount = round(current_bet, 2)

        if balance < bet_amount:
            log.warning("💸 Saldo tidak cukup! Saldo: Rp%s | Bet: Rp%d",
                        f"{balance:,.0f}", bet_amount)
            break

        result  = sim_bet(bet_amount, balance)
        balance = result["balance"]

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
            "Spin #%d | Bet: Rp%d | %s | Match: %d/%d (×%.0f) | Saldo: Rp%s",
            total_rounds,
            bet_amount,
            outcome,
            result["matches"],
            len(KENO_SELECTIONS),
            result["mult"],
            f"{balance:,.0f}",
        )
        log.info("         %s", stats_line())

        # ── Jeda setiap N spin ────────────────────────────────────────────
        if total_rounds % PAUSE_SPIN_EVERY == 0:
            log.info("🔁 %d spin | %s", total_rounds, stats_line())
            pause_sim(f"{total_rounds} Spin")
            current_bet = reset_session_sim()
            ses_profit = 0.0; ses_wins = 0; ses_losses = 0
            continue

        # ── Jeda profit sesi ──────────────────────────────────────────────
        if ses_profit >= PAUSE_PROFIT:
            log.info("🎯 Profit sesi Rp%s! | %s", f"{ses_profit:,.0f}", stats_line())
            pause_sim(f"Profit Rp{ses_profit:,.0f}")
            current_bet = reset_session_sim()
            ses_profit = 0.0; ses_wins = 0; ses_losses = 0
            continue

        # ── Jeda stop loss sesi ───────────────────────────────────────────
        if ses_profit <= -PAUSE_LOSS:
            log.info("🛑 Stop loss Rp%s! | %s", f"{abs(ses_profit):,.0f}", stats_line())
            pause_sim(f"Stop Loss Rp{abs(ses_profit):,.0f}")
            current_bet = reset_session_sim()
            ses_profit = 0.0; ses_wins = 0; ses_losses = 0
            continue

    # ── Ringkasan ─────────────────────────────────────────────────────────────
    net     = balance - SALDO_AWAL
    net_str = f"+Rp{net:,.0f}" if net >= 0 else f"-Rp{abs(net):,.0f}"
    wr      = (total_wins / total_rounds * 100) if total_rounds else 0

    log.info("")
    log.info("=" * 65)
    log.info("  ✅ SIMULASI SELESAI")
    log.info("  Total Spin  : %d", total_rounds)
    log.info("  W/L         : %d / %d  (Win rate: %.1f%%)", total_wins, total_losses, wr)
    log.info("  Total Wager : Rp%s", f"{total_wager:,.0f}")
    log.info("  Saldo Awal  : Rp%s", f"{SALDO_AWAL:,}")
    log.info("  Saldo Akhir : Rp%s", f"{balance:,.0f}")
    log.info("  Net P/L     : %s", net_str)
    log.info("=" * 65)


if __name__ == "__main__":
    run_test()
