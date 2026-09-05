// The shell: controls, the summary header, and the poll loop. §12, §13.
//
// **Polling at 500 ms.** §12 is explicit and it is a ruling rather than a
// limitation: the run is under 60 s, so an event stream buys nothing a poll does
// not and adds a reconnect path to debug in the demo room. `setInterval`, one
// fetch, done — there is no socket, no retry policy and no stream parser here
// because there is no stream.
//
// **Hierarchy, and only one thing at the top of it.** Precision is what the whole
// architecture exists to produce: every gate but G4 can only cost recall, the
// uniqueness search refuses rather than guesses, and the exception ledger exists so
// a refusal is useful. Six statistics at equal weight said none of that. One figure
// at display size, with its denominator under it, and everything else demoted to
// supporting scale.

import { useCallback, useEffect, useRef, useState } from 'react'
import Board, { PartialBoard } from './Board'
import Regression from './Regression'
import { fmtInr, pct } from './money'

const POLL_MS = 500

// §12's phase enum, with what each one is for. The board narrates the run rather
// than showing a bar that interpolates: a judge watching 19 s of blank screen learns
// nothing, and a judge watching A close 79 lines on hard identifiers before C starts
// searching has just been shown §9.8's entire argument without being told it.
const PHASE_LABEL = {
  generating: 'generating the three files',
  verifying_uniqueness: 'proving each payout unique',
  phase_a: 'Phase A · identifier recovery',
  phase_b: 'Phase B · amount lookup',
  phase_c: 'Phase C · combinatorial search',
  detective_a: 'Phase D · narration',
  detective_b: 'Phase D · batched hypotheses',
  propagation_2: 'pass 2 · re-offering every open line',
  audit: 'Phase E · residue and coherence',
  scoring: 'scoring',
  done: 'done',
}

// Phase D is listed because §12 lists it, and struck through when it is not running
// — a phase that silently vanished would make the ladder look shorter than the spec
// says it is. From stage 15 the demo runs with it off by measurement, not omission.
const DETECTIVE = new Set(['detective_a', 'detective_b'])

function Phases({ phases, current, closed, useLlm }) {
  const at = phases.indexOf(current)
  return (
    <ol className="phase-run">
      {phases.filter((p) => p !== 'done').map((p, i) => {
        const off = DETECTIVE.has(p) && !useLlm
        const cls = off ? 'off' : i < at ? 'past' : i === at ? 'now' : 'ahead'
        return (
          <li key={p} className={`phase-step ${cls}`}>
            <span className="phase-mark">{i < at && !off ? '✓' : i === at ? '▸' : ''}</span>
            <span className="phase-name">{PHASE_LABEL[p] ?? p}</span>
            {/* The count, only where it is a fact. A phase that has not run has no
                count, and printing 0 there would read as "closed nothing". */}
            {i === at && closed > 0 && (
              <span className="phase-count">{closed} lines closed</span>
            )}
            {off && <span className="phase-count">off · use_llm false</span>}
          </li>
        )
      })}
    </ol>
  )
}

// --- the residue gap ---------------------------------------------------------

// §9.7's trial balance, and the one indicator on this page allowed to shout.
//
// **A ledger that looks the same reconciled and unreconciled has failed at its
// only job.** The two states are not two colours of the same component: zero is a
// single quiet line that a reader can skip, and non-zero is a ruled band across the
// full width with the word UNRECONCILED in it, which pushes everything below it down
// the page. The height change is the point — a reader who has seen the board once
// knows something is wrong before reading a single figure.
function Residue({ residue }) {
  const [open, setOpen] = useState(false)
  const state = residue.reconciles === null ? 'unknown'
    : residue.reconciles ? 'reconciles' : 'broken'

  if (state === 'reconciles') {
    return (
      <div className="residue reconciles">
        <span className="residue-mark">✓</span>
        <span className="residue-word">RECONCILED</span>
        <span className="residue-detail">
          §9.7's trial balance closes: every transaction is either tied to a bank
          line or accounted for as not yet due. Residue gap {fmtInr(residue.gap_paise)}.
        </span>
        <button className="residue-more" onClick={() => setOpen(!open)}
                aria-expanded={open}>{open ? 'hide' : 'show'} the sum</button>
        {open && <pre className="gap-composition">{residue.composition.join('\n')}</pre>}
      </div>
    )
  }

  return (
    <div className={`residue ${state}`}>
      <div className="residue-band">
        <span className="residue-word">
          {state === 'broken' ? 'UNRECONCILED' : 'UNRECONCILED — PARTIAL RUN'}
        </span>
        <span className="residue-figure">{fmtInr(residue.gap_paise)}</span>
        <button className="residue-more" onClick={() => setOpen(!open)}
                aria-expanded={open}>
          {open ? 'hide the sum' : 'show the sum'}
        </button>
      </div>
      <div className="residue-detail">
        §9.7's trial balance does not close. {fmtInr(residue.open_lines_paise)} sits
        on bank lines nothing composed, against {fmtInr(residue.unclaimed_due_paise)}
        {' '}of gateway transactions that are settled and unclaimed. The difference is
        money the books cannot yet account for, and it is reported rather than
        absorbed (I6).
      </div>
      {/* The composition, not just the mark. An indicator nobody can take apart is
          a number people learn to ignore, and this one is the whole honesty claim —
          so the sentences come from `audit.py`, which owns the identity. */}
      {open && <pre className="gap-composition">{residue.composition.join('\n')}</pre>}
    </div>
  )
}

// --- the headline ------------------------------------------------------------

// One figure at display size. Precision is the claim the architecture exists to
// support and it was sitting fourth in a row of six at equal weight.
//
// **The ten-seed figure, not this run's**, when the regression file is there: a
// single seed is one draw and the header should carry the number that is hard to
// argue with. When it is not there the run's own precision is shown with its own
// denominator, and the sub-line says so — a board that printed "10 seeds" off one
// run would be inventing nine.
function Headline({ report, regression }) {
  const seeds = regression?.seeds ?? []
  const fp = regression?.summary?.false_matches
  const tenSeed = seeds.length > 0 && fp
  const value = tenSeed
    ? regression.summary.all_lines_precision.mean
    : report.all_lines.precision
  const lines = seeds.reduce((n, s) => n + s.bank_lines, 0)
  return (
    <div className="headline">
      <div className="headline-figure">
        <span className="eyebrow">precision</span>
        <span className="hero">{pct(value)}</span>
      </div>
      <div className="headline-under">
        {tenSeed ? (
          <>
            <b>{fp.total} false matches</b> · {seeds.length} seeds ·{' '}
            {lines.toLocaleString('en-IN')} bank lines
            <div className="headline-note">
              Every composition is proved to the paisa before it is approved, and two
              that both balance are refused rather than picked between (§1). A false
              match books a wrong figure silently; a refusal costs a human a minute.
            </div>
          </>
        ) : (
          <>
            <b>{report.counts.FP ?? 0} false matches</b> · this run ·{' '}
            {report.all_lines.n} scored bank lines
            <div className="headline-note">
              One seed. Run <span className="mono">python -m scoring.regression</span>{' '}
              for the ten-seed spread.
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function Buckets({ buckets, headlineN }) {
  // §11's disclosed populations, rendered **beside** the headline rather than
  // implied by it. `recall 100.0%` next to `35 open` is not a contradiction — the
  // headline is verified-unique lines only, and at the live 20k budget 57 of 134
  // land in `unproven` instead — but a reader cannot know that from an unlabelled
  // percentage. Everything held out is named here with its own outcomes.
  const held = buckets.filter((b) => !b.in_headline)
  return (
    <table className="buckets">
      <tbody>
        {buckets.map((b) => (
          <tr key={b.name} className={b.in_headline ? 'in-headline' : ''}>
            <td className="bname">{b.name.replace(/_/g, ' ')}</td>
            <td className="num">{b.n}</td>
            <td className="bcounts">
              {['TP', 'FP', 'FN', 'TN'].filter((k) => b.counts[k])
                .map((k) => `${k} ${b.counts[k]}`).join('   ') || '—'}
            </td>
            <td className="blurb">{b.blurb}</td>
          </tr>
        ))}
        <tr className="bucket-total">
          <td className="bname">held out of the headline</td>
          <td className="num">{held.reduce((n, b) => n + b.n, 0)}</td>
          <td className="bcounts" />
          <td className="blurb">
            the headline denominator is {headlineN} of{' '}
            {buckets.reduce((n, b) => n + b.n, 0)} scored bank lines
          </td>
        </tr>
      </tbody>
    </table>
  )
}

// §11's ablation delta, as a finding rather than an absence.
//
// "agent not built" was true at stage 11 and is not true now: Phase D is built, it
// ran live against ten seeds, and it closed **zero** extra lines. That is a
// measurement — a negative result about an LLM's contribution to a problem that
// turns out to be determined by arithmetic — and it is more interesting than a
// positive one would have been. The control toggles tier provenance on the closed
// column, because "the deterministic tiers did all of this" is a claim a reader
// should be able to check line by line.
function Ablation({ report, regression, provenance, onToggle }) {
  const det = report.all_lines.recall ?? 0
  const measured = regression?.harness?.phase_d
  const delta = measured
    ? (measured.recall_delta === 0
        ? '+0.0 points'
        : measured.recall_delta != null
          ? `${measured.recall_delta > 0 ? '+' : ''}${(measured.recall_delta * 100).toFixed(1)} points`
          : `${measured.extra_lines_closed} extra lines`)
    : null
  return (
    <button className={`ablation${provenance ? ' on' : ''}`} onClick={onToggle}
            aria-expanded={provenance}>
      <span className="abl-key">deterministic</span>
      <span className="abl-figure">{pct(det)}</span>
      <span className="track">
        <span className="det" style={{ width: `${det * 100}%` }} />
      </span>
      {measured ? (
        <span className="abl-key">
          agent <b>{delta}</b> across {measured.seeds} seeds
        </span>
      ) : (
        <span className="abl-key">
          {report.ablation.detective_ran
            ? `${pct(report.ablation.full_recall)} with agent`
            : 'agent off this run'}
        </span>
      )}
      <span className="abl-toggle">
        {provenance ? '▾ hide tier provenance' : '▸ show which tier closed what'}
      </span>
    </button>
  )
}

function Summary({ run, report, regression, provenance, onToggleProvenance }) {
  const { residue, counts, buckets, headline_n: n } = report
  const [showBuckets, setShowBuckets] = useState(false)

  // Two banner lines, maximum. §9.10's line-ID list moved into the open column —
  // a header that lists twelve bank line ids is a header nobody reads.
  const banner = []
  if (report.deadline.hit) {
    const cut = report.deadline.cut.length
    const never = report.deadline.exceeded.length
    banner.push(
      `deadline reached at ${report.deadline.ms?.toLocaleString('en-IN')} ms — `
      + `${cut} lines cut mid-search, ${never} never attempted; `
      + `${report.deadline.passes_run} of ${report.deadline.passes_asked} `
      + `propagation passes run. Listed under OPEN ITEMS.`)
  }
  if (run.notes?.length) banner.push(run.notes[0])

  return (
    <div className="summary">
      <Residue residue={residue} />
      <Headline report={report} regression={regression} />

      {/* Supporting scale. Everything here was competing with the headline at equal
          weight; none of it is the claim, all of it is the context the claim needs
          to be checkable. */}
      <div className="support">
        <div className="support-line">
          {/* Two nouns, never conflated: bank lines are counted here, transactions
              are counted separately, and the words say which is which. */}
          <span className="figure">{report.bank_lines} bank lines</span>
          <span className="label">·</span>
          <span className="figure">{report.transactions.toLocaleString('en-IN')} transactions</span>
          <span className="label">·</span>
          <span className="figure">{report.closed} closed</span>
          <span className="label">·</span>
          <span className="figure">{report.open} open</span>
          <span className="label">·</span>
          <span className="figure">
            {report.transactions_tied.toLocaleString('en-IN')} transactions tied
          </span>
          <span className="label">·</span>
          <span className="figure">{(report.elapsed_ms / 1000).toFixed(1)}s</span>
        </div>

        <div className="support-line">
          <span className="figure">exact {report.exact}</span>
          <span className="label">·</span>
          <span className="figure">tolerance {report.tolerance}</span>
          <span className="label">·</span>
          <span className="figure">via hypothesis {report.via_hypothesis}</span>
          <span className="label">·</span>
          <span className="figure">this run's precision {pct(report.precision)}</span>
        </div>

        {/* **Both figures on one line.** `recall 100.0%` beside `35 open` is a
            contradiction from the reader's side, and the resolution — that the
            headline bucket is 65 of 134 lines — must not be something they go
            looking for. The complete number is the unarguable one, so it sits next
            to the narrow one and neither is printed alone. */}
        <div className="support-line recall-line">
          <span className="figure">recall {pct(report.recall)}</span>
          <span className="qualifier">over verified-unique (n={n})</span>
          <span className="label">·</span>
          <span className="qualifier">
            {report.all_lines.fn_held_out} FN in disclosed buckets
          </span>
          <span className="label">·</span>
          <span className="figure complete">
            all-lines recall {pct(report.all_lines.recall)}
          </span>
          <span className="qualifier">(n={report.all_lines.n})</span>
          <button className="more inline" onClick={() => setShowBuckets(!showBuckets)}>
            {showBuckets ? 'hide' : 'show'} all {buckets.length} scored buckets
          </button>
        </div>

        {showBuckets && <Buckets buckets={buckets} headlineN={n} />}

        <Ablation report={report} regression={regression}
                  provenance={provenance} onToggle={onToggleProvenance} />
      </div>

      {banner.length > 0 && (
        <ul className="notes">
          {banner.map((line, i) => <li key={i}>{line}</li>)}
        </ul>
      )}
    </div>
  )
}

export default function App() {
  const [form, setForm] = useState({ seed: 42, bank_lines: 120, records: 3000,
                                     noise: 'high', use_llm: false })
  const [run, setRun] = useState(null)
  const [provenance, setProvenance] = useState(false)
  // `regression.json`, fetched once. A static artefact, so there is no reload and
  // no poll: it is what the seed on screen is a sample of, and a 404 means the
  // harness has not been run rather than that something failed.
  const [regression, setRegression] = useState(null)
  const timer = useRef(null)

  const poll = useCallback(async (runId) => {
    const res = await fetch(`/api/runs/${runId}`)
    const state = await res.json()
    setRun(state)
    if (state.status !== 'running') {
      clearInterval(timer.current)
      timer.current = null
    }
  }, [])

  useEffect(() => () => clearInterval(timer.current), [])

  useEffect(() => {
    fetch('/api/regression')
      .then((res) => (res.ok ? res.json() : null))
      .then(setRegression)
      .catch(() => setRegression(null))
  }, [])

  async function start() {
    clearInterval(timer.current)
    setRun({ status: 'running', phase: 'generating', progress: 0, notes: [],
             phases: [], closed_rows: [], report: null })
    const res = await fetch('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form, seed: Number(form.seed),
                             bank_lines: Number(form.bank_lines),
                             records: Number(form.records) }),
    })
    const { run_id } = await res.json()
    poll(run_id)
    timer.current = setInterval(() => poll(run_id), POLL_MS)
  }

  const running = run?.status === 'running'
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  return (
    <div className="sheet">
      <div className="masthead">
        <span className="wordmark">MILAAN</span>
        <div className="controls">
          <span className="field">
            <label htmlFor="seed">seed</label>
            <input id="seed" value={form.seed} onChange={set('seed')} />
          </span>
          <span className="field">
            <label htmlFor="noise">noise</label>
            <select id="noise" value={form.noise} onChange={set('noise')}>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </span>
          <button className="run" onClick={start} disabled={running}>
            {running ? 'running' : 'Run'}
          </button>
        </div>
      </div>
      <div className="double-rule" />

      {run && (
        <>
          {run.status === 'error' && (
            <ul className="notes"><li>{run.error}</li></ul>
          )}
          {running && (
            <>
              <div className="summary running">
                <div className="run-head">
                  <span className="eyebrow">running</span>
                  <span className="run-count">
                    {run.closed || 0}
                    <span className="of"> of {run.bank_lines || '—'} bank lines closed</span>
                  </span>
                </div>
                <Phases phases={run.phases} current={run.phase}
                        closed={run.closed || 0} useLlm={form.use_llm} />
              </div>
              {/* Rows land as the ladder closes them, at §13's 40 ms stagger. The
                  alternative is 19 s of blank paper followed by everything at once,
                  which shows a judge the answer and none of the argument. */}
              {run.closed_rows?.length > 0 && (
                <PartialBoard rows={run.closed_rows} provenance={provenance} />
              )}
            </>
          )}
          {run.report && (
            <Summary run={run} report={run.report} regression={regression}
                     provenance={provenance}
                     onToggleProvenance={() => setProvenance(!provenance)} />
          )}
          {run.report && <Board report={run.report} provenance={provenance} />}
          {/* Below the board, always. The single seed on screen is one draw; the
              ten-seed spread is what says whether it was a lucky one. §11 keeps
              the two apart because only one of them has a clock in it. */}
          {regression && <Regression data={regression} />}
        </>
      )}

      {!run && regression && <Regression data={regression} lead />}

      {!run && (
        <p className="empty">
          Set a seed and press Run. Milaan generates a bank statement, a gateway
          ledger and an order list, then determines what composes every bank line
          and proves it to the paisa — or refuses and says what it is missing.
        </p>
      )}
    </div>
  )
}
