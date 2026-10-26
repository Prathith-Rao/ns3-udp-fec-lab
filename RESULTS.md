# Measured study results

Actual ns-3.45 Windows native runs; 10 independent runs per cell, 1,000 originals/run, 150 ms deadline, 50% adaptive parity budget. Intervals are pointwise run-level 95% Student-t intervals.

| Scenario | Method | Timely delivery (%) | Extra forward traffic (%) | App bytes / timely original |
|---|---|---:|---:|---:|
| steady | Plain UDP | 90.02 ± 0.73 | 0.00 ± 0.00 | 230.90 ± 1.87 |
| steady | Duplication | 99.07 ± 0.21 | 100.00 ± 0.00 | 416.71 ± 0.89 |
| steady | Fixed XOR (k=4) | 96.50 ± 0.59 | 25.00 ± 0.00 | 268.49 ± 1.66 |
| steady | Fixed interleaved XOR | 96.71 ± 0.63 | 25.00 ± 0.00 | 267.91 ± 1.75 |
| steady | Loss-only adaptive | 97.31 ± 0.35 | 41.52 ± 3.27 | 301.06 ± 7.22 |
| steady | Deadline-aware adaptive | 97.36 ± 0.38 | 42.50 ± 2.00 | 302.96 ± 4.22 |
| burst | Plain UDP | 89.76 ± 1.04 | 0.00 ± 0.00 | 231.59 ± 2.70 |
| burst | Duplication | 93.55 ± 0.74 | 100.00 ± 0.00 | 441.34 ± 3.50 |
| burst | Fixed XOR (k=4) | 91.17 ± 0.95 | 25.00 ± 0.00 | 284.23 ± 2.95 |
| burst | Fixed interleaved XOR | 92.90 ± 0.73 | 25.00 ± 0.00 | 278.91 ± 2.18 |
| burst | Loss-only adaptive | 91.71 ± 0.72 | 39.78 ± 3.05 | 315.64 ± 8.81 |
| burst | Deadline-aware adaptive | 93.36 ± 1.08 | 41.01 ± 2.50 | 312.77 ± 7.59 |
| changing | Plain UDP | 94.24 ± 0.63 | 0.00 ± 0.00 | 220.55 ± 1.48 |
| changing | Duplication | 98.05 ± 0.45 | 100.00 ± 0.00 | 421.06 ± 1.96 |
| changing | Fixed XOR (k=4) | 96.84 ± 0.41 | 25.00 ± 0.00 | 267.54 ± 1.14 |
| changing | Fixed interleaved XOR | 97.42 ± 0.37 | 25.00 ± 0.00 | 265.95 ± 1.01 |
| changing | Loss-only adaptive | 96.52 ± 0.39 | 22.65 ± 1.44 | 263.44 ± 3.50 |
| changing | Deadline-aware adaptive | 97.12 ± 0.44 | 24.09 ± 1.76 | 264.87 ± 4.53 |

The full controller improves average timely delivery over loss-only adaptation in burst and changing channels in this study. It does not dominate all fixed methods. In the changing channel, fixed interleaving has a higher mean timely-delivery rate (97.42%) than full adaptation (97.12%); full adaptation sends slightly less added forward traffic (24.09% versus 25%). These are observed means, not a statistical superiority claim.

Duplication has the highest mean timely delivery in each included scenario, but pays 100% extra forward traffic. The controller makes a recovery/traffic tradeoff and sometimes records that its 97% planning target is infeasible.

The eight-packet deterministic demo is a correctness illustration, not a performance estimate: ordinary k=4 loses two originals, whereas depth-2 interleaving reconstructs both by the 150 ms deadline.

See NOVELTY.md for the per-arrival burst model, feedback assumptions, cost definition and inference limitations.
