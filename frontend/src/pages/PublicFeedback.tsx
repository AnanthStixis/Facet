import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { IconCheck, IconClock, IconLock } from '../components/icons'
import { Banner, Spinner } from '../components/ui'
import type { FeedbackForm, FormQuestion } from '../lib/cycleTypes'

interface PublicPayload {
  organization: { name: string; accent_color: string; logo_url: string | null }
  recipient: { full_name: string; company: string | null }
  subject: { label: string; type: string }
  campaign: { name: string; closes_at: string | null }
  is_anonymous: boolean
  form: FeedbackForm
}

type Answers = Record<string, number | string | boolean>

const BASE = '/api/v1/public'

/**
 * The respondent's page.
 *
 * Deliberately outside the application shell: no navigation, no sign-in
 * prompt, no product marketing. The person opening this is a client of the
 * tenant, not a user of ours — the page carries the tenant's mark and asks one
 * thing. Anything else added here costs completions.
 */
function ScaleRow({
  question,
  form,
  value,
  onChange,
  accent,
}: {
  question: FormQuestion
  form: FeedbackForm
  value: Answers[string] | undefined
  onChange: (value: Answers[string]) => void
  accent: string
}) {
  const points = Array.from(
    { length: form.scale.max - form.scale.min + 1 },
    (_, index) => form.scale.min + index,
  )

  return (
    <div className="border-t border-ink-200 py-5 first:border-t-0 first:pt-0 dark:border-ink-800">
      <p className="mb-3 text-base text-ink-800 dark:text-ink-100">
        {question.text}
        {question.required && <span className="ml-1 text-critical">*</span>}
      </p>

                        {question.type === 'scale' && (
        <div className="flex flex-wrap gap-2">
          {points.map((point) => {
            const active = value === point
            const label = form.scale.labels[String(point)]
            return (
              <button
                key={point}
                type="button"
                onClick={() => onChange(point)}
                aria-pressed={active}
                className={clsx(
                  'flex min-w-11 flex-col items-center gap-0.5 rounded-lg border px-2.5 py-2 transition-all',
                  active
                    ? 'border-transparent text-white shadow-sm'
                    : 'border-ink-200 text-ink-600 hover:border-ink-400 dark:border-ink-700 dark:text-ink-300',
                )}
                style={active ? { background: accent } : undefined}
              >
                <span className="text-base font-medium">{point}</span>
                {label && (
                  <span
                    className={clsx(
                      'max-w-16 truncate text-2xs leading-none',
                      active ? 'text-white/85' : 'text-ink-400',
                    )}
                  >
                    {label}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}

      {question.type === 'choice' && (
        <div className="flex flex-wrap gap-2">
          {question.options.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => onChange(option)}
              className={clsx(
                'rounded-lg border px-3.5 py-2 text-sm transition-all',
                value === option
                  ? 'border-transparent text-white'
                  : 'border-ink-200 text-ink-600 hover:border-ink-400 dark:border-ink-700 dark:text-ink-300',
              )}
              style={value === option ? { background: accent } : undefined}
            >
              {option}
            </button>
          ))}
        </div>
      )}

      {question.type === 'boolean' && (
        <div className="flex gap-2">
          {[true, false].map((option) => (
            <button
              key={String(option)}
              type="button"
              onClick={() => onChange(option)}
              className={clsx(
                'rounded-lg border px-5 py-2 text-sm transition-all',
                value === option
                  ? 'border-transparent text-white'
                  : 'border-ink-200 text-ink-600 hover:border-ink-400 dark:border-ink-700 dark:text-ink-300',
              )}
              style={value === option ? { background: accent } : undefined}
            >
              {option ? 'Yes' : 'No'}
            </button>
          ))}
        </div>
      )}

      {question.type === 'text' && (
        <textarea
          className="field min-h-24 resize-y"
          value={(value as string) ?? ''}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </div>
  )
}

export function PublicFeedback() {
  const { token = '' } = useParams()
  const [data, setData] = useState<PublicPayload | null>(null)
  const [dead, setDead] = useState<string | null>(null)
  const [answers, setAnswers] = useState<Answers>({})
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [done, setDone] = useState<string | null>(null)

  useEffect(() => {
    const load = () => {
      fetch(`${BASE}/feedback/${encodeURIComponent(token)}`, { cache: 'no-store' })
        .then(async (response) => {
          if (!response.ok) {
            const body = await response.json().catch(() => null)
            setDead(
              body?.error?.message ??
                'This feedback link is no longer valid.',
            )
            return
          }
          setData(await response.json())
        })
        .catch(() => setDead('We could not load this feedback form. Please try again later.'))
    }
    load()

    // This is the actual fix for "submitted, then re-opening the same link
    // still works": on a back/forward navigation, the browser can restore
    // this exact page from its back-forward cache (bfcache) — the DOM the
    // respondent last saw, including the live form, straight from memory,
    // with no network request and no JavaScript re-run. `cache: 'no-store'`
    // above only stops a *new* request from being served a cached response;
    // it does nothing when no request happens at all. `pageshow` with
    // `event.persisted === true` is the one event that fires specifically
    // for a bfcache restore, so it's what forces a real re-check. Resetting
    // the local state first means the respondent sees the loading spinner
    // again rather than a stale screen for the instant before the fresh
    // result comes back.
    const onPageShow = (event: PageTransitionEvent) => {
      if (!event.persisted) return
      setData(null)
      setDead(null)
      setDone(null)
      load()
    }
    window.addEventListener('pageshow', onPageShow)
    return () => window.removeEventListener('pageshow', onPageShow)
  }, [token])

  if (dead) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink-50 px-4 dark:bg-ink-950">
        <div className="w-full max-w-md rounded-xl border border-ink-200 bg-white p-8 text-center dark:border-ink-800 dark:bg-ink-900">
          <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-ink-100 text-ink-400 dark:bg-ink-800">
            <IconLock width={19} height={19} />
          </div>
          <h1 className="text-xl font-semibold text-ink-900 dark:text-white">
            Link no longer valid
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-500 dark:text-ink-400">
            {dead}
          </p>
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink-50 dark:bg-ink-950">
        <Spinner className="text-ink-400" />
      </div>
    )
  }

  const accent = data.organization.accent_color || '#2F6F62'
  const allQuestions = data.form.sections.flatMap((section) => section.questions)
  const required = allQuestions.filter((question) => question.required)
  const answered = required.filter(
    (question) => answers[question.key] !== undefined && answers[question.key] !== '',
  ).length
  const complete = answered === required.length

  if (done) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink-50 px-4 dark:bg-ink-950">
        <div className="w-full max-w-md rounded-xl border border-ink-200 bg-white p-8 text-center dark:border-ink-800 dark:bg-ink-900">
          <div
            className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full text-white"
            style={{ background: accent }}
          >
            <IconCheck width={22} height={22} />
          </div>
          <h1 className="text-xl font-semibold text-ink-900 dark:text-white">Thank you</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-500 dark:text-ink-400">
            {done}
          </p>
          <p className="mt-5 text-2xs text-ink-400">
            {data.organization.name}
          </p>
        </div>
      </div>
    )
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setProblems([])
    try {
      const response = await fetch(`${BASE}/feedback/${encodeURIComponent(token)}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ answers, comment: comment || null }),
      })
      const body = await response.json().catch(() => null)
      if (!response.ok) {
        setError(body?.error?.message ?? 'Your feedback could not be submitted.')
        setProblems(body?.error?.details?.answers ?? [])
        return
      }
      setDone(body.message)
    } catch {
      setError('We could not reach the server. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-ink-50 dark:bg-ink-950">
      {/* Tenant-branded header. The bar takes the client's accent colour, so
          the page reads as theirs from the first glance. */}
      <header
        className="border-b-2 bg-white dark:bg-ink-900"
        style={{ borderColor: accent }}
      >
        <div className="mx-auto flex max-w-2xl items-center gap-3 px-5 py-4">
          {data.organization.logo_url ? (
            <img
              src={data.organization.logo_url}
              alt={data.organization.name}
              className="h-8 max-w-[150px] object-contain"
            />
          ) : (
            <span className="text-lg font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
              {data.organization.name}
            </span>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-2xl px-5 py-10">
        <form onSubmit={submit}>
          <h1 className="text-3xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
            How did we do with {data.subject.label}?
          </h1>
          <p className="mt-2 text-base leading-relaxed text-ink-500 dark:text-ink-400">
            {data.recipient.full_name.split(' ')[0]}, {data.organization.name} would
            value your view. It takes about two minutes.
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-400">
            {data.campaign.closes_at && (
              <span className="flex items-center gap-1">
                <IconClock width={12} height={12} />
                Closes {new Date(data.campaign.closes_at).toLocaleDateString()}
              </span>
            )}
            <span className="flex items-center gap-1">
              <IconLock width={12} height={12} />
              {data.is_anonymous
                ? 'Your answers are anonymous'
                : 'No account or password needed'}
            </span>
          </div>

          {error && (
            <Banner tone="error" className="mt-6">
              <div>
                {error}
                {problems.length > 0 && (
                  <ul className="mt-1 list-disc pl-4">
                    {problems.map((problem) => (
                      <li key={problem}>{problem}</li>
                    ))}
                  </ul>
                )}
              </div>
            </Banner>
          )}

          {data.form.intro && (
            <p className="mt-6 rounded-lg border border-ink-200 bg-white p-4 text-sm leading-relaxed text-ink-600 dark:border-ink-800 dark:bg-ink-900 dark:text-ink-300">
              {data.form.intro}
            </p>
          )}

          <div className="mt-6 space-y-5">
            {data.form.sections.map((section) => (
              <section
                key={section.key}
                className="rounded-xl border border-ink-200 bg-white p-6 dark:border-ink-800 dark:bg-ink-900"
              >
                <h2 className="mb-4 text-lg font-semibold text-ink-900 dark:text-ink-50">
                  {section.title}
                </h2>
                {section.questions.map((question) => (
                  <ScaleRow
                    key={question.key}
                    question={question}
                    form={data.form}
                    value={answers[question.key]}
                    accent={accent}
                    onChange={(value) =>
                      setAnswers((current) => ({ ...current, [question.key]: value }))
                    }
                  />
                ))}
              </section>
            ))}

                        {data.form.closing.comment_prompt && (
              <section className="rounded-xl border border-ink-200 bg-white p-6 dark:border-ink-800 dark:bg-ink-900">
                <h2 className="mb-3 text-lg font-semibold text-ink-900 dark:text-ink-50">
                  {data.form.closing.comment_prompt}
                </h2>
                <textarea
                  className="field min-h-28 resize-y"
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Optional, but the most useful part for us."
                />
              </section>
            )}
          </div>

          <div className="sticky bottom-0 mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-ink-200 bg-ink-50/95 py-4 backdrop-blur dark:border-ink-800 dark:bg-ink-950/95">
            <span className="text-xs text-ink-500 dark:text-ink-400">
              <span className="tabular">{answered}</span> of{' '}
              <span className="tabular">{required.length}</span> answered
            </span>
            <button
              type="submit"
              disabled={busy || !complete}
              className="rounded-lg px-6 py-2.5 text-base font-medium text-white transition-opacity disabled:opacity-40"
              style={{ background: accent }}
            >
              {busy && <Spinner className="mr-1.5 inline" />}
              Send feedback
            </button>
          </div>
        </form>

        <p className="mt-8 text-center text-2xs text-ink-400">
          Powered by Stixis AI Solutions © Copyright 2026-2027
        </p>
      </main>
    </div>
  )
}