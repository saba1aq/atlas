import { useEffect } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Database, LogOut, Menu } from 'lucide-react'
import { useState } from 'react'
import { useSite } from '../lib/hooks'
import { api, ApiError } from '../lib/api'
import { Spinner } from './ui'
import { ConfirmProvider } from './Confirm'

export default function Layout() {
  const site = useSite()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (site.error instanceof ApiError && site.error.status === 401) navigate('/login', { replace: true })
  }, [site.error, navigate])

  if (site.isPending) return <Spinner />
  if (!site.data) return <div className="p-6 text-danger">Failed to load admin: {String(site.error)}</div>

  const logout = async () => {
    await api('/auth/logout', { method: 'POST' })
    qc.clear()
    navigate('/login')
  }

  const nav = (
    <nav className="flex flex-col gap-0.5 p-2">
      {site.data.resources.map((r) => (
        <NavLink
          key={r.key}
          to={`/${r.key}`}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            `pressable flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm ${isActive ? 'bg-accent/15 font-medium text-accent' : 'text-fg hoverable'}`
          }
        >
          <Database size={14} className="shrink-0 opacity-60" />
          {r.label_plural}
        </NavLink>
      ))}
    </nav>
  )

  return (
    <ConfirmProvider>
      <div className="flex h-full">
        <aside data-open={open ? 'true' : 'false'} className="drawer fixed inset-y-0 left-0 z-30 flex w-60 flex-col border-r bg-surface md:static">
          <NavLink to="/" className="flex h-12 items-center border-b px-4 font-semibold tracking-tight" onClick={() => setOpen(false)}>
            {site.data.title}
          </NavLink>
          <div className="flex-1 overflow-y-auto">{nav}</div>
          {site.data.user && (
            <div className="flex items-center justify-between border-t px-3 py-2 text-xs text-muted">
              <span className="truncate">{site.data.user.display_name}</span>
              <button onClick={logout} className="pressable pressable-sm rounded p-1 hoverable" title="Log out" aria-label="Log out"><LogOut size={14} /></button>
            </div>
          )}
        </aside>
        <div data-open={open ? 'true' : 'false'} className="drawer-overlay fixed inset-0 z-20 bg-black/30 md:hidden" onClick={() => setOpen(false)} />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-12 items-center gap-2 border-b bg-surface px-4 md:hidden">
            <button onClick={() => setOpen(true)} className="pressable pressable-sm rounded p-1 hoverable" aria-label="Menu"><Menu size={18} /></button>
            <span className="font-semibold">{site.data.title}</span>
          </header>
          <main className="min-w-0 flex-1 overflow-auto p-4 md:p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </ConfirmProvider>
  )
}
