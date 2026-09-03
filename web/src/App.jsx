// The shell: controls, the summary header, and the poll loop. §12, §13.
//
// **Polling at 500 ms.** §12 is explicit and it is a ruling rather than a
// limitation: the run is under 60 s, so an event stream buys nothing a poll does
// not and adds a reconnect path to debug in the demo room. `setInterval`, one
// fetch, done — there is no socket, no retry policy and no stream parser here
// because there is no stream.

import { useCallback, useEffect, useRef, useState } from 'react'
import Board from './Board'
import { fmtInr, pct } from './money'

const POLL_MS = 500

// §12's phase enum. The detective phases are listed because §12 lists them and are
// struck through until stage 12 builds it — a phase that silently vanished would
// make the ladder look shorter than the spec says it is.
const NOT_BUILT = new Set(['detective_a', 'detective_b'])

function Phases({ phases, current }) {
  const at = phases.indexOf(current)
  return (
    <div className="phases">
      {phases.map((p, i) => {
        const cls = NOT_BUILT.has(p) ? 'skipped' : i < at ? 'past' : i === at ? 'now' : ''
        return <span key={p} className={`phase ${cls}`}>{p}</span>
      })}
    </div>
  )
}

function Gap({ residue }) {
  // §13: the residue gap sits in the header — it is the global honesty indicator.
  // Three states. `?` is now a *narrow* state: the gap is non-zero but smaller than
  // what the deadline-cut lines could still absorb. It is no longer "the clock ran,
  // so who knows" — closing a line moves the gap by that line's own delta and
  // nothing else, and §8.2 caps that at ₹1.00, so an unfinished run has a bound.
  const [open, setOpen] = useState(false)
  const state = residue.reconciles === null ? 'unknown'
    : residue.reconciles ? 'reconciles' : 'broken'
  const mark = residue.reconciles === null ? '?' : residue.reconciles ? '✓' : '!'
  return (
    <>
      <button className={`gap ${state}`} onClick={() => setOpen(!open)}
               aria-expanded={open}>
        <span className="eyebrow">residue gap</span>
        <span>{fmtInr(residue.gap_paise)}</span>
        <span>{mark}</span>
        <span className="caret">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        // The composition, not just the mark. An indicator nobody can take apart
        // is a number people learn to ignore, and this one is the whole honesty
        // claim — so the sentences come from `audit.py`, which owns the identity.
        <pre className="gap-composition">{residue.composition.join('\n')}</pre>
      )}
    </>
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

function Summary({ run, report }) {
  const { residue, counts, ablation, buckets, headline_n: n } = report
  const det = ablation.deterministic_recall ?? 0
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
      <div className="summary-line">
        {/* Two nouns, never conflated: bank lines are counted here, transactions
            are counted separately, and the words say which is which. */}
        <span className="figure">{report.bank_lines} bank lines</span>
        <span className="label">·</span>
        <span className="figure">{report.transactions.toLocaleString('en-IN')} transactions</span>
        <span className="label">·</span>
        <span className="figure">{(report.elapsed_ms / 1000).toFixed(1)}s</span>
      </div>

      <div className="summary-line">
        <span className="figure">{report.closed} lines closed</span>
        <span className="figure">{counts.FP ?? 0} false</span>
        <span className="figure">{report.open} open</span>
        <span className="label">
          {report.transactions_tied.toLocaleString('en-IN')} transactions tied
        </span>
        <Gap residue={residue} />
      </div>

      <div className="summary-line">
        <span className="figure">exact {report.exact}</span>
        <span className="label">·</span>
        <span className="figure">tolerance {report.tolerance}</span>
        <span className="label">·</span>
        <span className="figure">via hypothesis {report.via_hypothesis}</span>
        <span className="label">·</span>
        {/* The denominator, in the label. Not implied, not a footnote. */}
        <span className="figure">precision {pct(report.precision)}</span>
        <span className="figure">recall {pct(report.recall)}</span>
        <span className="qualifier">(verified-unique, n={n})</span>
        <button className="more inline" onClick={() => setShowBuckets(!showBuckets)}>
          {showBuckets ? 'hide' : 'show'} all {buckets.length} scored buckets
        </button>
      </div>

      {showBuckets && <Buckets buckets={buckets} headlineN={n} />}

      <div className="summary-line ablation">
        <span className="label">deterministic {pct(det)}</span>
        <span className="track">
          <span className="det" style={{ width: `${det * 100}%` }} />
        </span>
        {/* §11's ablation delta is deterministic-vs-full and there is no full yet.
            Reporting the deterministic figure twice would render as a result and
            mean the opposite of one, so the second half says what is missing. */}
        <span className="label">
          {ablation.detective_available
            ? `${pct(ablation.full_recall)} with agent`
            : 'agent not built — ablation delta arrives at stage 12'}
        </span>
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

  async function start() {
    clearInterval(timer.current)
    setRun({ status: 'running', phase: 'generating', progress: 0, notes: [],
             phases: [], report: null })
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
            <div className="summary">
              <div className="summary-line">
                <span className="figure">{run.closed || 0} of {run.bank_lines || '—'} bank lines closed</span>
                <span className="label">{Math.round((run.progress || 0) * 100)}%</span>
              </div>
              <Phases phases={run.phases} current={run.phase} />
            </div>
          )}
          {run.report && <Summary run={run} report={run.report} />}
          {run.report && <Board report={run.report} />}
        </>
      )}

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
