import { useState, useEffect, useRef } from 'react'
import { format } from 'date-fns'
import { addMessageListener } from '../services/websocket'

const MAX_ITEMS = 100

const REASON_LABELS = {
  velocity_exceeded:  { text: '⚡ Velocity', cls: 'bg-orange-900/50 text-orange-300 border-orange-700' },
  amount_exceeded:    { text: '💰 Amount',   cls: 'bg-yellow-900/50 text-yellow-300 border-yellow-700' },
  impossible_travel:  { text: '✈️ Travel',   cls: 'bg-purple-900/50 text-purple-300 border-purple-700' },
  ml_isolation_forest:{ text: '🤖 ML',       cls: 'bg-blue-900/50 text-blue-300 border-blue-700' },
}

function ReasonBadge({ reason }) {
  const r = REASON_LABELS[reason] ?? { text: reason.replace(/_/g, ' '), cls: 'bg-gray-700 text-gray-300 border-gray-600' }
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium whitespace-nowrap ${r.cls}`}>
      {r.text}
    </span>
  )
}

function TxRow({ tx, isNew }) {
  const isSuspicious = tx.status === 'SUSPICIOUS'
  const isPending = tx.status === 'PENDING'

  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 border-b border-gray-800/50 transition-all duration-500
        ${isNew ? 'bg-gray-800/60' : 'bg-transparent'}
        ${isSuspicious ? 'border-l-2 border-l-red-500' : isPending ? 'border-l-2 border-l-yellow-500' : 'border-l-2 border-l-green-600'}`}
    >
      {/* Status icon */}
      <div className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 text-sm mt-0.5">
        {isSuspicious ? '🚨' : isPending ? '⏳' : '✅'}
      </div>

      {/* User + location + badges */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-sm font-semibold text-white truncate">{tx.user_id}</span>
          <div className="text-right flex-shrink-0">
            <div className={`text-sm font-bold ${isSuspicious ? 'text-red-400' : 'text-white'}`}>
              ₺{Number(tx.amount).toLocaleString('tr-TR', { minimumFractionDigits: 2 })}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 mt-0.5">
          <div className="flex items-center gap-1.5 text-xs text-gray-500 min-w-0">
            <span className="truncate">📍 {tx.location}</span>
            <span>·</span>
            <span className="flex-shrink-0">{tx.timestamp ? format(new Date(tx.timestamp), 'HH:mm:ss') : '—'}</span>
          </div>
          <div className="flex-shrink-0">
            {isSuspicious
              ? <span className="badge-suspicious text-[10px]">Score: {tx.fraud_score}</span>
              : isPending
              ? <span className="badge-pending text-[10px]">⏳ Pending</span>
              : <span className="badge-approved text-[10px]">✓ Approved</span>
            }
          </div>
        </div>

        {/* Reason badges — own row so they never overlap */}
        {isSuspicious && tx.fraud_reasons?.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {tx.fraud_reasons.map(r => <ReasonBadge key={r} reason={r} />)}
          </div>
        )}
      </div>
    </div>
  )
}

export default function TransactionStream({ onUserSelect }) {
  const [transactions, setTransactions] = useState([])
  const [newId, setNewId] = useState(null)
  const [filter, setFilter] = useState('ALL') // ALL | SUSPICIOUS | APPROVED
  const bottomRef = useRef(null)

  useEffect(() => {
    const remove = addMessageListener((msg) => {
      if (msg.type === 'transaction') {
        const tx = msg.data
        setTransactions(prev => {
          // Upsert: update existing or prepend
          const idx = prev.findIndex(t => t.id === tx.id)
          if (idx >= 0) {
            const updated = [...prev]
            updated[idx] = tx
            return updated
          }
          return [tx, ...prev].slice(0, MAX_ITEMS)
        })
        setNewId(tx.id)
        setTimeout(() => setNewId(null), 1500)
      }
    })
    return remove
  }, [])

  const filtered = filter === 'ALL'
    ? transactions
    : transactions.filter(t => t.status === filter)

  return (
    <div className="card flex flex-col h-full">
      {/* Header */}
      <div className="mb-3">
        <div className="flex items-center gap-2 mb-2">
          <span className="w-2 h-2 rounded-full bg-green-400 live-dot flex-shrink-0" />
          <h2 className="font-semibold text-white truncate">Live Transaction Stream</h2>
          <span className="text-xs text-gray-500 flex-shrink-0">{filtered.length} shown</span>
        </div>
        <div className="flex gap-1">
          {['ALL', 'SUSPICIOUS', 'APPROVED'].map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`flex-1 text-xs py-1 rounded-full border transition-colors
                ${filter === f
                  ? f === 'SUSPICIOUS' ? 'bg-red-900 border-red-700 text-red-300'
                    : f === 'APPROVED' ? 'bg-green-900 border-green-700 text-green-300'
                    : 'bg-blue-900 border-blue-700 text-blue-300'
                  : 'bg-transparent border-gray-700 text-gray-400 hover:border-gray-500'}`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Stream */}
      <div className="flex-1 overflow-y-auto -mx-4 rounded-lg">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-gray-600">
            <span className="text-3xl mb-2">📭</span>
            <span className="text-sm">Waiting for transactions…</span>
          </div>
        ) : (
          filtered.map(tx => (
            <div key={tx.id} onClick={() => onUserSelect(tx.user_id)} className="cursor-pointer hover:bg-gray-800/40">
              <TxRow tx={tx} isNew={tx.id === newId} />
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
