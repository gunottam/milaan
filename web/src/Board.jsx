// The two columns and what expands under them. §13.
//
// **Two nouns, never conflated.** Bank lines are *closed* or *open*. Transactions
// are *tied*. The header carries both counts and they are not the same number —
// 134 bank lines against 3,009 transactions — and every string in this file that
// names one of them names it correctly. This is not pedantry: a screen that says
// "99 of 134 reconciled" leaves a reader unable to tell whether 35 payouts or 35
// payments are unexplained, and those differ by two orders of magnitude in money.

import { Fragment, useState } from 'react'
import { fmtInr, fmtBare, fmtDate } from './money'

// A demo shows the first screenful and expands on demand. 99 ruled rows is a
// scroll, not a ledger — the closed column's job is to make the arithmetic
// reachable, and the count carries the completeness claim.
const FIRST_SCREEN = 8

// --- the proof strip -------------------------------------------------------

export function ProofStrip({ row }) {
  const { proof, tier, confidence, source, delta_paise, value_date } = row
  return (
    <div className="strip">
      <div className="strip-head">
        <span className="eid">{row.bank_line_id}</span>
        <span>
          {tier} · <span className={confidence === 'tolerance' ? 'tol' : ''}>{confidence}</span>
          {' · '}
          {/* §13: hypothesis-sourced matches carry the --hypo marker, so provenance
              is never ambiguous. `source` is stamped on the result, never on the
              Claim (I9). Nothing produces 'hypothesis' until stage 12. */}
          <span className={source === 'hypothesis' ? 'hypo' : ''}>{source}</span>
        </span>
      </div>

      <table>
        <tbody>
          {proof.rows.map((r, i) => (
            <tr key={i}>
              {/* The sign lives in the left margin and the figure is unsigned —
                  §13's sketch, and the reason the column reads as a column. */}
              <td className="sign">{r.amount_paise < 0 ? '−' : ''}</td>
              <td className="count">{r.count || ''}</td>
              <td className="desc">{r.label}</td>
              <td className="figure">{fmtBare(r.amount_paise)}</td>
            </tr>
          ))}
          {/* Single rule above the total. */}
          <tr className="total">
            <td /><td /><td />
            <td className="figure">{fmtBare(proof.total_paise)}</td>
          </tr>
        </tbody>
      </table>
      {/* Double rule below — the bookkeeping mark for a closed sum. */}
      <div className="double-under" />

      <div className={`ties${delta_paise ? ' off' : ''}`}>
        <span>
          {delta_paise === 0 ? '✓' : '~'} ties to the credit of {fmtDate(value_date)}
          {row.anchor_settlement_id ? ` · ${row.anchor_settlement_id}` : ''}
          {` · ${row.composition_size} transactions tied`}
        </span>
        <span>{delta_paise} paise delta</span>
      </div>

      {/* §9.4: an accepted match spanning settlements is flagged for human
          confirmation. It stays a match — G3 accepted the shape and G2 balanced
          it — so the flag sits under the proof rather than in place of it. Hiding
          it would let a mis-tagged transaction be absorbed silently, which is the
          shape SETTLEMENT_CONTAMINATION takes once it has been. */}
      {row.flags?.length > 0 && (
        <ul className="flags">
          {row.flags.map((f, i) => <li key={i}>{f}</li>)}
        </ul>
      )}
    </div>
  )
}

// --- CLOSED ----------------------------------------------------------------

function Closed({ rows }) {
  const [open, setOpen] = useState(null)
  const [all, setAll] = useState(false)
  const shown = all ? rows : rows.slice(0, FIRST_SCREEN)
  return (
    <section>
      <div className="col-head">
        <span className="eyebrow">Closed</span>
        <span className="eyebrow">{rows.length} bank lines</span>
      </div>
      {rows.length === 0 && <p className="empty">No bank line has been closed yet.</p>}
      <table className="ledger">
        <tbody>
          {shown.map((row, i) => (
            <Row key={row.bank_line_id}
                 row={row} index={i} tint={i % 2 === 1}
                 open={open === row.bank_line_id}
                 onToggle={() => setOpen(open === row.bank_line_id ? null : row.bank_line_id)} />
          ))}
        </tbody>
      </table>
      {rows.length > FIRST_SCREEN && (
        <button className="more" onClick={() => setAll(!all)}>
          {all
            ? `collapse to first ${FIRST_SCREEN}`
            : `show all ${rows.length} closed bank lines (${rows.length - FIRST_SCREEN} more)`}
        </button>
      )}
    </section>
  )
}

// Exported so `check-strip.mjs` can render it with `open` set and assert that
// the proof <tr> is a *sibling* of the data <tr> — §13's "expands in place, no
// modal" is a structural claim, and a screenshot cannot distinguish a strip
// that is missing from one that is merely closed.
export function Row({ row, index, tint, open, onToggle }) {
  return (
    <>
      {/* The greenbar tint comes from the row's index in the data, not from
          `nth-of-type`. A proof row inserted between two data rows shifts the CSS
          parity and re-bands the whole table underneath it; counting in JS keeps
          the banding still while a strip is open. */}
      <tr className={`row fresh${tint ? ' tint' : ''}${open ? ' expanded' : ''}`}
          style={{ animationDelay: `${Math.min(index, 24) * 40}ms` }}
          onClick={onToggle} tabIndex={0} role="button"
          aria-expanded={open}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onToggle()}>
        {/* The caret is the affordance. Without it the row is a clickable thing
            that does not look like one, and the proof strip is the whole point of
            the screen — nobody should have to guess it is there. */}
        <td className="caret">{open ? '▾' : '▸'}</td>
        <td className="tick">{row.delta_paise === 0 ? '✓' : '~'}</td>
        <td className="eid">{row.bank_line_id}</td>
        <td className="num amount">{fmtInr(row.target_paise)}</td>
        <td className="tier">
          {row.tier}
          {row.confidence === 'tolerance' && <span className="tol"> tol</span>}
          {row.flags?.length > 0 && <span className="flag-mark"> ⚑</span>}
          {row.source === 'hypothesis' && <span className="hypo-mark"> ◆</span>}
        </td>
      </tr>
      {open && (
        <tr className="proof">
          <td colSpan={5}><ProofStrip row={row} /></td>
        </tr>
      )}
    </>
  )
}

// --- OPEN ITEMS ------------------------------------------------------------

function ExceptionDetail({ exc }) {
  return (
    <div className="detail">
      {exc.delta_diagnosis && exc.delta_diagnosis !== 'not_applicable' && (
        <div className="diag">δ {exc.delta_diagnosis}
          {' · '}{exc.hypotheses_tried} hypotheses tried</div>
      )}
      <ul>{exc.evidence.map((token, i) => <li key={i}>{token}</li>)}</ul>
      {/* §10: `blocked_on` must name the missing input in one sentence. It is the
          line a human acts on, so it is the only one in ink rather than soft. */}
      <div className="blocked"><b>Blocked on:</b> {exc.blocked_on}</div>
      <div className="action">
        {exc.proposed_action.kind}: {exc.proposed_action.detail}
      </div>
    </div>
  )
}

function ExceptionRows({ rows, open, setOpen }) {
  return (
    <table className="ledger">
      <tbody>
        {rows.map((exc, i) => {
          const isOpen = open === exc.exception_id
          return (
            <Fragment key={exc.exception_id}>
              <tr className={`row${i % 2 === 1 ? ' tint' : ''}${isOpen ? ' expanded' : ''}`}
                  onClick={() => setOpen(isOpen ? null : exc.exception_id)}
                  tabIndex={0} role="button" aria-expanded={isOpen}
                  onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ')
                    && setOpen(isOpen ? null : exc.exception_id)}>
                <td className="caret">{isOpen ? '▾' : '▸'}</td>
                <td className="num amount">{fmtInr(exc.amount_at_risk_paise)}</td>
                <td className="exc-type">
                  {exc.exception_type}
                  {/* A reversal pair is one finding across two bank lines. Naming
                      the partner on the row is what stops each half reading as an
                      unexplained credit on its own (§3.2). */}
                  {exc.reverses && <span className="partner"> ⇄ {exc.reverses}</span>}
                </td>
                <td className="conf">{exc.type_confidence}</td>
                <td className="age">{exc.age_bucket}</td>
              </tr>
              {isOpen && (
                <tr className="proof">
                  <td colSpan={5}><ExceptionDetail exc={exc} /></td>
                </tr>
              )}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}

function Open({ report }) {
  const [open, setOpen] = useState(null)
  const { ledger, deadline } = report
  const atRisk = ledger.exceptions.filter((e) => e.risk_class === 'at_risk')
  const docs = ledger.exceptions.filter((e) => e.risk_class === 'documentation')
  const cut = deadline.cut.concat(deadline.exceeded)

  return (
    <section>
      <div className="col-head">
        <span className="eyebrow">Open items</span>
        <span className="eyebrow">{ledger.exceptions.length} items</span>
      </div>

      {/* Two totals, never one. A reversal pair and an `AMBIGUOUS_EQUIVALENT` are
          not money at risk — the first nets to zero, the second gives identical
          books whichever way it is booked — and summing them into the risk figure
          made it always larger and never actionable. */}
      <div className="risk-split">
        <div className="risk">
          <span className="eyebrow">At risk</span>
          <span className="amount">{fmtInr(ledger.at_risk_paise)}</span>
          <span className="note">{atRisk.length} items · the books cannot account for this</span>
        </div>
        <div className="risk docs">
          <span className="eyebrow">Needs documentation</span>
          <span className="amount">{fmtInr(ledger.documentation_paise)}</span>
          <span className="note">
            {docs.length} items · reconciled or bookkeeping-identical
            {ledger.nets_to_zero_paise
              ? ` · ${fmtInr(ledger.nets_to_zero_paise)} of it is a posting and its contra`
              : ''}
          </span>
        </div>
      </div>

      {/* §9.10's line-ID list lives here, not in the header. It is a property of
          this run's machine (§11) and a reader only wants it once they are already
          looking at what did not close. */}
      {cut.length > 0 && (
        <p className="cut-note">
          <b>EXCEEDED_SEARCH_BUDGET</b> — the deadline stopped {cut.length}{' '}
          {cut.length === 1 ? 'line' : 'lines'}: <span className="eid">{cut.join(', ')}</span>.
          They score as FN. Closing a line moves the residue gap only by its own
          delta, so these can account for at most{' '}
          {fmtInr(report.residue.deadline_slack_paise)} of it.
        </p>
      )}

      {atRisk.length > 0 && (
        <>
          <div className="sub-head"><span className="eyebrow">At risk</span></div>
          <ExceptionRows rows={atRisk} open={open} setOpen={setOpen} />
        </>
      )}
      {docs.length > 0 && (
        <>
          <div className="sub-head"><span className="eyebrow">Needs documentation</span></div>
          <ExceptionRows rows={docs} open={open} setOpen={setOpen} />
        </>
      )}
      {ledger.exceptions.length === 0 && <p className="empty">Nothing open.</p>}
    </section>
  )
}

export default function Board({ report }) {
  return (
    <div className="columns">
      <Closed rows={report.closed_lines} />
      <Open report={report} />
    </div>
  )
}
