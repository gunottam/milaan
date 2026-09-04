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

// The closed column's job is to make the arithmetic reachable, and it was doing
// the opposite: eight rows of whitespace beside an open column running three
// screens, with the strongest object on the board — the proof — behind a click
// nobody knew to make. Twenty rows fills the column, and the first strip renders
// open so the arithmetic is on screen before anybody touches anything.
const FIRST_SCREEN = 20

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
              {/* MDR, GST and TDS are derived from the transactions above them and
                  have no count of their own. A blank cell reads as missing data;
                  an em dash says "not applicable here", which is what it is. */}
              <td className={`count${r.count ? '' : ' derived'}`}>
                {r.count || '—'}
              </td>
              <td className="desc">{r.label}</td>
              {/* Line items are bare: a ledger does not repeat the symbol on every
                  row. The total carries it, because the total is the answer. */}
              <td className="figure">{fmtBare(r.amount_paise)}</td>
            </tr>
          ))}
          {/* Single rule above the total. */}
          <tr className="total">
            <td /><td /><td />
            <td className="figure">{fmtInr(proof.total_paise)}</td>
          </tr>
        </tbody>
      </table>
      {/* Double rule below — the bookkeeping mark for a closed sum. */}
      <div className="double-under" />

      {/* The delta gets its own line. It is the figure a reader checks hardest —
          the whole claim is that the arithmetic closes — and it was wrapping under
          the transaction count where it read as an afterthought. */}
      <div className={`ties${delta_paise ? ' off' : ''}`}>
        <div className="tie-line">
          {delta_paise === 0 ? '✓' : '~'} ties to the credit of {fmtDate(value_date)}
          {row.anchor_settlement_id ? ` · ${row.anchor_settlement_id}` : ''}
          {` · ${row.composition_size} transactions tied`}
        </div>
        <div className="delta">{delta_paise} paise delta</div>
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
  // The first row's strip is open on arrival. §11.1: in production the proof strip
  // is what a human verifies *instead of* precision, so it is the claim the board
  // is making — and a claim behind a click is a claim nobody sees.
  const [open, setOpen] = useState(rows[0]?.bank_line_id ?? null)
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

// The refusals, with the reason that makes each one a refusal. §13's board reports
// what closed; this reports what deliberately did not, and it is the stronger claim
// of the two — `setl_0048` ties out against both credits to the paisa and **279
// divisions of it balance against this one**, so any single answer is a false match
// with probability 278/279. A recall point bought by picking one would read better
// and mean less.
//
// Not behind a click, and not a row in the documentation table: a refusal whose
// reason is one expand away is a refusal a reader records as a miss.
export function Refused({ rows }) {
  const pairs = Object.values(rows.reduce((acc, exc) => {
    const key = exc.settlement_id ?? exc.bank_line_id
    acc[key] = acc[key] ?? { settlement_id: exc.settlement_id, halves: [] }
    acc[key].halves.push(exc)
    return acc
  }, {}))
  return (
    <>
      <div className="sub-head">
        <span className="eyebrow">
          Refused — the pair ties out, the division is not recorded
        </span>
        <span className="eyebrow">{rows.length} halves</span>
      </div>
      {pairs.map((pair) => (
        <div className="refused" key={pair.settlement_id ?? pair.halves[0].bank_line_id}>
          <div className="refused-head">
            <span className="eid">{pair.settlement_id ?? '—'}</span>
            <span className="eid halves">
              {pair.halves.map((h) => h.bank_line_id).join(' + ')}
            </span>
            <span className="num">
              {pair.halves.map((h) => fmtInr(h.amount_at_risk_paise)).join(' + ')}
            </span>
            <span className="conf">SPLIT_PAYOUT · documentation</span>
          </div>
          {/* The census sentence, straight off the ledger record. It names the
              settlement, the partner credit and how many sets of transactions
              balance — counted exactly by `count_exact`, not stopped at the two
              that already make it a refusal. */}
          <div className="refused-why">{pair.halves[0].evidence[0]}</div>
          <div className="blocked"><b>Blocked on:</b> {pair.halves[0].blocked_on}</div>
        </div>
      ))}
    </>
  )
}

function Open({ report }) {
  const [open, setOpen] = useState(null)
  const { ledger, deadline } = report
  const atRisk = ledger.exceptions.filter((e) => e.risk_class === 'at_risk')
  const docs = ledger.exceptions.filter((e) => e.risk_class === 'documentation')
  // SPLIT_PAYOUT leaves the table and gets its own block above it. It still counts
  // in the documentation total — the money is accounted for either way — but its
  // reason is the finding and a table cell cannot hold it.
  const splits = docs.filter((e) => e.exception_type === 'SPLIT_PAYOUT')
  const docRows = docs.filter((e) => e.exception_type !== 'SPLIT_PAYOUT')
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
      {splits.length > 0 && <Refused rows={splits} />}
      {docRows.length > 0 && (
        <>
          <div className="sub-head"><span className="eyebrow">Needs documentation</span></div>
          <ExceptionRows rows={docRows} open={open} setOpen={setOpen} />
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
