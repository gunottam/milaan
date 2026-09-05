# Board screenshots — stage 16

Chrome, **1280 × 720**, 2× device pixel ratio, seed 42 at the demo uniqueness
budget. Regenerate with the app running (`uvicorn api.main:app --port 8000` and
`npm run dev` in `web/`); these are evidence for the stage, not a build artefact,
so nothing checks them.

| | what it shows |
|---|---|
| `01-residue-UNRECONCILED.png` | §9.7 failing. Full-width band, break rules top and bottom, UNRECONCILED at 22 px, the figure at 26 px. |
| `02-residue-RECONCILED.png` | The same board reconciled. One quiet tally-green line, and the page sits ~170 px higher — the height change is the signal. |
| `03-landing-regression-leads.png` | No run in progress: ten seeds at 100.0% precision, all ten rows and the mean ± σ block above the fold. |
| `04-mid-run-phases-and-rows.png` | The ladder working. Phase checklist with per-phase counts, and 64 closed rows already landed. |
| `05-tier-provenance-on.png` | The ablation control toggled: `A1 40 │ A3 7 │ B1 13 │ B2 4 │ C1 28 │ C2 7 │ C3 1`. |
| `06-open-column-triage.png` | At-risk against documentation, grouped by type under sticky subheads. `AMBIGUOUS_EQUIVALENT` reads `low`, `ORPHAN_ORDER` carries its order id. |
| `07-refusal-census.png` | The census as a figure, with the two compositions the search reached side by side. |
| `08-proof-strip-1280x720.png` | The proof strip at 1:1 in the 445 px column. |
| `09-…-150pct-at-third-scale.png` | The strip at 150 % browser zoom, rasterised at 1/3 — the proxy for 4 m from a 2 m screen. Readable. |
| `10-…-100pct-at-third-scale.png` | The same proxy at 100 % zoom. Not readable. **Present at ≥150 %.** |

The reconciled state in `02` is produced by intercepting the run payload and
setting `residue.reconciles`; every other pixel is the real component tree on real
data. No seed in the harness reconciles — §9.7's gap is non-zero on all ten — so
the quiet state has no board of its own to be photographed on.
