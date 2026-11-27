# Baseline: mechanical flow rule vs ordinary days

Rule: ATM call+put volume z-score ≥ 2.0 (trailing 20 days) = flow day.
Universe: SPY, QQQ, NVDA, TSLA, MU; 2025-11-01 → 2026-11-25.
Entry: bull put spread, short 0.96×spot (grid), width capped to the $300 budget, 7+ day expiry, real EOD closes; expiry settle.

| bucket | n | win rate | mean R | median R | mean credit |
|---|---|---|---|---|---|
| flow days | 36 | 80.6% | +0.188 | +0.302 | 0.79 |
| ordinary days | 548 | 73.7% | +0.284 | +0.250 | 0.76 |

**Flow edge: -0.096 R** (flow mean R minus ordinary mean R)