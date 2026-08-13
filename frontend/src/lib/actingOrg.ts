// A Super Admin's current "acting as" organization — never membership, just
// a per-session choice of which organization Cycles/Campaigns/Proposals
// currently operate against. Held in a module variable, the same way the
// access token itself is held (never localStorage — see lib/api.ts), and
// mirrored to sessionStorage only so a page refresh doesn't silently drop
// the selection mid-task. sessionStorage clears itself when the tab closes,
// unlike localStorage, so nothing survives past this browser session.

import { triggerManualRefresh } from '../hooks/useRefetchOnFocus'

export interface ActingOrg {
  id: string
  name: string
}

const STORAGE_KEY = 'facet_acting_org'

function readInitial(): ActingOrg | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as ActingOrg) : null
  } catch {
    return null
  }
}

let current: ActingOrg | null = readInitial()
const listeners = new Set<() => void>()

export function getActingOrg(): ActingOrg | null {
  return current
}

export function setActingOrg(org: ActingOrg | null): void {
  current = org
  try {
    if (org) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(org))
    else sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // sessionStorage can throw in a locked-down browser context (private
    // mode, some embedded webviews); the in-memory value above still holds
    // for the rest of this tab's session regardless.
  }
  listeners.forEach((listener) => listener())
  // Attaching the new selection to future requests (lib/api.ts) is not
  // enough on its own — whatever page is already open (Cycles, Campaigns,
  // Proposals) already fetched its list before this selection changed, and
  // nothing would otherwise tell it to fetch again. This reuses the same
  // mechanism the header's manual refresh button triggers, so switching
  // organizations here behaves exactly like clicking that button: the
  // current page re-fetches, now carrying the new X-Acting-Org-Id.
  triggerManualRefresh()
}

export function subscribeActingOrg(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}