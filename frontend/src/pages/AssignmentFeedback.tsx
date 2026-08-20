// pages/AssignmentFeedback.tsx
import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { IconCheck, IconClock, IconLock } from '../components/icons'
import { Banner, Spinner } from '../components/ui'
import type { FeedbackForm, FormQuestion } from '../lib/cycleTypes'

type Answers = Record<string, number | string | boolean>

interface AssignmentPayload {
  organization: { name: string; accent_color: string; logo_url: string | null }
  subject: { label: string; type: string }
  cycle: { name: string; closes_at: string | null }
  relationship: string
  is_anonymous: boolean
  form: FeedbackForm
}

/**
 * The branded, full-page landing spot for the "Give feedback" button in a
 * "you have been asked" email. Unauthenticated and token-based, same as
 * `PublicFeedback.tsx` (the external respondent's page) — a single-use
 * token minted per assignment stands in for login, so someone arriving
 * straight from their inbox never has to sign in first.
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
    </div>
  )
}

export function AssignmentFeedback() {
  const { token = '' } = useParams()
  const [data, setData] = useState<AssignmentPayload | null>(null)
  const [dead, setDead] = useState<string | null>(null)
  const [answers, setAnswers] = useState<Answers>({})
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [done, setDone] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/v1/public/assignment/${encodeURIComponent(token)}`, { cache: 'no-store' })
      .then(async (response) => {
        if (cancelled) return
        if (!response.ok) {
          const body = await response.json().catch(() => null)
          setDead(body?.error?.message ?? 'This feedback request could not be found.')
          return
        }
        setData(await response.json())
      })
      .catch(() => {
        if (!cancelled) setDead('We could not load this feedback form. Please try again later.')
      })
    return () => {
      cancelled = true
    }
  }, [token])

  const accent = data?.organization.accent_color || '#2F6F62'

  if (dead) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink-50 px-4 dark:bg-ink-950">
        <div className="w-full max-w-md rounded-xl border border-ink-200 bg-white p-8 text-center dark:border-ink-800 dark:bg-ink-900">
          <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-ink-100 text-ink-400 dark:bg-ink-800">
            <IconLock width={19} height={19} />
          </div>
          <h1 className="text-xl font-semibold text-ink-900 dark:text-white">
            Could not open this request
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
            {data.organization.name} · This link has now been used and will not open again.
          </p>
        </div>
      </div>
    )
  }

  const { form } = data
  const allQuestions = form.sections.flatMap((section) => section.questions)
  const required = allQuestions.filter((question) => question.required)
  const answered = required.filter(
    (question) => answers[question.key] !== undefined && answers[question.key] !== '',
  ).length
  const complete = answered === required.length

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setProblems([])
    try {
      const response = await fetch(
        `/api/v1/public/assignment/${encodeURIComponent(token)}/submit`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ answers, comment: comment || null }),
        },
      )
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
            Feedback on {data.subject.label}
          </h1>
          <p className="mt-2 text-base leading-relaxed text-ink-500 dark:text-ink-400">
            {data.cycle.name}. It takes about two minutes.
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-400">
            {data.cycle.closes_at && (
              <span className="flex items-center gap-1">
                <IconClock width={12} height={12} />
                Closes {new Date(data.cycle.closes_at).toLocaleDateString()}
              </span>
            )}
            {data.is_anonymous && (
              <span className="flex items-center gap-1">
                <IconLock width={12} height={12} />
                Your answers are anonymous
              </span>
            )}
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

          {form.intro && (
            <p className="mt-6 rounded-lg border border-ink-200 bg-white p-4 text-sm leading-relaxed text-ink-600 dark:border-ink-800 dark:bg-ink-900 dark:text-ink-300">
              {form.intro}
            </p>
          )}

          <div className="mt-6 space-y-5">
            {form.sections.map((section) => (
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
                    form={form}
                    value={answers[question.key]}
                    accent={accent}
                    onChange={(value) =>
                      setAnswers((current) => ({ ...current, [question.key]: value }))
                    }
                  />
                ))}
              </section>
            ))}

                        {form.closing.comment_prompt && (
              <section className="rounded-xl border border-ink-200 bg-white p-6 dark:border-ink-800 dark:bg-ink-900">
                <h2 className="mb-3 text-lg font-semibold text-ink-900 dark:text-ink-50">
                  {form.closing.comment_prompt}
                </h2>
                <textarea
                  className="field min-h-28 resize-y"
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Optional, but the most useful part."
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
      </main>
    </div>
  )
}