# BEAM crossover — flat WRRF vs assembler at 500K and 1M (2026-06-11)

Overnight compute chain (Fix 1.2), clean bench DB, current code, 35
conversations per split. Raw stdout: 20260611-overnight-chain.log (also
contains the BEAM-10M temporal run: OVERALL 0.523 / R@10 59.3% / 196 Qs).

| split | config | MRR | R@5 | R@10 | Qs |
|---|---|---|---|---|---|
| 500K | plain WRRF | 0.500 | 59.6% | 63.7% | 699 |
| 500K | assembler  | **0.570** | 65.1% | 65.4% | 699 |
| 1M   | plain WRRF | 0.466 | 58.3% | 63.4% | 695 |
| 1M   | assembler  | **0.535** | 62.6% | 63.9% | 695 |

Flat WRRF degrades with scale (0.500 → 0.466); the assembler holds a durable
+0.07 MRR at both splits. Direction-consistent with the 10M result. Guard: do
NOT claim "better everywhere" — BEAM-100K-era data showed net-flat at small
scale; the assembler's value is scale-dependent.
