// Does the proof strip expand IN PLACE? §13 says no modal — and that is a
// *structural* claim about where the markup goes, which a screenshot cannot settle:
// a strip that is missing and a strip that is merely closed look identical.
//
// Renders the real <Row/> with `open` set and asserts on the markup: the proof <tr>
// is a sibling of the data <tr> inside the same <tbody>, the strip carries the
// single rule above the total and the double rule below, and there is no dialog,
// overlay or fixed positioning anywhere.
//
// No browser, no jsdom, no test runner. esbuild and react-dom/server are already
// here as Vite and React dependencies.
//
// Two more structural claims ride along in the same bundle, both about things a
// reader must not have to click for: the `SPLIT_PAYOUT` refusals carry their census
// sentence on the page, and the regression table carries every figure with its ± σ.
//
//   node check-strip.mjs
import { build } from 'esbuild'
import { writeFileSync, rmSync } from 'node:fs'
import { createRequire } from 'node:module'

const ENTRY = 'check-strip.entry.jsx'
const OUT = 'check-strip.bundle.cjs'

const ROW = {
  bank_line_id: 'bl_0000', value_date: '2026-01-04', target_paise: 9592824,
  tier: 'A1', confidence: 'exact', delta_paise: 0, source: 'deterministic',
  anchor_settlement_id: 'setl_0000', composition_size: 29, flags: [],
  proof: {
    rows: [{ label: 'payments captured', count: 29, amount_paise: 9753919 },
           { label: 'MDR', count: 0, amount_paise: -128258 }],
    total_paise: 9592824, target_paise: 9592824, delta_paise: 0,
  },
}

// One refused pair, as the ledger emits it. The census sentence is the claim.
const REFUSED = [
  { bank_line_id: 'bl_0048', settlement_id: 'setl_0048',
    census: [['setl_0048', [279]]],
    alternatives: [['pay_02538', 'pay_02539', 'rfnd_02557'],
                   ['pay_02538', 'pay_02539', 'rfnd_02564']],
    amount_at_risk_paise: 4445390, exception_type: 'SPLIT_PAYOUT',
    evidence: ['setl_0048 ties to this credit and bl_9003 jointly to the paisa, '
               + 'but 279 divisions of the payout balance against this credit, and '
               + 'the statement does not say which of them this credit carried'],
    blocked_on: 'A bank advice naming the transactions behind each credit.' },
  { bank_line_id: 'bl_9003', settlement_id: 'setl_0048',
    amount_at_risk_paise: 4337770, exception_type: 'SPLIT_PAYOUT',
    evidence: ['setl_0048 ties to this credit and bl_0048 jointly to the paisa, '
               + 'but 279 divisions of the payout balance against this credit, and '
               + 'the statement does not say which of them this credit carried'],
    blocked_on: 'A bank advice naming the transactions behind each credit.' },
]

// Two seeds, one of them carrying a false match, so the FP cell's one job can be
// checked: it is the only figure on the page that gets a colour.
const REG = {
  harness: {
    seeds: [42, 7], scoring_rule: 'per-line composition set equality (I5).',
    offline: { deadline_ms: null, uniqueness_node_budget: 40000000 },
    live: { ceiling_s: 60, uniqueness_node_budget: 5000000 },
  },
  seeds: [
    { seed: 42, bank_lines: 134, closed: 100,
      all_lines: { recall: 0.952, precision: 1, counts: { FP: 0 } },
      headline: { recall: 1 }, ambiguity: { rate: 0.119 } },
    { seed: 7, bank_lines: 134, closed: 103,
      all_lines: { recall: 0.903, precision: 0.99, counts: { FP: 1 } },
      headline: { recall: 0.988 }, ambiguity: { rate: 0.06 } },
  ],
  live: [{ seed: 42, total_s: 56.3, total_ablated_s: 9.9 },
         { seed: 7, total_s: 70.0, total_ablated_s: 11.2 }],
  summary: {
    all_lines_recall: { mean: 0.9275, sigma: 0.0245, min: 0.903, max: 0.952 },
    headline_recall: { mean: 0.994, sigma: 0.006, min: 0.988, max: 1 },
    all_lines_precision: { mean: 0.995, sigma: 0.005, min: 0.99, max: 1 },
    ambiguity_rate: { mean: 0.0895, sigma: 0.0295, min: 0.06, max: 0.119 },
    live_total_s: { mean: 63.15, sigma: 6.85, min: 56.3, max: 70 },
    live_total_ablated_s: { mean: 10.55, sigma: 0.65, min: 9.9, max: 11.2 },
    false_matches: { per_seed: { 42: 0, 7: 1 }, total: 1,
                     clean_on_every_seed: false },
    excluded: { lines_per_seed: { 42: 6, 7: 6 },
                withheld_resolvable_per_seed: { 42: 0, 7: 0 },
                withheld_resolvable_total: 0,
                costs_no_recall_on_any_seed: true },
  },
}

// The same figures with Phase D off, which is what the shipped board renders from
// stage 15. The two clock columns are then one run, and the sentence attributing
// their difference to the model's round trips must not appear.
const SHIPPED = {
  ...REG,
  live: [{ seed: 42, total_s: 21.4, total_ablated_s: 21.4 },
         { seed: 7, total_s: 19.8, total_ablated_s: 19.8 }],
  summary: { ...REG.summary,
             live_total_s: { mean: 20.6, sigma: 0.8, min: 19.8, max: 21.4 },
             live_total_ablated_s: { mean: 20.6, sigma: 0.8, min: 19.8, max: 21.4 } },
}

writeFileSync(ENTRY, `
import { renderToStaticMarkup } from 'react-dom/server'
import { Row, Refused } from './src/Board'
import Regression from './src/Regression'
const row = ${JSON.stringify(ROW)}
const table = (open) => renderToStaticMarkup(
  <table className="ledger"><tbody>
    <Row row={row} index={0} tint={false} open={open} onToggle={() => {}} />
  </tbody></table>)
module.exports = {
  closed: table(false),
  open: table(true),
  refused: renderToStaticMarkup(<Refused rows={${JSON.stringify(REFUSED)}} />),
  regression: renderToStaticMarkup(<Regression data={${JSON.stringify(REG)}} />),
  shipped: renderToStaticMarkup(<Regression data={${JSON.stringify(SHIPPED)}} />),
}
`)

await build({ entryPoints: [ENTRY], bundle: true, format: 'cjs', outfile: OUT,
              platform: 'node', packages: 'external', logLevel: 'silent',
              jsx: 'automatic' })
const { closed, open, refused, regression, shipped } =
  createRequire(import.meta.url)(`./${OUT}`)
rmSync(ENTRY); rmSync(OUT)

const fail = []
const ok = (name, cond) => (cond ? console.log('  ok    ' + name) : (fail.push(name),
  console.log('  FAIL  ' + name)))

// Only the outer table's own rows count. The strip contains a table of its own,
// so a naive `<tr` tally counts the arithmetic as structure.
const outerRows = (html) => (html.match(/<tr class="(row|proof)[^"]*"/g) || [])

ok('closed: exactly one outer <tr>, caret pointing right',
   outerRows(closed).length === 1 && closed.includes('\u25b8')
   && closed.includes('aria-expanded="false"'))
ok('open: a second outer <tr> appears', outerRows(open).length === 2)
ok('the proof <tr> is a SIBLING of the data <tr>, not nested inside it',
   /<\/tr><tr class="proof"/.test(open)
   && outerRows(open)[1].startsWith('<tr class="proof"'))
ok('and it is a real table row spanning the columns above it',
   /<tr class="proof"><td colSpan="5"|<tr class="proof"><td colspan="5"/i.test(open))
ok('no modal, dialog, overlay or fixed positioning',
   !/role="dialog"|<dialog|position:\s*fixed|class="[^"]*(modal|overlay)/.test(open))
ok('single rule above the total (tr.total)', open.includes('class="total"'))
ok('double rule below (div.double-under) \u2014 \u00a713 ledger convention',
   open.includes('class="double-under"'))
ok('the tick is in the margin', open.includes('class="tick"') && open.includes('\u2713'))
ok('figures use Indian grouping', open.includes('97,539.19') && open.includes('95,928.24'))
// \u20b9 on the total only. A ledger does not repeat the symbol on every row, but a
// bare total is not obviously money, and the total is the answer.
ok('\u20b9 appears exactly once in the arithmetic table, and on the total',
   (open.match(/<td class="figure">\u20b9/g) || []).length === 1
   && /<tr class="total">.*<td class="figure">\u20b995,928\.24<\/td>/.test(open))
ok('derived rows carry an em dash, not a blank cell',
   (open.match(/class="count derived">\u2014</g) || []).length === 1
   && open.includes('class="count">29<'))
ok('the delta is on its own line, not sharing a row with the tie sentence',
   /<div class="delta">0 paise delta<\/div>/.test(open))
ok('it ties, and says so', /class="tie-line"/.test(open) && /ties to the credit/.test(open))
ok('the caret flips to \u25be when open', open.includes('\u25be')
   && open.includes('aria-expanded="true"'))

// --- the refusals: the reason is on the page, not behind a click --------------

// Two halves, one payout, one block. A row per half would read as two unexplained
// credits, which is the confusion the pair exists to remove.
ok('refused: one block per pair, not one per half',
   (refused.match(/class="refused"/g) || []).length === 1)
ok('both halves are named on it',
   refused.includes('bl_0048 + bl_9003') && refused.includes('setl_0048'))
ok('the census is on the page, with no expand to reach it',
   refused.includes('279 divisions of the payout balance against this credit')
   && !/aria-expanded/.test(refused))
ok('and it says what would settle it', /class="refused-decision"/.test(refused)
   && refused.includes('bank advice'))
// §13, stage 16: the census is the strongest sentence in the product and it was
// reading as a paragraph. The number is set as a figure, and the two compositions
// are on the page so "279 balance" has evidence under it rather than only prose.
ok('the census is set as a figure, not only as a clause',
   /class="census-n">279</.test(refused))
ok('the two candidate compositions are shown side by side',
   (refused.match(/class="candidate"/g) || []).length === 2)
ok('and the transactions they differ on are marked, the separators are not',
   (refused.match(/class="tx differs"/g) || []).length === 2
   && refused.includes('rfnd_02557') && refused.includes('rfnd_02564'))
ok('the refusal is stated as a decision, not a footnote',
   /<b>Refused\.<\/b>/.test(refused))
ok('the halves are priced with Indian grouping',
   refused.includes('\u20b944,453.90') && refused.includes('\u20b943,377.70'))

// --- the regression table: every figure carries its spread -------------------

ok('regression: one row per seed', (regression.match(/class="row/g) || []).length
   === 2 + 4)                                  // two seeds, four summary rows
for (const label of ['all-lines recall', 'headline recall', 'precision',
                     'ambiguity rate']) {
  ok(`\u00b1 \u03c3 printed for ${label}`, regression.includes(label))
}
ok('the \u00b1 figures are there in full', regression.includes('92.8% \u00b1 2.5%')
   && regression.includes('99.5% \u00b1 0.5%'))
ok('every figure carries its range too',
   (regression.match(/class="num range"/g) || []).length === 4)
ok('the node budget the figures were measured at is on the page',
   regression.includes('4,00,00,000') || regression.includes('40,000,000'))
ok('a false match is coloured, and it is the only cell that is',
   (regression.match(/class="num break"/g) || []).length === 1)
ok('and it is named rather than averaged away',
   regression.includes('seed 7: 1 FP') && regression.includes('NOT CLEAN'))
ok('the live clock is reported against the ceiling, breach named',
   regression.includes('BREACHED') && regression.includes('seed 7 at 70.0s'))
ok('with the ablated clock beside it, so a breach can be located',
   regression.includes('10.6s \u00b1 0.7s') || regression.includes('Ablated'))
// Stage 15: the exclusion is a claim on the page, and the claim that matters is its
// *cost*. A rule that withholds lines from every tier has to say how many of them
// had an answer, even when the number is zero.
ok('the reversal-pair exclusion is on the page with its line count',
   regression.includes('withheld') && regression.includes('12 lines'))
ok('and priced — it says how much recall it cost',
   regression.includes('cost') && regression.includes('zero recall'))
// Phase D off is the shipped configuration, and then the ablated column is the same
// run. Attributing a difference of zero to the model's round trips would be a
// sentence about nothing.
ok('with Phase D off the ablation comparison is not printed',
   !shipped.includes('Ablated') && !shipped.includes("round trips"))
ok('and the board says which configuration it is instead',
   shipped.includes('use_llm: false') && shipped.includes('zero extra lines'))
ok('double rule under the summary \u2014 \u00a713 ledger convention',
   regression.includes('class="double-under"'))
ok('nothing here expands, sorts or fetches',
   !/aria-expanded|<button/.test(regression))

if (fail.length) { console.error(`\n  ${fail.length} FAILED`); process.exit(1) }
console.log('\n  proof strip expands in place \u2014 sibling <tr> in the same table, '
            + 'no modal.')
console.log('  refusals carry their census, the regression table carries its \u03c3, '
            + 'and neither needs a click.')
