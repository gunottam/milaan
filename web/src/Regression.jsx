// §11's multi-seed variance, rendered as a static ruled table.
//
// **Static on purpose.** Nothing here is fetched per run, nothing sorts, nothing
// expands. It is a precomputed artefact — `regression.json`, written offline at the
// node budget with no clock in the search — and the board's job is to put it beside
// the single seed on screen so a reader can see what that seed is a sample of.
//
// **The spread is a finding, not a caveat.** At stage 4 five seeds ran 4.5% to
// 11.9% on the ambiguity rate, so a mean alone would have described none of them.
// Every figure here carries ± σ and its range, and neither is behind a control.

import { pct } from './money'

const pm = (f, fmt = pct) =>
  (f?.mean === null || f?.mean === undefined ? '—' : `${fmt(f.mean)} ± ${fmt(f.sigma)}`)

const secs = (s) => (s === null || s === undefined ? '—' : `${s.toFixed(1)}s`)

// The four figures stage 14 reports. Precision is third because it is the one that
// must not move: a single false match anywhere is worth stopping for.
const SUMMARY_ROWS = [
  ['all-lines recall', 'all_lines_recall'],
  ['headline recall', 'headline_recall'],
  ['precision', 'all_lines_precision'],
  ['ambiguity rate', 'ambiguity_rate'],
]

export default function Regression({ data, lead }) {
  const { seeds, live = [], summary, harness } = data
  const clock = Object.fromEntries(live.map((r) => [r.seed, r]))
  const fp = summary.false_matches
  const exc = summary.excluded
  const breached = live.filter((r) => r.total_s > (harness.live?.ceiling_s ?? 60))
  // The ablated clock is a *comparison*, so it is only worth printing when there
  // is something to compare. From stage 15 the shipped configuration is Phase D
  // off, and then the two clocks are the same run — a sentence attributing their
  // difference to the model's round trips would be explaining a difference of zero.
  const ablated = summary.live_total_ablated_s
  const ablationMeasured = ablated?.mean != null
    && summary.live_total_s?.mean != null
    && ablated.mean !== summary.live_total_s.mean

  return (
    <section className={`regression${lead ? ' lead' : ''}`}>
      {/* With no run on screen this table *is* the board, so it carries the
          headline. §11: ten seeds at 100.0% is what makes one seed at 100.0%
          unarguable, and it should not have to wait behind a button press. */}
      {lead && (
        <div className="headline">
          <div className="headline-figure">
            <span className="eyebrow">precision</span>
            <span className="hero">{pct(summary.all_lines_precision.mean)}</span>
          </div>
          <div className="headline-under">
            <b>{fp.total} false matches</b> · {seeds.length} seeds ·{' '}
            {seeds.reduce((n, r) => n + r.bank_lines, 0).toLocaleString('en-IN')} bank lines
            <div className="headline-note">
              Measured offline at the node budget with no clock in the search, so two
              machines produce the same bytes. Press Run for a live seed.
            </div>
          </div>
        </div>
      )}
      <div className="col-head">
        <span className="eyebrow">Offline regression · {seeds.length} seeds</span>
        <span className="eyebrow">node budget only · no wall clock</span>
      </div>
      <p className="note">
        {/* en-US grouping, deliberately, against §2's Indian grouping for money:
            this is a node count, and the CLI table prints it as 40,000,000. Two
            renderings of one number must agree to the character. */}
        Uniqueness verified at {harness.offline.uniqueness_node_budget.toLocaleString('en-US')}{' '}
        nodes, deadline off, deterministic tiers only — so every figure in these
        columns is a property of the data and the budget rather than of this
        machine. The <span className="mono">live s</span> column is the other run:
        the demo budget with the deadline armed, timed and nothing else.
      </p>

      <table className="ledger reg">
        <thead>
          <tr>
            <th className="num">seed</th>
            <th className="num">lines</th>
            <th className="num">closed</th>
            <th className="num">all-lines</th>
            <th className="num">headline</th>
            <th className="num">precision</th>
            <th className="num">ambiguity</th>
            <th className="num">FP</th>
            <th className="num">live s</th>
            <th className="num">abl s</th>
          </tr>
        </thead>
        <tbody>
          {seeds.map((row, i) => (
            <tr key={row.seed} className={`row${i % 2 === 1 ? ' tint' : ''}`}>
              <td className="num eid">{row.seed}</td>
              <td className="num">{row.bank_lines}</td>
              <td className="num">{row.closed}</td>
              <td className="num">{pct(row.all_lines.recall)}</td>
              <td className="num">{pct(row.headline.recall)}</td>
              <td className="num">{pct(row.all_lines.precision)}</td>
              <td className="num">{pct(row.ambiguity.rate)}</td>
              {/* The only cell that changes colour. Zero is the claim; anything
                  else is the one result that stops a stage. */}
              <td className={`num${row.all_lines.counts.FP ? ' break' : ''}`}>
                {row.all_lines.counts.FP ?? 0}
              </td>
              <td className="num">{secs(clock[row.seed]?.total_s)}</td>
              {/* The same run with Phase D filtered out of the tier list. One
                  clock cannot say where a breach came from, and these two differ
                  by a network round trip per batch. */}
              <td className="num">{secs(clock[row.seed]?.total_ablated_s)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Single rule above the summary, double below — §13's mark for a closed
          sum. The ± figures are rows rather than columns because `100.0% ± 0.0%`
          does not fit under an 11-character heading, and squeezing it there is how
          the spread gets dropped from the number it belongs to. */}
      <table className="ledger reg summary">
        <tbody>
          {SUMMARY_ROWS.map(([label, key], i) => (
            <tr key={key} className="row">
              <td className="slabel">{i === 0 ? 'mean ± σ' : ''}</td>
              <td className="sname">{label}</td>
              <td className="num spread">{pm(summary[key])}</td>
              <td className="num range">
                range {pct(summary[key].min)} – {pct(summary[key].max)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="double-under" />

      <ul className="reg-claims">
        <li className={fp.clean_on_every_seed ? 'clean' : 'broken'}>
          <b>{fp.total} false matches across {seeds.length} seeds</b> —{' '}
          {fp.clean_on_every_seed
            ? 'precision reads 100.0% on every seed. A false match books a wrong '
              + 'figure silently and propagates to GST and revenue, so this is the '
              + 'figure that stops a stage rather than a figure that trends.'
            : `NOT CLEAN: ${Object.entries(fp.per_seed)
                .filter(([, n]) => n).map(([s, n]) => `seed ${s}: ${n} FP`).join(', ')}`}
        </li>
        {summary.live_total_s && (
          <li className={breached.length ? 'broken' : ''}>
            <b>live wall clock {pm(summary.live_total_s, secs)}</b>, range{' '}
            {secs(summary.live_total_s.min)}–{secs(summary.live_total_s.max)} against
            §15&apos;s {harness.live.ceiling_s}s ceiling
            {breached.length
              ? ` — BREACHED on ${breached.length} of ${live.length} seeds: `
                + breached.map((r) => `seed ${r.seed} at ${secs(r.total_s)}`).join(', ')
              : ', measured across every seed rather than asserted from one'}.
            {ablationMeasured ? (
              <>
                {' '}Ablated — Phase D filtered out of the tier list, same data and
                same deadline — {pm(ablated, secs)}, range{' '}
                {secs(ablated.min)}–{secs(ablated.max)}. The difference is the
                model&apos;s round trips, which is the one part of the run this
                machine does not own.
              </>
            ) : (
              <>
                {' '}Phase D is off, so the two clock columns are the same run: this
                is the configuration the board ships (<span className="mono">
                use_llm: false</span>). §15&apos;s 12s Phase D allocation is not
                enforceable — the run deadline is checked between tiers and cannot
                interrupt a batch in flight — and Phase D closed zero extra lines on
                every seed measured, so the budget it would enforce is one nothing
                wants to spend.
              </>
            )}
          </li>
        )}
        {exc && (
          <li className={exc.costs_no_recall_on_any_seed ? 'clean' : 'broken'}>
            <b>reversal-pair exclusion withheld{' '}
              {Object.values(exc.lines_per_seed).reduce((a, b) => a + b, 0)} lines
            </b>{' '}
            across {seeds.length} seeds — a line with a T+1 equal-and-opposite
            counterpart is a duplicate posting, not a payout, so no tier is offered
            either half (§3.2, §9.8).{' '}
            {exc.costs_no_recall_on_any_seed
              ? 'None of them was a line truth calls resolvable, so the rule cost '
                + 'zero recall. It can only ever cost recall: an exclusion removes '
                + 'candidates and never approves one.'
              : `COST RECALL: ${Object.entries(exc.withheld_resolvable_per_seed)
                  .filter(([, n]) => n).map(([sd, n]) => `seed ${sd}: ${n}`)
                  .join(', ')}`}
          </li>
        )}
        <li>
          Scored under {harness.scoring_rule}
        </li>
      </ul>
    </section>
  )
}
