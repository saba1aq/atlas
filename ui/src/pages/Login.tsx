import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../lib/api'
import { config } from '../lib/config'
import { Button, ErrorBox } from '../components/ui'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      await api('/auth/login', { method: 'POST', body: { username, password } })
      qc.clear()
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <form onSubmit={submit} className="card-enter w-full max-w-sm space-y-4 rounded-xl border bg-surface p-6 shadow-sm">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{config.title}</h1>
          <p className="text-sm text-muted">Sign in to continue</p>
        </div>
        {error && <ErrorBox>{error}</ErrorBox>}
        <label className="block space-y-1 text-sm">
          <span className="text-muted">Username</span>
          <input className="field" autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className="block space-y-1 text-sm">
          <span className="text-muted">Password</span>
          <input className="field" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <Button type="submit" variant="primary" className="w-full justify-center" loading={busy}>Sign in</Button>
      </form>
    </div>
  )
}
