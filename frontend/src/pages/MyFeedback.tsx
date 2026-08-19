import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { IconCheck, IconClock, IconLock, IconShield } from '../components/icons'
import { Banner, Card, EmptyState, Skeleton, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { useRefetchOnFocus } from '../hooks/useRefetchOnFocus'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import type {
  Assignment,
  AssignmentForm,
  FeedbackForm,
  FormQuestion,
} from '../lib/cycleTypes'
import { RELATIONSHIP_LABEL, RELATIONSHIP_SHORT } from '../lib/cycleTypes'

type Answers = Record<string, number | string | boolean>

function dueLabel(due: string | null): { text: string; tone: string } {
  if (!due) return { text: 'No deadline', tone: 'text-ink-400' }
  const days = Math.ceil(
    (new Date(due).getTime() - Date.now()) / (1000 * 60 * 60 * 24),
  )
  if (days < 0) return { text: `${Math.abs(days)}d overdue`, tone: 'text-critical' }
  if (days === 0) return { text: 'Due today', tone: 'text-critical' }
  if (days <= 3) return { text: `Due in ${days}d`, tone: 'text-caution' }
  return { text: `Due in ${days}d`, tone: 'text-ink-400' }
}

/**
 * The rating control.
 *
 * Buttons rather than a select or a slider: the whole scale is visible at once,
 * every point is one tap on a phone, and there is no hidden state. This is the
 * control a respondent will use eighty times in one sitting, so the cost of
 * getting it slightly wrong is multiplied by eighty.
 */
function ScaleInput({
  min,
  max,
  labels,
  value,
  onChange,
}: {
  min: number
  max: number
  labels: Record<string, string>
  value: number | undefined
  onChange: (value: number) => void
}) {
  const points = Array.from({ length: max - min + 1 }, (_, index) => min + index)
  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {points.map((point) => {
          const active = value === point
          return (
            <button
              key={point}
              type="button"
              onClick={() => onChange(point)}
              aria-pressed={active}
              title={labels[String(point)]}
              className={clsx(
                'h-9 min-w-9 rounded-md border px-3 text-sm font-medium transition-colors',
                active
                  ? 'accent-bg border-transparent text-white'
                  : 'border-ink-200 text-ink-600 hover:border-ink-400 dark:border-ink-700 dark:text-ink-300',
              )}
            >
              {point}
            </button>
          )
        })}
      </div>
      {value !== undefined && labels[String(value)] && (
        <p className="mt-1.5 text-xs text-ink-500 dark:text-ink-400">
          {labels[String(value)]}
        </p>
      )}
    </div>
  )
}

function QuestionField({
  question,
  form,
  value,
  onChange,
  error,
}: {
  question: FormQuestion
  form: FeedbackForm
  value: Answers[string] | undefined
  onChange: (value: Answers[string]) => void
  error?: string
}) {
  return (
    <div className="border-t border-ink-200 py-4 first:border-t-0 first:pt-0 dark:border-ink-800">
      <p className="mb-2.5 text-sm font-medium text-ink-800 dark:text-ink-100">
        {question.text}
        {question.required && <span className="accent-text ml-1">*</span>}
      </p>

      {question.type === 'scale' && (
        <ScaleInput
          min={form.scale.min}
          max={form.scale.max}
          labels={form.scale.labels}
          value={value as number | undefined}
          onChange={onChange}
        />
      )}

      {question.type === 'choice' && (
        <div className="flex flex-wrap gap-1.5">
          {question.options.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => onChange(option)}
              className={clsx(
                'rounded-md border px-3 py-1.5 text-sm transition-colors',
                value === option
                  ? 'accent-bg border-transparent text-white'
                  : 'border-ink-200 text-ink-600 hover:border-ink-400 dark:border-ink-700 dark:text-ink-300',
              )}
            >
              {option}
            </button>
          ))}
        </div>
      )}

      {question.type === 'boolean' && (
        <div className="flex gap-1.5">
          {[true, false].map((option) => (
            <button
              key={String(option)}
              type="button"
              onClick={() => onChange(option)}
              className={clsx(
                'rounded-md border px-4 py-1.5 text-sm transition-colors',
                value === option
                  ? 'accent-bg border-transparent text-white'
                  : 'border-ink-200 text-ink-600 hover:border-ink-400 dark:border-ink-700 dark:text-ink-300',
              )}
            >
              {option ? 'Yes' : 'No'}
            </button>
          ))}
        </div>
      )}

      {question.type === 'text' && (
        <textarea
          className={clsx('field min-h-20 resize-y', error && 'border-critical')}
          value={(value as string) ?? ''}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Your answer"
        />
      )}

      {error && <p className="mt-1.5 text-xs text-critical">{error}</p>}
    </div>
  )
}

function FeedbackFormView({
  data,
  onDone,
  onCancel,
}: {
  data: AssignmentForm
  onDone: (message: string) => void
  onCancel: () => void
}) {
  const { assignment, form } = data
  const [answers, setAnswers] = useState<Answers>({})
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const allQuestions = form.sections.flatMap((section) => section.questions)
  const required = allQuestions.filter((question) => question.required)
  const answered = required.filter(
    (question) => answers[question.key] !== undefined && answers[question.key] !== '',
  ).length
  const complete = answered === required.length
  const percent = required.length ? Math.round((100 * answered) / required.length) : 100

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setFieldErrors({})
    try {
      const result = await api.post<{ message: string }>(
        `/assignments/${assignment.id}/submit`,
        { answers, comment: comment || null },
      )
      onDone(result.message)
    } catch (caught) {
      if (caught instanceof ApiError) {
        const fields = caught.fieldErrors()
        // When a problem is tied to a specific field, show it there instead
        // of repeating it in a toast too — see the password-change fix
        // for the same reasoning. The toast stays for anything that isn't
        // attributable to one field (e.g. "unknown question" on a stale form).
        if (Object.keys(fields).length === 0) {
          toast.show('critical', 'Could not submit feedback', caught.message)
        }
        setFieldErrors(fields)
      } else {
        toast.show('critical', 'Could not submit feedback', 'Your feedback could not be submitted.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <button
            type="button"
            className="btn-ghost mb-2 px-2 py-1 text-xs"
            onClick={onCancel}
          >
            &larr; Back to my feedback
          </button>
          <h1 className="text-3xl font-semibold text-ink-900 dark:text-white">
            Feedback on {assignment.target_label}
          </h1>
          <p className="mt-1 text-sm text-ink-500 dark:text-ink-400">
            {assignment.cycle_name} &middot;{' '}
            {RELATIONSHIP_LABEL[assignment.relationship]}
          </p>
        </div>
      </div>

      {/* The anonymity promise is stated where the honesty is being asked for,
          not buried in a policy page. It is also precise: the storage model
          genuinely cannot link this back, so the wording says so plainly. */}
      {assignment.is_anonymous && assignment.relationship !== 'self' && (
        <Banner tone="info" className="mb-5">
          <span className="flex flex-wrap items-center gap-x-1.5">
            <IconLock width={14} height={14} />
            <strong>This is anonymous.</strong> Your name is not stored against these
            answers, and there is no record linking them back to you — not for your
            administrator, and not for anyone with database access.
          </span>
        </Banner>
      )}

      {form.intro && (
        <p className="mb-5 max-w-2xl text-sm leading-relaxed text-ink-600 dark:text-ink-300">
          {form.intro}
        </p>
      )}

      <div className="space-y-5">
        {form.sections.map((section) => (
          <Card key={section.key} title={section.title}>
            {section.questions.map((question) => (
              <QuestionField
                key={question.key}
                question={question}
                form={form}
                value={answers[question.key]}
                error={fieldErrors[question.key]}
                onChange={(value) =>
                  setAnswers((current) => ({ ...current, [question.key]: value }))
                }
              />
            ))}
          </Card>
        ))}

        <Card title="Closing comment">
          <textarea
            className={clsx(
              'field min-h-28 resize-y',
              fieldErrors.closing_comment && 'border-critical',
            )}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder={form.closing.comment_prompt}
          />
          {fieldErrors.closing_comment ? (
            <p className="mt-1.5 text-xs text-critical">{fieldErrors.closing_comment}</p>
          ) : (
            <p className="mt-1.5 text-xs text-ink-400">
              Specific examples are far more useful than general praise.
            </p>
          )}
        </Card>
      </div>

      {/* Sticky footer: on a long form the submit button should never be
          something the respondent has to go looking for. */}
      <div className="sticky bottom-0 mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-ink-200 bg-white/90 py-3 backdrop-blur dark:border-ink-800 dark:bg-ink-950/90">
        <div className="flex items-center gap-3">
          <div className="h-1.5 w-32 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
            <div
              className="accent-bg h-full transition-all"
              style={{ width: `${percent}%` }}
            />
          </div>
          <span className="text-xs text-ink-500 dark:text-ink-400">
            <span className="tabular">{answered}</span> of{' '}
            <span className="tabular">{required.length}</span> required answered
          </span>
        </div>
        <div className="flex gap-2">
          <button type="button" className="btn-secondary px-3 py-1.5" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn-primary px-4 py-1.5"
            disabled={busy || !complete}
          >
            {busy && <Spinner />}
            Submit feedback
          </button>
        </div>
      </div>
    </form>
  )
}
export function MyFeedback() {
  const location = useLocation()
  const navigate = useNavigate()
  const { assignmentId } = useParams<{ assignmentId?: string }>()
  const cameFromDashboard = (location.state as { from?: string } | null)?.from === 'dashboard'
  const [assignments, setAssignments] = useState<Assignment[] | null>(null)
  const [active, setActive] = useState<AssignmentForm | null>(null)
  const toast = useToast()
  const [opening, setOpening] = useState<string | null>(null)

  const load = () => {
    api
      .get<Assignment[]>('/assignments/mine')
      .then(setAssignments)
      .catch((caught) =>
        toast.show(
          'critical',
          'Could not load your feedback',
          caught instanceof ApiError ? caught.message : undefined,
        ),
      )
  }

  useEffect(load, [])
  useRefetchOnFocus(load)

    const open = async (id: string) => {
    setOpening(id)
    try {
      setActive(await api.get<AssignmentForm>(`/assignments/${id}`))
    } catch (caught) {
      toast.show(
        'critical',
        'Could not open that form',
        caught instanceof ApiError
          ? caught.message
          : 'That link may have expired, or you may have already responded.',
      )
      // A deep link from an email pointing at an assignment that no longer
      // applies (already submitted, cycle closed, wrong account) should
      // land the person on their list instead of a dead end.
      if (assignmentId) navigate('/my-feedback', { replace: true })
    } finally {
      setOpening(null)
    }
  }

  // The "you have been asked" email links straight to one assignment's
  // form (`/my-feedback/{id}`), not the generic list — this is what makes
  // that land on the actual form instead of requiring a second click, the
  // same experience the external one-time link already gives an outside
  // respondent. Runs once per id the URL actually carries.
  useEffect(() => {
    if (assignmentId) void open(assignmentId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignmentId])

  if (active) {
    return (
      <FeedbackFormView
        data={active}
                onCancel={() => {
          setActive(null)
          if (assignmentId) navigate('/my-feedback', { replace: true })
        }}
        onDone={(message) => {
          const submittedId = active.assignment.id
          setActive(null)
          toast.show('success', message)
          setAssignments((current) => (current ? current.filter((a) => a.id !== submittedId) : current))
          if (assignmentId) navigate('/my-feedback', { replace: true })
        }}
      />
    )
  }

  return (
    <>
      <PageHeader
        title="My feedback"
        backTo={cameFromDashboard ? '/' : undefined}
        backLabel="Dashboard"
        description="Feedback you have been asked to give. Nothing here is visible to the person concerned until enough people have responded."
      />

        {(!assignments || (assignmentId && opening === assignmentId)) ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-20 w-full rounded-lg" />
          ))}
        </div>
      ) : assignments.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconCheck width={19} height={19} />}
            title="You are all caught up"
            body="Nothing is waiting for your input. You will see requests here as soon as a review cycle opens."
          />
        </Card>
      ) : (
        <div className="grid gap-3">
          {assignments.map((assignment) => {
            const due = dueLabel(assignment.due_at)
            return (
              <Card key={assignment.id} className="flex flex-wrap items-center justify-between gap-4">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="text-base font-semibold text-ink-900 dark:text-ink-50">
                      {assignment.target_label}
                    </span>
                    <span className="chip bg-ink-100 text-ink-600 dark:bg-ink-800 dark:text-ink-300">
                      {RELATIONSHIP_SHORT[assignment.relationship]}
                    </span>
                    {assignment.is_anonymous && assignment.relationship !== 'self' && (
                      <span className="chip accent-soft-bg accent-text flex items-center gap-1">
                        <IconLock width={10} height={10} />
                        Anonymous
                      </span>
                    )}
                  </p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-ink-500 dark:text-ink-400">
                    <span>{assignment.cycle_name}</span>
                    <span className={clsx('flex items-center gap-1', due.tone)}>
                      <IconClock width={12} height={12} />
                      {due.text}
                    </span>
                  </p>
                </div>
                <button
                  type="button"
                  className="btn-primary shrink-0 px-3 py-1.5 text-sm"
                  disabled={opening === assignment.id}
                  onClick={() => open(assignment.id)}
                >
                  {opening === assignment.id && <Spinner />}
                  {assignment.status === 'in_progress' ? 'Continue' : 'Give feedback'}
                </button>
              </Card>
            )
          })}
        </div>
      )}

      <Card className="mt-5" title="How your answers are handled">
        <ul className="space-y-2 text-sm text-ink-600 dark:text-ink-300">
          {[
            'Anonymous responses are stored with no link to you — no reviewer id, and no connection to the request you were sent.',
            'Results stay hidden until enough people have responded, so a single answer can never be isolated.',
            'A breakdown by direction is only shown when that direction on its own clears the same threshold.',
            'Once submitted, a response cannot be edited or deleted by anyone, including an administrator.',
          ].map((line) => (
            <li key={line} className="flex items-start gap-2">
              <IconShield width={14} height={14} className="mt-0.5 shrink-0 accent-text" />
              {line}
            </li>
          ))}
        </ul>
      </Card>
    </>
  )
}