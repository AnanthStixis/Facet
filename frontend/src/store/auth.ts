import { create } from 'zustand'
import { api, refreshSession, setSessionExpiredHandler, setTokens } from '../lib/api'
import type { Organization, SessionResponse, User } from '../lib/types'

type Phase = 'booting' | 'anonymous' | 'mfa_required' | 'authenticated'

interface AuthState {
  phase: Phase
  user: User | null
  organization: Organization | null
  theme: 'light' | 'dark'
  sessionExpiredNotice: boolean

  boot: () => Promise<void>
  login: (email: string, password: string) => Promise<SessionResponse>
  submitMfa: (code: string) => Promise<void>
  logout: () => Promise<void>
  setTheme: (theme: 'light' | 'dark') => void
  applySession: (session: SessionResponse) => void
  updateOrganization: (organization: Organization) => void
  dismissSessionExpiredNotice: () => void
}

/** Paint the tenant's accent colour into the CSS custom properties. */
const applyBranding = (organization: Organization | null) => {
  const accent = organization?.branding?.accent_color || '#B4633A'
  const root = document.documentElement
  root.style.setProperty('--accent', accent)
  const [r, g, b] = [1, 3, 5].map((index) => parseInt(accent.slice(index, index + 2), 16))
  root.style.setProperty('--accent-soft', `rgba(${r}, ${g}, ${b}, 0.12)`)
}

const applyTheme = (theme: 'light' | 'dark') => {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  localStorage.setItem('facet-theme', theme)
}

const initialTheme = (): 'light' | 'dark' => {
  const stored = localStorage.getItem('facet-theme')
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export const useAuth = create<AuthState>((set, get) => ({
  phase: 'booting',
  user: null,
  organization: null,
  theme: initialTheme(),
  sessionExpiredNotice: false,

  applySession(session) {
    setTokens(session.access_token, session.csrf_token)
    applyBranding(session.organization)
    set({
      phase: session.mfa_required ? 'mfa_required' : 'authenticated',
      user: session.user,
      organization: session.organization,
      sessionExpiredNotice: false,
    })
  },

  async boot() {
    applyTheme(get().theme)
    // The refresh cookie survives a reload, so a session can be restored
    // without ever having stored a bearer token where script could read it.
    const session = await refreshSession()
    if (session?.user) {
      applyBranding(session.organization)
      set({
        phase: 'authenticated',
        user: session.user,
        organization: session.organization,
      })
    } else {
      set({ phase: 'anonymous', user: null, organization: null })
    }
  },

  async login(email, password) {
    const session = await api.post<SessionResponse>('/auth/login', { email, password })
    get().applySession(session)
    return session
  },

  async submitMfa(code) {
    const session = await api.post<SessionResponse>('/auth/mfa/challenge', { code })
    get().applySession(session)
  },

  async logout() {
    try {
      await api.post('/auth/logout')
    } finally {
      setTokens(null, null)
      set({ phase: 'anonymous', user: null, organization: null })
    }
  },

  setTheme(theme) {
    applyTheme(theme)
    set({ theme })
  },

  // Lets the branding screen repaint the accent and header logo immediately
  // after a save, rather than requiring a reload to see the tenant's own
  // change take effect.
  updateOrganization(organization) {
    applyBranding(organization)
    set({ organization })
  },

  dismissSessionExpiredNotice() {
    set({ sessionExpiredNotice: false })
  },
}))

// A definitively-expired session (refresh cookie rejected) must drop the
// stored user immediately — otherwise the sidebar keeps showing "Signed in
// as <old user>" while the app is actually logged out, and RequireAuth in
// App.tsx has nothing to react to until the person happens to navigate.
//
// The notice, though, is only shown if this tab actually had a live session
// that just died — i.e. phase was already 'authenticated' the moment this
// fired. If phase was still 'booting' (the very first check on a fresh page
// load) or already 'anonymous', there was nothing for *this* visit to lose:
// it's just an old, unrelated cookie being cleaned up quietly, and telling
// someone who was never logged in this visit that their "session expired"
// is confusing, not helpful.
setSessionExpiredHandler(() => {
  const hadLiveSession = useAuth.getState().phase === 'authenticated'
  useAuth.setState({
    phase: 'anonymous',
    user: null,
    organization: null,
    sessionExpiredNotice: hadLiveSession,
  })
})