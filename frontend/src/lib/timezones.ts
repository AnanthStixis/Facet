// Temporary kill switch — every timezone field in the app reads this instead
// of rendering its own picker. Flip back to true to bring editable timezone
// selection back everywhere at once; no need to hunt down each screen again.
export const TIMEZONE_FIELD_ENABLED = false

// `Intl.supportedValuesOf` covers every IANA zone the browser ships with; the
// short list below is only a fallback for browsers old enough to lack it.
// One shared list so registration, org profile editing, and anywhere else a
// timezone is picked all offer the same set — previously each page kept its
// own, and one of them was a short hand-picked subset while the other was
// the full IANA list, so the same field looked different depending on which
// screen you were on.
export const TIMEZONES: string[] =
  typeof Intl.supportedValuesOf === 'function'
    ? Intl.supportedValuesOf('timeZone')
    : [
        'UTC',
        'Asia/Kolkata',
        'Asia/Dubai',
        'Asia/Singapore',
        'Europe/London',
        'Europe/Berlin',
        'America/New_York',
        'America/Los_Angeles',
        'Australia/Sydney',
      ]
