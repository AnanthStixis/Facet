import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { FacetMark } from './components/Logo'
import { Modal } from './components/ui'
import { AppShell } from './layout/AppShell'
import { Campaigns } from './pages/Campaigns'
import { Clients } from './pages/Clients'
import { CreateFeedback } from './pages/CreateFeedback'
import { Cycles } from './pages/Cycles'
import { Dashboard } from './pages/Dashboard'
import { Insights } from './pages/Insights'
import { Login } from './pages/Login'
import { PublicFeedback } from './pages/PublicFeedback'
import { MyFeedback } from './pages/MyFeedback'
import { MyResults } from './pages/MyResults'
import { Organizations } from './pages/Organizations'
import { Masters } from './pages/Masters'
import { People } from './pages/People'
import { AcceptInvite, Register, ResetPassword } from './pages/Public'
import { AuditPage } from './pages/ReportView'
import { Reports } from './pages/Reports'
import { Results } from './pages/Results'
import { Security } from './pages/Security'
import { Settings } from './pages/Settings'
import { Categories } from './pages/Categories'
import { Templates } from './pages/Templates'
import { useAuth } from './store/auth'

function Booting() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-ink-950">
      <span className="accent-text animate-pulse">
        <FacetMark size={34} />
      </span>
      <p className="text-sm text-ink-500">Restoring your session…</p>
    </div>
  )
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { phase } = useAuth()
  const location = useLocation()

  if (phase === 'booting') return <Booting />
  if (phase !== 'authenticated') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <>{children}</>
}

function RequireRole({
  roles,
  children,
}: {
  roles: string[]
  children: React.ReactNode
}) {
  const { user } = useAuth()
  // Belt and braces only: the API enforces this independently, and row level
  // security enforces it again beneath that. Hiding a route the server would
  // refuse anyway is a usability decision, not a security control.
  if (!user || !roles.includes(user.role)) return <Navigate to="/" replace />
  return <>{children}</>
}

function NotFound() {
  return (
    <div className="py-20 text-center">
      <p className="text-5xl font-semibold text-ink-300 dark:text-ink-700">404</p>
      <p className="mt-2 text-lg font-medium text-ink-800 dark:text-ink-100">
        That page does not exist
      </p>
    </div>
  )
}

function SessionExpiredModal() {
  const { dismissSessionExpiredNotice } = useAuth()
  return (
    <Modal title="Session expired" onClose={dismissSessionExpiredNotice}>
      <p className="text-sm text-ink-600 dark:text-ink-300">
        Your session has expired. Please sign in again.
      </p>
      <div className="mt-5 flex justify-end">
        <button
          type="button"
          className="btn-primary px-4 py-1.5"
          onClick={dismissSessionExpiredNotice}
        >
          OK
        </button>
      </div>
    </Modal>
  )
}

// Routes an unauthenticated stranger is meant to reach. Attempting a session
// restore on these is pointless: the visitor has no account, and it costs a
// wasted request plus a 401 in their console.
const PUBLIC_PREFIXES = ['/f/', '/register', '/accept-invite', '/reset-password']

export default function App() {
  const { phase, boot, sessionExpiredNotice } = useAuth()
  const location = useLocation()
  const isPublic = PUBLIC_PREFIXES.some((prefix) =>
    location.pathname.startsWith(prefix),
  )

  useEffect(() => {
    if (isPublic) {
      useAuth.setState({ phase: 'anonymous' })
      return
    }
    void boot()
  }, [boot, isPublic])

  if (phase === 'booting' && !isPublic) return <Booting />

  return (
    <>
      {sessionExpiredNotice && <SessionExpiredModal />}
      <Routes>
      <Route
        path="/login"
        element={phase === 'authenticated' ? <Navigate to="/" replace /> : <Login />}
      />
      <Route path="/register" element={<Register />} />
      <Route path="/accept-invite" element={<AcceptInvite />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      {/* The respondent's page. Outside the shell and outside RequireAuth —
          an external client has no account and must never see a sign-in
          prompt on their way to giving feedback. */}
      <Route path="/f/:token" element={<PublicFeedback />} />

      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="my-feedback" element={<MyFeedback />} />
        <Route path="my-results" element={<MyResults />} />
        <Route
          path="create-feedback"
          element={
            <RequireRole roles={['super_admin', 'client_admin', 'manager']}>
              <CreateFeedback />
            </RequireRole>
          }
        />
        <Route
          path="results"
          element={
            <RequireRole roles={['super_admin', 'client_admin', 'manager']}>
              <Results />
            </RequireRole>
          }
        />
        <Route
          path="cycles"
          element={
            <RequireRole roles={['super_admin', 'client_admin', 'manager']}>
              <Cycles />
            </RequireRole>
          }
        />
        <Route
          path="campaigns"
          element={
            <RequireRole roles={['super_admin', 'client_admin', 'manager']}>
              <Campaigns />
            </RequireRole>
          }
        />
        <Route
          path="insights"
          element={
            <RequireRole roles={['super_admin', 'client_admin', 'manager']}>
              <Insights />
            </RequireRole>
          }
        />
        <Route
          path="organizations"
          element={
            <RequireRole roles={['super_admin']}>
              <Organizations />
            </RequireRole>
          }
        />
        <Route
          path="people"
          element={
            <RequireRole roles={['super_admin', 'client_admin']}>
              <People />
            </RequireRole>
          }
        />
        <Route
          path="masters"
          element={
            <RequireRole roles={['super_admin', 'client_admin', 'manager']}>
              <Masters />
            </RequireRole>
          }
        />
        <Route path="categories" element={<Categories />} />
        <Route path="templates" element={<Templates />} />
        <Route
          path="clients"
          element={
            <RequireRole roles={['client_admin', 'manager']}>
              <Clients />
            </RequireRole>
          }
        />
        <Route
          path="reports"
          element={
            <RequireRole roles={['super_admin', 'client_admin']}>
              <Reports />
            </RequireRole>
          }
        />
        <Route
          path="audit"
          element={
            <RequireRole roles={['super_admin', 'client_admin']}>
              <AuditPage />
            </RequireRole>
          }
        />
        {/* Client Admin only: these are org-level settings, and a Super
            Admin has no organization of their own to configure. */}
        <Route
          path="settings"
          element={
            <RequireRole roles={['client_admin']}>
              <Settings />
            </RequireRole>
          }
        />
        <Route path="security" element={<Security />} />
        <Route path="*" element={<NotFound />} />
      </Route>
      </Routes>
    </>
  )
}