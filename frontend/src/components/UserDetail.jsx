import { useState, useEffect } from 'react'
import { format } from 'date-fns'
import { fetchUserStatus } from '../services/api'

const REASON_LABEL = {
  velocity_exceeded:   { text: '⚡ Velocity', cls: 'bg-orange-900/50 text-orange-300 border-orange-700' },
  amount_exceeded:     { text: '💰 Amount',   cls: 'bg-yellow-900/50 text-yellow-300 border-yellow-700' },
  impossible_travel:   { text: '✈️ Travel',   cls: 'bg-purple-900/50 text-purple-300 border-purple-700' },
  ml_isolation_forest: { text: '🤖 ML',       cls: 'bg-blue-900/50 text-blue-300 border-blue-700' },
}

function ReasonBadge({ reason }) {
  const r = REASON_LABEL[reason] ?? { text: reason.replace(/_/g, ' '), cls: 'bg-gray-700 text-gray-300 border-gray-600' }
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium whitespace-nowrap ${r.cls}`}>
      {r.text}
    </span>
  )
}

export default function UserDetail({ userId, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState(userId || '')
  const [queried, setQueried] = useState(userId || '')

  const load = async (uid) => {
    if (!uid) return
    setLoading(true)
    setError(null)
    try {
      const result = await fetchUserStatus(uid)
      setData(result)
    } catch (e) {
      setError(e.response?.data?.detail ?? 'User not found or no transactions.')
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(queried) }, [queried])

  useEffect(() => {
    if (userId) { setSearch(userId); setQueried(userId) }
  }, [userId])

  const riskClass = data?.risk_level === 'HIGH' ? 'risk-high'
    : data?.risk_level === 'MEDIUM' ? 'risk-medium' : 'risk-low'

  return (
    <div className="card flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold text-white">User Analysis</h2>
        {onClose && (
          <button onClick={onClose} className="text-gray-500 hover:text-white text-xl leading-none">×</button>
        )}
      </div>

      {/* Search bar */}
      <div className="flex gap-2 mb-4">
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && setQueried(search)}
          placeholder="Enter user ID…"
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
        />
        <button
          onClick={() => setQueried(search)}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg font-medium transition-colors"
        >
          Search
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {!queried && !loading && (
          <div className="flex flex-col items-center justify-center h-48 text-gray-600">
            <span className="text-4xl mb-3">👤</span>
            <span className="text-sm text-center">Enter a user ID above or click<br/>a transaction in the stream</span>
          </div>
        )}

        {loading && (
          <div className="flex items-center justify-center h-40 text-gray-500">
            <span className="animate-spin text-2xl mr-2">⏳</span> Loading…
          </div>
        )}

        {error && !loading && (
          <div className="flex flex-col items-center justify-center h-40 text-gray-500">
            <span className="text-3xl mb-2">🔍</span>
            <span className="text-sm text-center">{error}</span>
          </div>
        )}

        {data && !loading && (
          <div className="space-y-3">
            {/* Risk summary */}
            <div className={`p-3 rounded-xl border ${
              data.risk_level === 'HIGH'   ? 'bg-red-950/30 border-red-800' :
              data.risk_level === 'MEDIUM' ? 'bg-orange-950/30 border-orange-800' :
                                             'bg-green-950/20 border-green-800'
            }`}>
              <div className="flex items-center justify-between mb-2">
                <div className="min-w-0">
                  <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-0.5">Risk Level</div>
                  <div className={`text-xl font-black ${riskClass}`}>{data.risk_level}</div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-0.5">Fraud Rate</div>
                  <div className="text-xl font-black text-white">
                    {data.total_transactions > 0
                      ? `${((data.suspicious_transactions / data.total_transactions) * 100).toFixed(1)}%`
                      : '—'}
                  </div>
                </div>
              </div>
              <div className="flex gap-2">
                <Stat label="Total Tx"   value={data.total_transactions} />
                <Stat label="Suspicious" value={data.suspicious_transactions} danger />
              </div>
            </div>

            {/* Recent transactions */}
            <div>
              <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Recent Transactions</div>
              <div className="space-y-1">
                {data.recent_transactions.map(tx => (
                  <div
                    key={tx.id}
                    className={`px-2.5 py-2 rounded-lg text-xs
                      ${tx.status === 'SUSPICIOUS'
                        ? 'bg-red-950/30 border border-red-900/40'
                        : 'bg-gray-800/40 border border-gray-800'}`}
                  >
                    {/* Row 1: icon + amount + location + date */}
                    <div className="flex items-center gap-2">
                      <span className="flex-shrink-0">
                        {tx.status === 'SUSPICIOUS' ? '🚨' : tx.status === 'PENDING' ? '⏳' : '✅'}
                      </span>
                      <span className="font-semibold text-gray-200 flex-shrink-0">
                        ₺{Number(tx.amount).toLocaleString('tr-TR', { minimumFractionDigits: 2 })}
                      </span>
                      <span className="text-gray-500 truncate">{tx.location}</span>
                      <span className="text-gray-600 flex-shrink-0 ml-auto">
                        {tx.timestamp ? format(new Date(tx.timestamp), 'dd/MM HH:mm') : '—'}
                      </span>
                    </div>
                    {/* Row 2: reason badges (only if suspicious) */}
                    {tx.fraud_reasons?.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5 pl-5">
                        {tx.fraud_reasons.map(r => <ReasonBadge key={r} reason={r} />)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, danger }) {
  return (
    <div className="flex-1 bg-gray-900/50 rounded-lg p-2 text-center">
      <div className="text-[10px] text-gray-500">{label}</div>
      <div className={`text-base font-bold ${danger ? 'text-red-400' : 'text-white'}`}>{value}</div>
    </div>
  )
}
