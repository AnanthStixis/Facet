import { create } from 'zustand'
import { api, refreshSession, setTokens } from '../lib/api'
import type { Organization, SessionResponse, User } from '../lib/types'

type Phase = 'booting' | 'anonymous' | 'mfa_required' | 'authenticated'

interface AuthState {
  phase: Phase
  user: User | null
  organization: Organization | null
  theme: 'light' | 'dark'

  boot: () => Promise<void>
  login: (email: string, password: string) => Promise<SessionResponse>
  submitMfa: (code: string) => Promise<void>
  logout: () => Promise<void>
  setTheme: (theme: 'light' | 'dark') => void
  applySession: (session: SessionResponse) => void
  updateOrganization: (organization: Organization) => void
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

  applySession(session) {
    setTokens(session.access_token, session.csrf_token)
    applyBranding(session.organization)
    set({
      phase: session.mfa_required ? 'mfa_required' : 'authenticated',
      user: session.user,
      organization: session.organization,
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
}))
