# Stake Keno Bot

A Python bot that plays Keno on Stake.com using a defined betting strategy with automatic profit/loss stop conditions and client seed rotation.

## How to run

1. Set your `STAKE_API_KEY` secret in Replit Secrets (already prompted on first run).
2. Click **Run** — the workflow starts `bot.py` directly.

```
python bot.py
```

## Betting strategy

| Parameter       | IDR         | USD      |
|-----------------|-------------|----------|
| Starting bet    | Rp 160      | $0.01    |
| Target profit   | Rp 320      | $0.02    |
| Loss limit      | Rp 32,000   | $2.00    |
| Reset threshold | Rp 160      | $0.01    |

- **WIN** → next bet × 0.78 (reduce by 22%)
- **LOSE** → next bet × 1.25 (increase by 25%)
- **Reset rule**: if the current bet exceeds the reset threshold (Rp 160), it resets to the starting bet before the next round and a new client seed is generated.

## Seed rotation

`reset_seed()` generates a 32-character random alphanumeric string and pushes it to Stake via the `updateClientSeed` GraphQL mutation. It is triggered automatically:
- Whenever the bet amount exceeds the reset threshold.
- When the bot stops because the target profit was reached.

## Configuration

All tunable parameters are at the top of `bot.py`:

| Variable         | Default          | Description                              |
|------------------|------------------|------------------------------------------|
| `KENO_SELECTIONS`| `[3,7,14,22,36]` | Numbers to pick each round (1–40)        |
| `CURRENCY`       | `"usd"`          | Stake currency enum                      |
| `BET_DELAY`      | `1.0` s          | Sleep between bets                       |
| `WIN_MULTIPLIER` | `0.78`           | Bet scale on win                         |
| `LOSE_MULTIPLIER`| `1.25`           | Bet scale on loss                        |

## User preferences

- Language: Indonesian (user is Indonesian-speaking)
- Currency display: IDR with USD equivalent shown in logs
- Target platform: VPS, also runnable on Replit for testing
