import type { ApiErrorBody, SessionResponse } from './types'

const BASE = '/api/v1'

export class ApiError extends Error {
  code: string
  details?: Record<string, string[]>
  status: number
  requestId?: string

  constructor(status: number, body: ApiErrorBody) {
    const base = body?.error?.message ?? 'Something went wrong.'
    const details = body?.error?.details
    // The backend's top-level message for a 422 is deliberately generic
    // ("Some of the submitted values are not valid.") so it never needs
    // localising — the actual per-field reasons live in `details`. Most call
    // sites just show `caught.message` and never touch `fieldErrors()`, so
    // without this the user sees the generic sentence and nothing else. Fold
    // the field reasons into the message itself so every existing call site
    // gets a useful error for free.
    const fieldSummary = details
      ? Object.entries(details)
          .map(([field, messages]) => `${field}: ${messages.join(' ')}`)
          .join('; ')
      : ''
    super(fieldSummary ? `${base} (${fieldSummary})` : base)
    this.status = status
    this.code = body?.error?.code ?? 'unknown'
    this.details = details
    this.requestId = body?.error?.request_id
  }

  /** Field-level messages for inline form errors. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {}
    for (const [field, messages] of Object.entries(this.details ?? {})) {
      out[field] = messages.join(' ')
    }
    return out
  }
}

// The access token is held in a module variable, never in localStorage or a
// readable cookie. Anything persisted where JavaScript can read it survives a
// tab close but also survives an XSS bug, and the second property is worse
// than the first is useful. The refresh cookie is httpOnly, so a reload
// restores the session without ever exposing a bearer token to script.
let accessToken: string | null = null
let csrfToken: string | null = null
let refreshInFlight: Promise<SessionResponse | null> | null = null

export const setTokens = (access: string | null, csrf?: string | null) => {
  accessToken = access
  if (csrf !== undefined) csrfToken = csrf
}

export const getAccessToken = () => accessToken

const readCsrfCookie = (): string | null => {
  const match = document.cookie.match(/(?:^|;\s*)facet_csrf=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T
  const contentType = response.headers.get('content-type') ?? ''
  if (!response.ok) {
    const body = contentType.includes('application/json')
      ? await response.json()
      : { error: { code: 'http_error', message: response.statusText } }
    throw new ApiError(response.status, body as ApiErrorBody)
  }
  return contentType.includes('application/json')
    ? ((await response.json()) as T)
    : (undefined as T)
}

/** Exchange the refresh cookie for a new access token. Deduplicated. */
export async function refreshSession(): Promise<SessionResponse | null> {
  // Several requests can 401 at the same moment when a token expires. Without
  // this guard each would refresh independently, and rotation means all but
  // the first would present an already-spent token, which the backend
  // correctly treats as theft and would sign the user out.
  if (refreshInFlight) return refreshInFlight

  refreshInFlight = (async () => {
    try {
      const response = await fetch(`${BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { 'x-facet-csrf': csrfToken ?? readCsrfCookie() ?? '' },
      })
      if (!response.ok) {
        setTokens(null, null)
        return null
      }
      const session = (await response.json()) as SessionResponse
      setTokens(session.access_token, session.csrf_token)
      return session
    } catch {
      return null
    } finally {
      refreshInFlight = null
    }
  })()

  return refreshInFlight
}

interface RequestOptions {
  method?: string
  body?: unknown
  retry?: boolean
  raw?: boolean
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, retry = true } = options
  const headers: Record<string, string> = {}
  if (accessToken) headers.authorization = `Bearer ${accessToken}`
  if (body !== undefined) headers['content-type'] = 'application/json'
  const csrf = csrfToken ?? readCsrfCookie()
  if (csrf) headers['x-facet-csrf'] = csrf

  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    // Without this, the browser applies its default HTTP caching heuristics
    // to GET requests — no explicit Cache-Control from the API means it can
    // still serve a stale response from disk cache on a repeat request to
    // the same URL. That is exactly "the change doesn't show up until I hard
    // reload or clear cache": the app was correct, the browser served an old
    // response instead of making a new request.
    cache: 'no-store',
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401 && retry) {
    const code = await response
      .clone()
      .json()
      .then((b: ApiErrorBody) => b?.error?.code)
      .catch(() => undefined)
    // Reuse detection means the session was deliberately destroyed. Retrying
    // would be pointless and would mask a security event from the user.
    // if (code !== 'token_reuse_detected') {
    //   const session = await refreshSession()
    //   if (session) return request<T>(path, { ...options, retry: false })
    // }
      if (code === 'session_expired' || code === 'unauthenticated') {
      const session = await refreshSession()
      if (session) return request<T>(path, { ...options, retry: false })
     }
  }

  return parse<T>(response)
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

/**
 * Upload a file as multipart/form-data.
 *
 * Deliberately not routed through `request()`: that helper always sets
 * `content-type: application/json`, and a multipart body needs the browser to
 * set its own `content-type` with the correct boundary — setting it manually
 * is a classic way to silently send a body the server cannot parse.
 */
export async function uploadFile<T>(
  path: string,
  file: File,
  fieldName = 'file',
): Promise<T> {
  const form = new FormData()
  form.append(fieldName, file)

  const headers: Record<string, string> = {}
  if (accessToken) headers.authorization = `Bearer ${accessToken}`
  const csrf = csrfToken ?? readCsrfCookie()
  if (csrf) headers['x-facet-csrf'] = csrf

  let response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    credentials: 'same-origin',
    body: form,
  })

  if (response.status === 401) {
    const session = await refreshSession()
    if (session) {
      headers.authorization = `Bearer ${session.access_token}`
      headers['x-facet-csrf'] = session.csrf_token
      response = await fetch(`${BASE}${path}`, {
        method: 'POST',
        headers,
        credentials: 'same-origin',
        body: form,
      })
    }
  }

  return parse<T>(response)
}

/** Download an export, preserving the filename the server chose. */
export async function downloadExport(
  reportKey: string,
  format: string,
  filters: unknown,
): Promise<void> {
  const headers: Record<string, string> = { 'content-type': 'application/json' }
  if (accessToken) headers.authorization = `Bearer ${accessToken}`
  const csrf = csrfToken ?? readCsrfCookie()
  if (csrf) headers['x-facet-csrf'] = csrf

  let response = await fetch(`${BASE}/reports/${reportKey}/export/${format}`, {
    method: 'POST',
    headers,
    credentials: 'same-origin',
    body: JSON.stringify(filters),
  })

  if (response.status === 401) {
    const session = await refreshSession()
    if (session) {
      headers.authorization = `Bearer ${session.access_token}`
      headers['x-facet-csrf'] = session.csrf_token
      response = await fetch(`${BASE}/reports/${reportKey}/export/${format}`, {
        method: 'POST',
        headers,
        credentials: 'same-origin',
        body: JSON.stringify(filters),
      })
    }
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, body as ApiErrorBody)
  }

  const disposition = response.headers.get('content-disposition') ?? ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : `${reportKey}.${format}`

  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/** GET a file from an authenticated endpoint and save it, e.g. a CSV template. */
export async function downloadFile(path: string, fallbackFilename: string): Promise<void> {
  const headers: Record<string, string> = {}
  if (accessToken) headers.authorization = `Bearer ${accessToken}`

  let response = await fetch(`${BASE}${path}`, {
    headers,
    credentials: 'same-origin',
    cache: 'no-store',
  })

  if (response.status === 401) {
    const session = await refreshSession()
    if (session) {
      headers.authorization = `Bearer ${session.access_token}`
      response = await fetch(`${BASE}${path}`, {
        headers,
        credentials: 'same-origin',
        cache: 'no-store',
      })
    }
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, body as ApiErrorBody)
  }

  const disposition = response.headers.get('content-disposition') ?? ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : fallbackFilename

  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
