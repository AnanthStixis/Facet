import type { ReactNode } from 'react'
import { Toaster, toast as sonnerToast } from 'sonner'
import { useAuth } from '../store/auth'

type ToastTone = 'success' | 'critical' | 'warning'

interface ToastContextValue {
  show: (tone: ToastTone, title: string, detail?: string) => void
}

/** Renders Sonner's toast viewport. `useToast()` below is the app-facing
 * API — kept stable across the Sonner swap so none of its ~15 call sites
 * had to change. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const theme = useAuth((state) => state.theme)
  return (
    <>
      {children}
      <Toaster
        position="bottom-center"
        theme={theme}
        richColors
        closeButton
        toastOptions={{
          className: 'font-sans',
        }}
      />
    </>
  )
}

export function useToast(): ToastContextValue {
  return {
    show: (tone, title, detail) => {
      const options = detail ? { description: detail } : undefined
      if (tone === 'success') sonnerToast.success(title, options)
      else if (tone === 'critical') sonnerToast.error(title, options)
      else sonnerToast.warning(title, options)
    },
  }
}
