import { useState, useEffect } from 'react'
import { addMessageListener } from '../services/websocket'

export default function Header({ stats }) {
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    const remove = addMessageListener((msg) => {
      if (msg.type === 'connection') {
        setConnected(msg.status === 'connected')
      }
    })
    return remove
  }, [])

  return (
    <header className="bg-gray-900 border-b border-gray-800 px-6 py-4">
      <div className="max-w-screen-2xl mx-auto flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-red-600 flex items-center justify-center text-lg font-bold">
            🛡️
          </div>
          <div>
            <h1 className="text-lg font-bold text-white leading-none">Fraud Detection</h1>
            <p className="text-xs text-gray-500">Real-time E-Commerce Anomaly Platform</p>
          </div>
        </div>

        {/* Stats pills */}
        <div className="hidden md:flex items-center gap-4">
          <StatPill label="Total"      value={stats.total}     color="blue" />
          <StatPill label="Suspicious" value={stats.suspicious} color="red" />
          <StatPill label="Approved"   value={stats.approved}  color="green" />
          <StatPill
            label="Fraud Rate"
            value={stats.total > 0 ? `${((stats.suspicious / stats.total) * 100).toFixed(1)}%` : '0%'}
            color="orange"
          />
        </div>

        {/* Connection indicator */}
        <div className="flex items-center gap-2 text-sm">
          <span className={`w-2 h-2 rounded-full live-dot ${connected ? 'bg-green-400' : 'bg-red-500'}`} />
          <span className={connected ? 'text-green-400' : 'text-red-400'}>
            {connected ? 'Live' : 'Reconnecting…'}
          </span>
        </div>
      </div>
    </header>
  )
}

function StatPill({ label, value, color }) {
  const colors = {
    blue:   'bg-blue-900/50 text-blue-300 border-blue-700',
    red:    'bg-red-900/50 text-red-300 border-red-700',
    green:  'bg-green-900/50 text-green-300 border-green-700',
    orange: 'bg-orange-900/50 text-orange-300 border-orange-700',
  }
  return (
    <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium ${colors[color]}`}>
      <span className="text-gray-400">{label}</span>
      <span className="font-bold">{value ?? '—'}</span>
    </div>
  )
}
