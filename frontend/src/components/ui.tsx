import clsx from 'clsx'
import { useEffect, useRef, type InputHTMLAttributes, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { IconAlert, IconX } from './icons'

export function Card({
  title,
  hint,
  action,
  children,
  className,
  padded = true,
}: {
  title?: ReactNode
  hint?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  padded?: boolean
}) {
  return (
    <section className={clsx('surface animate-fade-up', className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-4 border-b border-ink-200 px-5 py-3.5 dark:border-ink-800">
          <div className="min-w-0">
            {title && (
              <h2 className="truncate text-lg font-semibold text-ink-900 dark:text-ink-50">
                {title}
              </h2>
            )}
            {hint && (
              <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">{hint}</p>
            )}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </header>
      )}
      <div className={padded ? 'p-5' : undefined}>{children}</div>
    </section>
  )
}

export function StatTile({
  label,
  value,
  sub,
  tone = 'neutral',
  to,
  state,
  onClick,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: 'neutral' | 'accent' | 'caution' | 'critical'
  to?: string
  state?: Record<string, unknown>
  onClick?: () => void
}) {
  const navigate = useNavigate()
  const interactive = Boolean(to || onClick)
  const activate = () => {
    if (onClick) onClick()
    else if (to) navigate(to, state ? { state } : undefined)
  }

  return (
    <div
      className={clsx(
        'surface animate-fade-up px-4 py-3.5 text-left',
        interactive &&
          'cursor-pointer transition-transform hover:-translate-y-0.5 hover:shadow-lift focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2',
      )}
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={interactive ? activate : undefined}
      onKeyDown={
        interactive
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                activate()
              }
            }
          : undefined
      }
    >
      <p className="label-caps">{label}</p>
      <p
        className={clsx(
          'mt-1.5 text-3xl font-semibold tabular',
          tone === 'accent' && 'accent-text',
          tone === 'caution' && 'text-caution',
          tone === 'critical' && 'text-critical',
          tone === 'neutral' && 'text-ink-900 dark:text-ink-50',
        )}
      >
        {value}
      </p>
      {sub && <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">{sub}</p>}
    </div>
  )
}

const CHIP_TONES: Record<string, string> = {
  active: 'bg-positive/10 text-positive',
  published: 'bg-positive/10 text-positive',
  pending: 'bg-caution/12 text-caution',
  invited: 'bg-caution/12 text-caution',
  suspended: 'bg-critical/10 text-critical',
  rejected: 'bg-critical/10 text-critical',
  disabled: 'bg-ink-200 text-ink-500 dark:bg-ink-800 dark:text-ink-400',
  alert: 'bg-critical/10 text-critical',
  notice: 'bg-caution/12 text-caution',
  info: 'bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-400',
  super_admin: 'bg-internal/12 text-internal',
  client_admin: 'accent-soft-bg accent-text',
  manager: 'bg-ink-100 text-ink-600 dark:bg-ink-800 dark:text-ink-300',
  employee: 'bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-400',
}

export function Chip({ value, children }: { value: string; children?: ReactNode }) {
  const key = String(value ?? '').toLowerCase()
  return (
    <span className={clsx('chip', CHIP_TONES[key] ?? CHIP_TONES.info)}>
      {children ?? key.replace(/_/g, ' ')}
    </span>
  )
}

export function Field({
  label,
  error,
  hint,
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  label: string
  error?: string
  hint?: string
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
        {label}
        {props.required && (
          <span className="ml-0.5 text-critical" aria-hidden="true">
            *
          </span>
        )}
      </span>
      <input
        {...props}
        aria-invalid={Boolean(error)}
        className={clsx(
          'field',
          error && 'border-critical focus:ring-critical',
          className,
        )}
      />
      {error ? (
        <span className="mt-1 flex items-start gap-1 text-xs text-critical">
          <IconAlert width={13} height={13} className="mt-0.5 shrink-0" />
          {error}
        </span>
      ) : hint ? (
        <span className="mt-1 block text-xs text-ink-400">{hint}</span>
      ) : null}
    </label>
  )
}

export function Banner({
  tone = 'info',
  children,
  onDismiss,
  className,
  autoScroll = true,
}: {
  tone?: 'info' | 'error' | 'success' | 'warning'
  children: ReactNode
  onDismiss?: () => void
  className?: string
  /** Scroll itself into view on mount. On by default because the common case
   * — a submit result appearing at the top of a page the user has scrolled
   * down on — is otherwise invisible until they scroll back up themselves. */
  autoScroll?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // Instant, not smooth: a submit result needs to be visible the moment it
    // appears, not after an animation catches up — and smooth scrolling
    // triggered from inside a just-mounted element is unreliable across
    // browsers when nothing else on the page moves the scrollbar first.
    if (autoScroll) ref.current?.scrollIntoView({ behavior: 'auto', block: 'center' })
    // Only on mount — a banner already on screen should not keep re-scrolling
    // the page every time its content or tone changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div
      ref={ref}
      role={tone === 'error' ? 'alert' : 'status'}
      className={clsx(
        'flex items-start gap-2.5 rounded-md border px-3.5 py-2.5 text-sm animate-fade-up',
        tone === 'error' && 'border-critical/30 bg-critical/5 text-critical',
        tone === 'success' && 'border-positive/30 bg-positive/5 text-positive',
        tone === 'warning' && 'border-caution/35 bg-caution/8 text-caution',
        tone === 'info' &&
          'border-ink-200 bg-ink-50 text-ink-600 dark:border-ink-700 dark:bg-ink-800/60 dark:text-ink-300',
        className,
      )}
    >
      {tone === 'error' && <IconAlert className="mt-0.5 shrink-0" />}
      <div className="min-w-0 flex-1">{children}</div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="shrink-0 opacity-60 hover:opacity-100">
          <IconX width={14} height={14} />
        </button>
      )}
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode
  title: string
  body?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2.5 px-6 py-14 text-center">
      {icon && (
        <div className="mb-1 flex h-11 w-11 items-center justify-center rounded-full bg-ink-100 text-ink-400 dark:bg-ink-800">
          {icon}
        </div>
      )}
      <p className="text-lg font-semibold text-ink-800 dark:text-ink-100">{title}</p>
      {body && <p className="max-w-sm text-sm text-ink-500 dark:text-ink-400">{body}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('skeleton', className)} />
}

export function Modal({
  title,
  hint,
  onClose,
  children,
  className,
}: {
  title: ReactNode
  hint?: ReactNode
  onClose: () => void
  children: ReactNode
  className?: string
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink-950/50 p-4 py-10 backdrop-blur-[1px]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        className={clsx(
          'surface w-full max-w-2xl animate-fade-up',
          className,
        )}
      >
        <header className="flex items-start justify-between gap-4 border-b border-ink-200 px-5 py-3.5 dark:border-ink-800">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold text-ink-900 dark:text-ink-50">
              {title}
            </h2>
            {hint && <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">{hint}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700 dark:hover:bg-ink-800"
          >
            <IconX width={16} height={16} />
          </button>
        </header>
        <div className="max-h-[75vh] overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={clsx('animate-spin', className)}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.22" strokeWidth="3" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}
