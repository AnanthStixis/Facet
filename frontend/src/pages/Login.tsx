import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FacetMark } from '../components/Logo'
import { IconLock } from '../components/icons'
import { Banner, Field, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../store/auth'

function ForgotPassword({ initialEmail, onBack }: { initialEmail: string; onBack: () => void }) {
  const [email, setEmail] = useState(initialEmail)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  return (
    <form
      className="space-y-4"
      onSubmit={async (event) => {
        event.preventDefault()
        setBusy(true)
        setError(null)
        try {
          await api.post('/auth/forgot-password', { email })
          toast.show(
            'success',
            'Reset link sent',
            'If that email matches an account, a reset link is on its way. Check your inbox.',
          )
          onBack()
        } catch (caught) {
          setError(caught instanceof ApiError ? caught.message : 'Could not reach the server.')
        } finally {
          setBusy(false)
        }
      }}
    >
      {error && <Banner tone="error">{error}</Banner>}
      <Field
        label="Work email"
        type="email"
        autoComplete="username"
        autoFocus
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="you@company.com"
      />
      <button type="submit" disabled={busy} className="btn-primary w-full py-2.5">
        {busy && <Spinner />}
        Send reset link
      </button>
      <button type="button" className="btn-ghost w-full py-2" onClick={onBack}>
        Back to sign in
      </button>
    </form>
  )
}

/**
 * The artwork half of the sign-in screen.
 *
 * A slowly drawn constellation of the feedback graph: nodes for people, teams,
 * products and proposals, linked into one figure. It states the positioning
 * before a single word is read, and it is the reason this screen does not look
 * like the seven other HR tools the buyer evaluated the same week.
 */
function GraphArtwork() {
  const nodes = [
    { x: 50, y: 18, r: 4.5, kind: 'internal', label: 'Manager' },
    { x: 22, y: 34, r: 3.5, kind: 'internal', label: 'Peer' },
    { x: 78, y: 32, r: 3.5, kind: 'internal', label: 'Team' },
    { x: 50, y: 50, r: 6.5, kind: 'core', label: 'Person' },
    { x: 18, y: 68, r: 4, kind: 'external', label: 'Client' },
    { x: 50, y: 82, r: 4, kind: 'external', label: 'Proposal' },
    { x: 82, y: 66, r: 4, kind: 'external', label: 'Product' },
  ]
  const links: [number, number][] = [
    [0, 3], [1, 3], [2, 3], [3, 4], [3, 5], [3, 6], [4, 5], [5, 6], [1, 0], [0, 2],
  ]

  return (
    <svg viewBox="0 0 100 100" className="h-full w-full" aria-hidden="true">
      {links.map(([from, to], index) => (
        <line
          key={index}
          x1={nodes[from].x}
          y1={nodes[from].y}
          x2={nodes[to].x}
          y2={nodes[to].y}
          stroke="#8A93A0"
          strokeOpacity={0.4}
          strokeWidth={0.35}
          strokeDasharray="60"
          strokeDashoffset="60"
          style={{
            animation: `dash 1.5s ${0.25 + index * 0.07}s cubic-bezier(.3,.8,.3,1) forwards`,
          }}
        />
      ))}
      {nodes.map((node, index) => (
        <g
          key={node.label}
          style={{ animation: `pop .6s ${0.6 + index * 0.08}s cubic-bezier(.2,.9,.3,1) both` }}
        >
          {node.kind === 'core' && (
            <circle cx={node.x} cy={node.y} r={node.r + 4} fill="none" stroke="#2F6F62" strokeOpacity={0.3} strokeWidth={0.4} />
          )}
          <circle
            cx={node.x}
            cy={node.y}
            r={node.r}
            fill={
              node.kind === 'external'
                ? '#C08A2E'
                : node.kind === 'core'
                  ? '#2F6F62'
                  : '#3572B0'
            }
            fillOpacity={node.kind === 'core' ? 1 : 0.88}
          />
          <text
            x={node.x}
            y={node.y - node.r - 2.4}
            textAnchor="middle"
            fill="#5A6472"
            fillOpacity={0.85}
            style={{ fontSize: '2.6px', letterSpacing: '0.28px', textTransform: 'uppercase' }}
          >
            {node.label}
          </text>
        </g>
      ))}
      <style>{`
        @keyframes dash { to { stroke-dashoffset: 0; } }
        @keyframes pop { from { opacity: 0; transform: scale(.4); transform-origin: center; } to { opacity: 1; transform: scale(1); } }
      `}</style>
    </svg>
  )
}

export function Login() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [forgot, setForgot] = useState(false)

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setFieldErrors({})
    try {
      await login(email, password)
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        setFieldErrors(caught.fieldErrors())
      } else {
        setError('Could not reach the server. Check that the API is running.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      {/* Left: brand panel. Light and airy like the rest of the product now,
          rather than a permanently dark showcase panel — the sign-in screen
          should feel like the same tool, not a different one. */}
      <div className="relative hidden overflow-hidden bg-ink-50 dark:bg-ink-950 lg:flex lg:flex-col lg:justify-between">
        <div
          className="absolute inset-0 opacity-[0.35] dark:opacity-[0.06]"
          style={{
            backgroundImage:
              'linear-gradient(rgba(18,22,28,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(18,22,28,0.05) 1px, transparent 1px)',
            backgroundSize: '36px 36px',
          }}
        />
        <div
          className="absolute -left-24 top-1/3 h-96 w-96 rounded-full blur-3xl"
          style={{ background: 'radial-gradient(circle, rgba(47,111,98,0.16), transparent 68%)' }}
        />

        <div className="relative z-10 flex items-center gap-2.5 px-12 pt-11">
          <span className="accent-bg flex h-9 w-9 items-center justify-center rounded-lg text-white">
            <FacetMark size={20} />
          </span>
          <span className="text-xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
            Facet
          </span>
        </div>

        <div className="relative z-10 flex flex-1 items-center justify-center px-12">
          <div className="w-full max-w-md">
            <GraphArtwork />
          </div>
        </div>

        <div className="relative z-10 max-w-lg px-12 pb-14">
          <h2 className="text-4xl font-semibold leading-tight tracking-[-0.03em] text-ink-900 dark:text-white">
            Every relationship has more than one side.
          </h2>
          <p className="mt-3.5 text-base leading-relaxed text-ink-500 dark:text-ink-400">
            Employee, client, and proposal feedback in a single graph &mdash; so you
            can finally ask whether the teams that work well together are the ones
            winning the work.
          </p>
          <div className="mt-7 flex flex-wrap gap-x-6 gap-y-2 text-2xs uppercase tracking-[0.12em] text-ink-500 dark:text-ink-500">
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-internal" /> Internal 360
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-external" /> Client experience
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-external opacity-60" /> Proposal quality
            </span>
          </div>
        </div>
      </div>

      {/* Right: the form. */}
      <div className="flex items-center justify-center bg-white px-6 py-12 dark:bg-ink-950 sm:px-12">
        <div className="w-full max-w-sm animate-fade-up">
          <div className="mb-8 lg:hidden">
            <span className="accent-text">
              <FacetMark size={30} />
            </span>
          </div>

          <h1 className="text-3xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
            {forgot ? 'Reset your password' : 'Sign in'}
          </h1>
          <p className="mt-1.5 text-sm text-ink-500 dark:text-ink-400">
            {forgot
              ? "Enter your work email and we'll send a link to set a new password, if you have an account."
              : 'Use the credentials issued by your administrator.'}
          </p>

          {forgot ? (
            <div className="mt-7">
              <ForgotPassword initialEmail={email} onBack={() => setForgot(false)} />
            </div>
          ) : (
          <form onSubmit={handleSubmit} className="mt-7 space-y-4">
            {error && <Banner tone="error">{error}</Banner>}

            <Field
              label="Work email"
              type="email"
              autoComplete="username"
              autoFocus
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              error={fieldErrors.email}
              placeholder="you@company.com"
            />
            <Field
              label="Password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              error={fieldErrors.password}
              placeholder="••••••••••••"
            />
            <p className="text-right">
              <button
                type="button"
                className="accent-text text-xs font-medium hover:underline"
                onClick={() => setForgot(true)}
              >
                Forgot password?
              </button>
            </p>

            <button type="submit" disabled={busy} className="btn-primary w-full py-2.5">
              {busy && <Spinner />}
              Sign in
            </button>
          </form>
          )}

          {!forgot && (
            <>
              <div className="my-7 flex items-center gap-3">
                <span className="h-px flex-1 bg-ink-200 dark:bg-ink-800" />
                <span className="text-2xs uppercase tracking-[0.1em] text-ink-400">or</span>
                <span className="h-px flex-1 bg-ink-200 dark:bg-ink-800" />
              </div>
              <p className="text-center text-sm text-ink-500 dark:text-ink-400">
                Don't have an account yet?{' '}
                <Link to="/register" className="accent-text font-medium hover:underline">
                   Register here.
                </Link>
              </p>
            </>
          )}

          <p className="mt-9 flex items-center justify-center gap-1.5 text-2xs text-ink-400">
            <IconLock width={12} height={12} />
            Powered by Stixis AI Solutions © Copyright 2026-2027
          </p>
        </div>
      </div>
    </div>
  )
}
