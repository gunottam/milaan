// The two columns and what expands under them. §13.
//
// **Two nouns, never conflated.** Bank lines are *closed* or *open*. Transactions
// are *tied*. The header carries both counts and they are not the same number —
// 134 bank lines against 3,009 transactions — and every string in this file that
// names one of them names it correctly. This is not pedantry: a screen that says
// "99 of 134 reconciled" leaves a reader unable to tell whether 35 payouts or 35
// payments are unexplained, and those differ by two orders of magnitude in money.
//
// **The open column is not the leftovers.** It is half the argument — this closed,
// this did not, and the second is as much the product as the first — so it gets the
// wider half of the grid and is never behind a filter tab. A refusal a reader has
// to click a control to reach is a refusal they record as a miss.

import { Fragment, useState } from 'react'
import { fmtInr, fmtBare, fmtDate } from './money'

// The closed column's job is to make the arithmetic reachable, and it was doing
// the opposite: eight rows of whitespace beside an open column running three
// screens, with the strongest object on the board — the proof — behind a click
// nobody knew to make. Twenty rows fills the column, and the first strip renders
// open so the arithmetic is on screen before anybody touches anything.
const FIRST_SCREEN = 20

// §10.2's order, as a render order. The ledger already sorts its rows; this is the
// grouping the sort produces, named, so a reader can see *why* the list is in the
// order it is instead of scanning an unlabelled sequence of types and concluding it
// is arbitrary. Anything not listed falls to the end in ledger order.
const TYPE_ORDER = ['WITHHELD_RECORD', 'AMBIGUOUS_CONSEQUENTIAL',
                    'EXCEEDED_SEARCH_BUDGET', 'UNIQUENESS_UNPROVEN',
                    'ORPHAN_ORDER', 'SETTLEMENT_CONTAMINATION',
                    'DUPLICATE_CREDIT', 'AMBIGUOUS_EQUIVALENT']

// One line per type, because "WITHHELD_RECORD" is a token and a subhead is a place
// to say what it means. Kept short enough to sit on the same rule as the count.
const TYPE_GLOSS = {
  WITHHELD_RECORD: 'a source record is absent — the gap can be sized, not attributed',
  AMBIGUOUS_CONSEQUENTIAL: 'more than one composition balances and they book differently',
  EXCEEDED_SEARCH_BUDGET: 'the clock stopped the search — not a statement about the data',
  UNIQUENESS_UNPROVEN: 'a composition was found; the node budget could not prove it unique',
  ORPHAN_ORDER: 'an ERP order with no gateway record (§3.3)',
  SETTLEMENT_CONTAMINATION: 'the match spans settlements — confirm the tagging',
  DUPLICATE_CREDIT: 'a posting and its T+1 contra — the pair nets to zero',
  AMBIGUOUS_EQUIVALENT: 'the alternatives post identical figures — book either',
}

function groupByType(rows) {
  const seen = new Map()
  for (const exc of rows) {
    if (!seen.has(exc.exception_type)) seen.set(exc.exception_type, [])
    seen.get(exc.exception_type).push(exc)
  }
  return [...seen.entries()].sort(
    (a, b) => (TYPE_ORDER.indexOf(a[0]) + 1 || 99) - (TYPE_ORDER.indexOf(b[0]) + 1 || 99))
}

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

// The per-tier census, shown when provenance is on. §9.8's whole argument is that
// the ladder runs strongest-evidence-first, and this is the only place a reader can
// see that it did: 40 lines closed on a hard identifier before the search tiers ran
// at all. Scanning a column of two-character tier codes does not make that visible.
function TierStrip({ rows }) {
  const counts = rows.reduce((acc, r) => ({ ...acc, [r.tier]: (acc[r.tier] || 0) + 1 }), {})
  const tiers = Object.keys(counts).sort()
  return (
    <div className="tier-strip">
      {tiers.map((t) => (
        <span key={t} className="tier-cell">
          <span className={`tier-key t${t[0]}`}>{t}</span>
          <span className="tier-n">{counts[t]}</span>
        </span>
      ))}
    </div>
  )
}

function Closed({ rows, provenance, partial }) {
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
      {provenance && rows.length > 0 && <TierStrip rows={rows} />}
      {rows.length === 0 && <p className="empty">No bank line has been closed yet.</p>}
      <table className={`ledger${provenance ? ' provenance' : ''}`}>
        <tbody>
          {shown.map((row, i) => (
            <Row key={row.bank_line_id}
                 row={row} index={i} tint={i % 2 === 1}
                 provenance={provenance}
                 open={!partial && open === row.bank_line_id}
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
export function Row({ row, index, tint, open, onToggle, provenance }) {
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
        <td className={`tier${provenance ? ` keyed t${row.tier[0]}` : ''}`}>
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

function ExceptionRows({ rows, open, setOpen, risk }) {
  return (
    <table className={`ledger exceptions ${risk}`}>
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
                <td className="eid">{exc.bank_line_id ?? '—'}</td>
                <td className="exc-meta">
                  {/* A reversal pair is one finding across two bank lines. Naming
                      the partner on the row is what stops each half reading as an
                      unexplained credit on its own (§3.2). */}
                  {exc.reverses && <span className="partner">⇄ {exc.reverses}</span>}
                  <span className="conf">{exc.type_confidence}</span>
                  <span className="age">{exc.age_bucket}</span>
                </td>
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
  )
}

// One block per type, with the sort order made legible. Sticky, because the list
// runs past a screen and a reader scrolled halfway down it should never have to
// wonder which type they are looking at — the row itself carries an amount and a
// bank line id, and neither says whether this is money missing or a note to file.
function TypeGroup({ type, rows, risk, open, setOpen }) {
  const total = rows.reduce((n, e) => n + e.amount_at_risk_paise, 0)
  // Wrapped, and the wrapper is the point: a sticky element sticks within its
  // containing block, so all eight heads sharing one parent pinned at `top: 0`
  // simultaneously and stacked on each other over the rows they label. One block per
  // group means each head releases as its own last row scrolls past, which is what
  // "sticky subhead" means.
  return (
    <div className="type-group">
      <div className={`type-head ${risk}`}>
        <span className="type-name">{type}</span>
        <span className="type-n">{rows.length}</span>
        <span className="type-sum">{fmtInr(total)}</span>
        <span className="type-gloss">{TYPE_GLOSS[type] ?? ''}</span>
      </div>
      <ExceptionRows rows={rows} open={open} setOpen={setOpen} risk={risk} />
    </div>
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
// reason is one expand away is a refusal a reader records as a miss. The census is
// set as a *figure* rather than a clause in a sentence, and the two compositions the
// search reached are shown side by side underneath it — "279 balance" is a claim,
// and two columns differing by one transaction id is the evidence for it.
export function Refused({ rows }) {
  const pairs = Object.values(rows.reduce((acc, exc) => {
    const key = exc.settlement_id ?? exc.bank_line_id
    acc[key] = acc[key] ?? { settlement_id: exc.settlement_id, halves: [] }
    acc[key].halves.push(exc)
    return acc
  }, {}))
  return (
    <>
      <div className="sub-head refused-head-rule">
        <span className="eyebrow">
          Refused — the pair ties out, the division is not recorded
        </span>
        <span className="eyebrow">{rows.length} halves</span>
      </div>
      {pairs.map((pair) => (
        <Refusal key={pair.settlement_id ?? pair.halves[0].bank_line_id} pair={pair} />
      ))}
    </>
  )
}

// The census, as one number and its unit. `[[settlement_id, [divisions per
// payout]], ...]`, counted exactly by `count_exact` rather than stopped at the two
// that already make it a refusal — the difference between "the solver gave up" and
// "the source data does not contain the answer", and only one of those is true.
//
// **Three shapes, because three different things can be undetermined** (§10's
// `_sentence`), and one number cannot stand for all of them. The division count is
// the headline only when there is one settlement and one payout; with two payouts
// the undetermined thing is *which payout*, and `matcher/proposers/split_p.py`
// states outright that the counts are "grouped by settlement and never summed"
// because two payouts can share a division. Taking the max instead renders
// `[1, 1]` as **1 DIVISION BALANCE**, which reads as determined and is the exact
// opposite of the finding.
function census(entries) {
  if (!entries?.length) return null
  if (entries.length > 1) {
    return { n: entries.length, unit: ['settlements', 'tie'] }
  }
  const [, counts] = entries[0]
  if (counts.length === 1) {
    return { n: counts[0],
             unit: [`division${counts[0] === 1 ? '' : 's'}`, 'balance'] }
  }
  return { n: counts.length, unit: ['payouts', 'tie'] }
}

function Refusal({ pair }) {
  const lead = pair.halves[0]
  const figure = census(lead.census)
  const alts = lead.alternatives ?? []
  return (
    <div className="refused">
      <div className="refused-top">
        <span className="eid">{pair.settlement_id ?? '—'}</span>
        <span className="eid halves">
          {pair.halves.map((h) => h.bank_line_id).join(' + ')}
        </span>
        <span className="num">
          {pair.halves.map((h) => fmtInr(h.amount_at_risk_paise)).join(' + ')}
        </span>
      </div>

      <div className="refused-body">
        {/* The census at display size. It is the whole finding and it was reading
            as a clause in the middle of a sentence. */}
        {figure && (
          <div className="census">
            <span className="census-n">{figure.n.toLocaleString('en-IN')}</span>
            <span className="census-unit">
              {figure.unit[0]}<br />{figure.unit[1]}
            </span>
          </div>
        )}
        <div className="refused-text">
          <div className="refused-why">{lead.evidence[0]}</div>
          {/* Two of them, side by side. The claim is that the alternatives are real
              and the input does not choose between them; a reader who can see where
              the two lists actually diverge does not have to take that on trust —
              and on `setl_0048` they are not even the same length, 17 transactions
              against 16, both balancing to the paisa. Truncated at two because the
              census above is the count and this is the evidence that it is real.

              The separator is its own element so the rule under a differing id
              underlines the id and not the comma after it. */}
          {alts.length === 2 && (
            <div className="candidates">
              {alts.map((alt, i) => (
                <div className="candidate" key={i}>
                  <div className="candidate-head">
                    <span className="eyebrow">composition {i + 1}</span>
                    <span className="candidate-n">{alt.length} txns</span>
                  </div>
                  <div className="candidate-ids">
                    {alt.map((e, j) => (
                      <Fragment key={e}>
                        <span className={`tx${alts[1 - i].includes(e) ? '' : ' differs'}`}>
                          {e}
                        </span>
                        {j < alt.length - 1 && <span className="sep">, </span>}
                      </Fragment>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
          {/* Stated as a decision the system took, not as a note about what it
              could not do. §1: refusing here is the design working. */}
          <div className="refused-decision">
            <b>Refused.</b> {lead.blocked_on}
          </div>
        </div>
      </div>
    </div>
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

      {/* Triage, from `risk_class` — already stamped on every record by §10 so the
          CLI board, the API and this screen cannot disagree about which column a row
          belongs in. At-risk types get full ink and the break colour; documentation
          types get muted ink and a lighter weight. An AMBIGUOUS_EQUIVALENT at
          ₹46,943 is a thirty-second filing task and a WITHHELD_RECORD at ₹1,24,363
          is money nobody can account for, and they were rendering identically. */}
      {atRisk.length > 0 && (
        <div className="triage at-risk">
          <div className="triage-head">
            <span className="eyebrow">At risk — the books cannot account for this</span>
            <span className="eyebrow">{atRisk.length} items</span>
          </div>
          {groupByType(atRisk).map(([type, rows]) => (
            <TypeGroup key={type} type={type} rows={rows} risk="at-risk"
                       open={open} setOpen={setOpen} />
          ))}
        </div>
      )}

      {splits.length > 0 && <Refused rows={splits} />}

      {docRows.length > 0 && (
        <div className="triage documentation">
          <div className="triage-head">
            <span className="eyebrow">Needs documentation — accounted for, needs a note</span>
            <span className="eyebrow">{docRows.length} items</span>
          </div>
          {groupByType(docRows).map(([type, rows]) => (
            <TypeGroup key={type} type={type} rows={rows} risk="documentation"
                       open={open} setOpen={setOpen} />
          ))}
        </div>
      )}
      {ledger.exceptions.length === 0 && <p className="empty">Nothing open.</p>}
    </section>
  )
}

export default function Board({ report, provenance }) {
  return (
    <div className="columns">
      <Closed rows={report.closed_lines} provenance={provenance} />
      <Open report={report} />
    </div>
  )
}

// The board while the ladder is still working. Same closed column, same rows, same
// proof strips — the open column does not exist yet, because the exception ledger is
// Phase E and typing a line before the ladder has finished offering it every tier
// would name a break that has not happened.
export function PartialBoard({ rows, provenance }) {
  return (
    <div className="columns">
      <Closed rows={rows} provenance={provenance} partial />
      <section>
        <div className="col-head">
          <span className="eyebrow">Open items</span>
          <span className="eyebrow">Phase E</span>
        </div>
        <p className="empty">
          Nothing is typed until the ladder finishes. An exception names the missing
          input (§10), and a line still being offered tiers has not run out of them
          yet — so the column stays empty rather than filling with findings that
          would be withdrawn.
        </p>
      </section>
    </div>
  )
}
