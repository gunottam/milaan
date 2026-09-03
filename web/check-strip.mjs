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

writeFileSync(ENTRY, `
import { renderToStaticMarkup } from 'react-dom/server'
import { Row } from './src/Board'
const row = ${JSON.stringify(ROW)}
const table = (open) => renderToStaticMarkup(
  <table className="ledger"><tbody>
    <Row row={row} index={0} tint={false} open={open} onToggle={() => {}} />
  </tbody></table>)
module.exports = { closed: table(false), open: table(true) }
`)

await build({ entryPoints: [ENTRY], bundle: true, format: 'cjs', outfile: OUT,
              platform: 'node', packages: 'external', logLevel: 'silent',
              jsx: 'automatic' })
const { closed, open } = createRequire(import.meta.url)(`./${OUT}`)
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

if (fail.length) { console.error(`\n  ${fail.length} FAILED`); process.exit(1) }
console.log('\n  proof strip expands in place \u2014 sibling <tr> in the same table, '
            + 'no modal.')
