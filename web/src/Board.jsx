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

// --- the proof strip -------------------------------------------------------

function ProofStrip({ row }) {
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
  return (
    <section>
      <div className="col-head">
        <span className="eyebrow">Closed</span>
        <span className="eyebrow">{rows.length} bank lines</span>
      </div>
      {rows.length === 0 && <p className="empty">No bank line has been closed yet.</p>}
      <table className="ledger">
        <tbody>
          {rows.map((row, i) => (
            // A fragment per row so the proof shares the row's key and the
            // alternating greenbar tint counts data rows, not expansions.
            <Row key={row.bank_line_id}
                 row={row} index={i}
                 open={open === row.bank_line_id}
                 onToggle={() => setOpen(open === row.bank_line_id ? null : row.bank_line_id)} />
          ))}
        </tbody>
      </table>
    </section>
  )
}

function Row({ row, index, open, onToggle }) {
  return (
    <>
      <tr className="row fresh" style={{ animationDelay: `${Math.min(index, 24) * 40}ms` }}
          onClick={onToggle}>
        <td className="tick">{row.delta_paise === 0 ? '✓' : '~'}</td>
        <td className="eid">{row.bank_line_id}</td>
        <td className="num amount">{fmtInr(row.target_paise)}</td>
        <td className="tier">
          {row.tier}
          {row.confidence === 'tolerance' && <span className="tol"> tol</span>}
          {row.source === 'hypothesis' && <span className="hypo-mark"> ◆</span>}
        </td>
      </tr>
      {open && (
        <tr className="proof">
          <td colSpan={4}><ProofStrip row={row} /></td>
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

function Open({ exceptions }) {
  const [open, setOpen] = useState(null)
  const total = exceptions.reduce((n, e) => n + e.amount_at_risk_paise, 0)
  return (
    <section>
      <div className="col-head">
        <span className="eyebrow">Open items</span>
        <span className="eyebrow">{fmtInr(total)} at risk</span>
      </div>
      {exceptions.length === 0 && <p className="empty">Nothing open.</p>}
      <table className="ledger">
        <tbody>
          {exceptions.map((exc) => {
            const isOpen = open === exc.exception_id
            return (
              <Fragment key={exc.exception_id}>
                <tr className="row" onClick={() => setOpen(isOpen ? null : exc.exception_id)}>
                  <td className="num amount">{fmtInr(exc.amount_at_risk_paise)}</td>
                  <td className="exc-type">{exc.exception_type}</td>
                  <td className="conf">{exc.type_confidence}</td>
                  <td className="age">{exc.age_bucket}</td>
                </tr>
                {isOpen && (
                  <tr className="proof">
                    <td colSpan={4}><ExceptionDetail exc={exc} /></td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}

export default function Board({ report }) {
  return (
    <div className="columns">
      <Closed rows={report.closed_lines} />
      <Open exceptions={report.ledger.exceptions} />
    </div>
  )
}
