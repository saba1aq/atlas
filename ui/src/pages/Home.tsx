import { Link } from 'react-router-dom'
import { Database } from 'lucide-react'
import { useSite } from '../lib/hooks'

export default function Home() {
  const site = useSite()
  const resources = site.data?.resources ?? []
  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-1 text-xl font-semibold tracking-tight">Overview</h1>
      <p className="mb-6 text-sm text-muted">{resources.length} resources registered.</p>
      <div className="stagger grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {resources.map((r) => (
          <Link key={r.key} to={`/${r.key}`} className="pressable flex items-center gap-3 rounded-lg border bg-surface p-4 [@media(hover:hover)]:hover:border-accent">
            <span className="rounded-md bg-accent/15 p-2 text-accent"><Database size={18} /></span>
            <span>
              <span className="block font-medium">{r.label_plural}</span>
              <span className="block text-xs text-muted">/{r.key}</span>
            </span>
          </Link>
        ))}
      </div>
    </div>
  )
}
