# Baseline: mechanical flow rule vs ordinary days

Rule: ATM call+put volume z-score ≥ 2.0 (trailing 20 days) = flow day.
Universe: MU, NVDA, QQQ, SPY, TSLA; 2024-11-26 → 2026-11-13.
Per-ticker ranges: MU 2024-11-26→2026-11-03; NVDA 2024-11-26→2026-11-04; QQQ 2024-12-24→2026-11-13; SPY 2025-03-05→2026-11-02; TSLA 2024-11-26→2026-11-13.
Entry: bull put spread, short 0.96×spot (grid), width capped to the $300 budget, 7+ day expiry, real EOD closes; expiry settle.

| bucket | n | win rate | mean R | median R | mean credit |
|---|---|---|---|---|---|
| flow days | 79 | 78.5% | +0.162 | +0.316 | 0.71 |
| ordinary days | 1111 | 74.8% | +0.161 | +0.266 | 0.67 |

**Flow edge: +0.001 R** (flow mean R minus ordinary mean R)