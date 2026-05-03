import { useState, useEffect } from 'react'
import { formatDistanceToNow } from 'date-fns'
import { addMessageListener, requestNotificationPermission } from '../services/websocket'

function exportCSV(alerts) {
  const header = ['timestamp', 'user_id', 'amount', 'location', 'fraud_score', 'fraud_reasons']
  const rows = alerts.map(a => [
    a.timestamp,
    a.user_id,
    a.amount,
    a.location,
    a.fraud_score,
    (a.fraud_reasons || []).join(' | '),
  ])
  const csv = [header, ...rows].map(r => r.join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `fraud-alerts-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

const MAX_ALERTS = 30

const REASON_LABEL = {
  velocity_exceeded: '⚡ Velocity exceeded',
  amount_exceeded: '💰 Amount anomaly',
  impossible_travel: '✈️ Impossible travel',
}

function AlertItem({ alert, onClick }) {
  const ago = formatDistanceToNow(new Date(alert.timestamp), { addSuffix: true })

  return (
    <div
      onClick={() => onClick(alert.user_id)}
      className="group flex gap-3 p-3 rounded-lg bg-red-950/30 border border-red-900/40 hover:border-red-700/60 cursor-pointer transition-colors"
    >
      <div className="w-8 h-8 rounded-full bg-red-900/60 flex items-center justify-center text-sm flex-shrink-0">
        🚨
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-sm font-semibold text-red-300 truncate">{alert.user_id}</span>
          <span className="text-xs text-gray-600 flex-shrink-0">{ago}</span>
        </div>
        <div className="text-xs text-gray-400 mt-0.5">
          ₺{Number(alert.amount).toLocaleString('tr-TR', { minimumFractionDigits: 2 })} · {alert.location}
        </div>
        <div className="flex flex-wrap gap-1 mt-1.5">
          {alert.fraud_reasons?.map(r => (
            <span key={r} className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/40 border border-red-800 text-red-400">
              {REASON_LABEL[r] ?? r}
            </span>
          ))}
        </div>
      </div>
      <div className="flex-shrink-0 text-right">
        <div className="text-xs font-semibold text-red-400">Score</div>
        <div className="text-lg font-bold text-red-300">{alert.fraud_score}</div>
      </div>
    </div>
  )
}

export default function AlertPanel({ onUserSelect }) {
  const [alerts, setAlerts] = useState([])
  const [notifGranted, setNotifGranted] = useState(
    typeof Notification !== 'undefined' && Notification.permission === 'granted'
  )

  const handleEnableNotifications = async () => {
    const granted = await requestNotificationPermission()
    setNotifGranted(granted)
  }

  useEffect(() => {
    const remove = addMessageListener((msg) => {
      if (msg.type === 'alert') {
        setAlerts(prev => [msg.data, ...prev].slice(0, MAX_ALERTS))
      }
    })
    return remove
  }, [])

  return (
    <div className="card flex flex-col h-full">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {alerts.length > 0 && (
            <span className="w-2 h-2 rounded-full bg-red-500 live-dot" />
          )}
          <h2 className="font-semibold text-white">Alert Panel</h2>
          {alerts.length > 0 && (
            <span className="px-2 py-0.5 rounded-full bg-red-900/60 border border-red-700 text-red-300 text-xs font-bold">
              {alerts.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Browser notification toggle */}
          {!notifGranted && (
            <button
              onClick={handleEnableNotifications}
              title="Enable browser notifications for fraud alerts"
              className="text-xs px-2 py-1 rounded-lg border border-yellow-700 bg-yellow-900/30 text-yellow-400 hover:bg-yellow-900/50 transition-colors"
            >
              🔔 Enable alerts
            </button>
          )}
          {notifGranted && (
            <span className="text-xs text-green-500" title="Browser notifications active">🔔 On</span>
          )}
          {/* CSV Export */}
          {alerts.length > 0 && (
            <button
              onClick={() => exportCSV(alerts)}
              className="text-xs px-2 py-1 rounded-lg border border-gray-700 bg-gray-800 text-gray-400 hover:text-white hover:border-gray-500 transition-colors"
            >
              ↓ CSV
            </button>
          )}
          {alerts.length > 0 && (
            <button
              onClick={() => setAlerts([])}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-2">
        {alerts.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-gray-600">
            <span className="text-3xl mb-2">🔒</span>
            <span className="text-sm">No alerts — system clean</span>
          </div>
        ) : (
          alerts.map((alert, i) => (
            <AlertItem key={`${alert.id}-${i}`} alert={alert} onClick={onUserSelect} />
          ))
        )}
      </div>
    </div>
  )
}
