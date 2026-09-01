// Formatting. §2, and it must agree with `core/money.py::fmt_inr` to the character.
//
// Indian digit grouping is mandatory — ₹4,61,938.80, never ₹461,938.80 — and
// `Intl.NumberFormat('en-IN')` does lakh/crore grouping natively. That is the whole
// implementation: a hand-rolled grouper would be a second thing to keep in step with
// the Python one, and the platform already has this.
//
// The sign sits *after* the rupee mark (`₹-4,500.00`), because that is where
// `fmt_inr` puts it and the CLI board and this screen are two renderings of one
// number. Two formatters disagreeing about a minus sign in a demo is a bad minute.

const GROUP = new Intl.NumberFormat('en-IN', { useGrouping: true })

/** Paise (integer) -> '₹4,61,938.80'. */
export function fmtInr(paise) {
  const sign = paise < 0 ? '-' : ''
  const abs = Math.abs(paise)
  const whole = Math.trunc(abs / 100)
  const frac = abs % 100
  return `₹${sign}${GROUP.format(whole)}.${String(frac).padStart(2, '0')}`
}

/** Paise -> '1,24,500.00'. The proof strip carries no rupee marks: the column is
 *  already money, and §13's sketch aligns bare figures on the decimal. */
export function fmtBare(paise) {
  const abs = Math.abs(paise)
  return `${GROUP.format(Math.trunc(abs / 100))}.${String(abs % 100).padStart(2, '0')}`
}

/** '2026-01-15' -> '15-Jan-2026'. Ledger date, not ISO. */
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export function fmtDate(iso) {
  if (!iso) return ''
  const [y, m, d] = iso.split('-')
  return `${d}-${MONTHS[Number(m) - 1]}-${y}`
}

export const pct = (x) => (x === null || x === undefined ? '—' : `${(x * 100).toFixed(1)}%`)
