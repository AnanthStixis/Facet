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
    // The browser's back-forward cache (bfcache) is a distinct mechanism
    // from HTTP caching or React state: on a back/forward navigation, Chrome
    // and Safari can restore a fully-rendered page — DOM, React state, and
    // all — straight from memory, running no JavaScript and making no
    // network request at all. `cache: 'no-store'` on the fetch itself does
    // nothing here, because no fetch happens; the page simply reappears
    // exactly as it looked when the user navigated away, however stale that
    // now is. `pageshow` with `event.persisted === true` is the one signal
    // that fires specifically for this case (a normal load does not set
    // `persisted`), so it's the only reliable way to force a refetch when it
    // happens.
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) load()
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    window.addEventListener(REFRESH_EVENT, load)
    window.addEventListener('pageshow', onPageShow)
    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, pollMs)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
      window.removeEventListener(REFRESH_EVENT, load)
      window.removeEventListener('pageshow', onPageShow)
      window.clearInterval(interval)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, pollMs])
}
