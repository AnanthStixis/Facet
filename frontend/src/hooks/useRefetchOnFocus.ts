import { useEffect } from 'react'

// Dispatched by the manual refresh button in the app header. Any page using
// this hook picks it up automatically — one button, every page, no per-page
// wiring needed.
export const REFRESH_EVENT = 'app:refresh'

export function triggerManualRefresh() {
  window.dispatchEvent(new Event(REFRESH_EVENT))
}

/**
 * Re-runs `load` whenever this tab becomes the active one again, and on a
 * background interval while it stays visible.
 *
 * A page fetched once on mount goes stale the moment something changes it
 * from elsewhere — another tab, another user, or an admin action a few
 * clicks away in the same session. Focus/visibility alone misses the case
 * where someone is sitting on the page watching for something to change
 * (an employee waiting on "My feedback" while a manager opens a cycle) —
 * they never leave the tab, so focus never re-fires. The interval covers
 * that without resorting to a websocket for what is, in practice, a couple
 * of requests a minute.
 */
export function useRefetchOnFocus(load: () => void, pollMs = 20_000) {
  useEffect(() => {
    const onFocus = () => {
      if (document.visibilityState === 'visible') load()
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    window.addEventListener(REFRESH_EVENT, load)
    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, pollMs)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
      window.removeEventListener(REFRESH_EVENT, load)
      window.clearInterval(interval)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, pollMs])
}
