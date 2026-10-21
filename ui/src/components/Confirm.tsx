import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { Button } from './ui'

interface Options { title: string; body?: string; confirmLabel?: string; danger?: boolean }
type Ask = (o: Options) => Promise<boolean>
const Ctx = createContext<Ask>(async () => false)
export const useConfirm = () => useContext(Ctx)

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ o: Options; resolve: (v: boolean) => void } | null>(null)
  const ask = useCallback<Ask>((o) => new Promise((resolve) => setState({ o, resolve })), [])
  const close = (v: boolean) => { state?.resolve(v); setState(null) }
  useEffect(() => {
    if (!state) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state])
  return (
    <Ctx.Provider value={ask}>
      {children}
      {state && (
        <div className="modal-overlay fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" onClick={() => close(false)}>
          <div className="modal w-full max-w-sm rounded-xl border bg-surface p-5 shadow-2xl" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
            <h2 className="text-base font-semibold">{state.o.title}</h2>
            {state.o.body && <p className="mt-2 text-sm text-muted">{state.o.body}</p>}
            <div className="mt-5 flex justify-end gap-2">
              <Button onClick={() => close(false)} autoFocus>Cancel</Button>
              <Button variant={state.o.danger ? 'danger' : 'primary'} onClick={() => close(true)}>{state.o.confirmLabel ?? 'Confirm'}</Button>
            </div>
          </div>
        </div>
      )}
    </Ctx.Provider>
  )
}
