import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import { X } from 'lucide-react'

type Kind = 'info' | 'success' | 'error'
interface Toast { id: number; kind: Kind; text: string; leaving?: boolean }
const Ctx = createContext<(text: string, kind?: Kind) => void>(() => {})

export const useToast = () => useContext(Ctx)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const seq = useRef(0)
  const remove = useCallback((id: number) => {
    setItems((xs) => xs.map((t) => (t.id === id ? { ...t, leaving: true } : t)))
    setTimeout(() => setItems((xs) => xs.filter((t) => t.id !== id)), 200)
  }, [])
  const push = useCallback((text: string, kind: Kind = 'info') => {
    const id = ++seq.current
    setItems((xs) => [...xs, { id, kind, text }])
    setTimeout(() => remove(id), 4500)
  }, [remove])
  const colors: Record<Kind, string> = {
    info: 'border-border', success: 'border-success', error: 'border-danger',
  }
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-80 flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} data-leaving={t.leaving ? 'true' : 'false'} className={`toast pointer-events-auto flex items-start gap-2 rounded-lg border border-l-4 bg-surface px-3 py-2.5 shadow-lg ${colors[t.kind]}`}>
            <span className="flex-1 text-sm leading-5">{t.text}</span>
            <button onClick={() => remove(t.id)} className="pressable pressable-sm rounded p-0.5 text-muted hoverable" aria-label="Dismiss"><X size={14} /></button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
