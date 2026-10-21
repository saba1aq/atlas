import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Loader2 } from 'lucide-react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
const variants: Record<Variant, string> = {
  primary: 'bg-accent text-accent-fg border-transparent [@media(hover:hover)]:hover:opacity-90',
  secondary: 'bg-surface border hoverable',
  danger: 'bg-surface text-danger border border-danger/40 [@media(hover:hover)]:hover:bg-danger [@media(hover:hover)]:hover:text-white',
  ghost: 'border-transparent hoverable',
}

export function Button({ variant = 'secondary', size = 'md', loading, className = '', children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md'; loading?: boolean }) {
  const pad = size === 'sm' ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm'
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={`pressable inline-flex items-center gap-1.5 rounded-md border font-medium disabled:cursor-not-allowed disabled:opacity-50 ${size === 'sm' ? 'pressable-sm' : ''} ${pad} ${variants[variant]} ${className}`}
    >
      {loading && <Loader2 size={14} className="spin" />}
      {children}
    </button>
  )
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-muted">
      <Loader2 size={16} className="spin" /> {label}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-dashed p-10 text-center text-muted">{children}</div>
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'success' | 'danger' }) {
  const t = { neutral: 'bg-surface-2 text-muted', success: 'bg-success/15 text-success', danger: 'bg-danger/15 text-danger' }[tone]
  return <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${t}`}>{children}</span>
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{children}</div>
}
