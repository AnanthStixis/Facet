/**
 * Local YYYY-MM-DD for tomorrow — pass as the `min` on any "Closes on" date
 * input so the native picker greys out today and every earlier date. A
 * closing date is meaningless if it's already passed, and closing "today"
 * gives the cycle/campaign zero time to collect responses.
 */
export function minClosingDate(): string {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}