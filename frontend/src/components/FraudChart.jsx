import { useState, useEffect, useCallback } from 'react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Legend,
} from 'recharts'
import { format, subMinutes } from 'date-fns'
import { addMessageListener } from '../services/websocket'

const WINDOW_MINUTES = 10
const BUCKET_SECONDS = 30

function buildEmptyBuckets() {
  // Round "now" to the nearest bucket boundary so keys always match bucketKey()
  const bucketMs = BUCKET_SECONDS * 1000
  const now = Math.floor(Date.now() / bucketMs) * bucketMs
  const buckets = []
  const total = (WINDOW_MINUTES * 60) / BUCKET_SECONDS
  for (let i = total - 1; i >= 0; i--) {
    const ts = now - i * bucketMs
    buckets.push({
      time: format(new Date(ts), 'HH:mm:ss'),
      ts,
      approved: 0,
      suspicious: 0,
      total: 0,
    })
  }
  return buckets
}

function bucketKey(ts) {
  return Math.floor(ts / (BUCKET_SECONDS * 1000)) * BUCKET_SECONDS * 1000
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs">
      <p className="text-gray-400 mb-1">{label}</p>
      {payload.map(p => (
        <p key={p.name} style={{ color: p.color }}>{p.name}: <strong>{p.value}</strong></p>
      ))}
    </div>
  )
}

export default function FraudChart() {
  const [buckets, setBuckets] = useState(buildEmptyBuckets)
  const [locationStats, setLocationStats] = useState({})

  const addTransaction = useCallback((tx) => {
    const txTs = new Date(tx.timestamp || tx.processed_at || Date.now()).getTime()
    const key = bucketKey(txTs)

    setBuckets(prev => {
      const updated = prev.map(b => {
        if (b.ts === key) {
          return {
            ...b,
            approved: b.approved + (tx.status === 'APPROVED' ? 1 : 0),
            suspicious: b.suspicious + (tx.status === 'SUSPICIOUS' ? 1 : 0),
            total: b.total + 1,
          }
        }
        return b
      })

      // Slide window: if the current transaction falls outside all existing buckets,
      // add a new bucket for it so it gets counted
      const matched = updated.some(b => b.ts === key)
      if (!matched) {
        updated.push({ time: format(new Date(key), 'HH:mm:ss'), ts: key, approved: tx.status === 'APPROVED' ? 1 : 0, suspicious: tx.status === 'SUSPICIOUS' ? 1 : 0, total: 1 })
        // Keep only the last WINDOW_MINUTES worth of buckets
        const cutoff = Date.now() - WINDOW_MINUTES * 60 * 1000
        return updated.filter(b => b.ts >= cutoff).sort((a, b) => a.ts - b.ts)
      }

      return updated
    })

    // Location stats
    if (tx.location) {
      setLocationStats(prev => ({
        ...prev,
        [tx.location]: {
          name: tx.location,
          total: (prev[tx.location]?.total || 0) + 1,
          suspicious: (prev[tx.location]?.suspicious || 0) + (tx.status === 'SUSPICIOUS' ? 1 : 0),
        },
      }))
    }
  }, [])

  useEffect(() => {
    const remove = addMessageListener((msg) => {
      if (msg.type === 'transaction') addTransaction(msg.data)
    })

    // Refresh bucket window every 30s
    const timer = setInterval(() => {
      setBuckets(prev => {
        const now = Date.now()
        const cutoff = now - WINDOW_MINUTES * 60 * 1000
        const fresh = prev.filter(b => b.ts >= cutoff)
        const latest = fresh[fresh.length - 1]
        if (latest && now - latest.ts > BUCKET_SECONDS * 1000) {
          const newTs = latest.ts + BUCKET_SECONDS * 1000
          fresh.push({ time: format(new Date(newTs), 'HH:mm:ss'), ts: newTs, approved: 0, suspicious: 0, total: 0 })
        }
        return fresh
      })
    }, BUCKET_SECONDS * 1000)

    return () => { remove(); clearInterval(timer) }
  }, [addTransaction])

  const locationData = Object.values(locationStats)
    .sort((a, b) => b.total - a.total)
    .slice(0, 8)

  return (
    <div className="space-y-4">
      {/* Time series */}
      <div className="card">
        <h2 className="font-semibold text-white mb-4">
          Transaction Rate <span className="text-xs text-gray-500 font-normal ml-1">(last {WINDOW_MINUTES} min, {BUCKET_SECONDS}s buckets)</span>
        </h2>
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={buckets} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="colorSuspicious" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#ef4444" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="colorApproved" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#6b7280' }} tickLine={false} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: '#6b7280' }} tickLine={false} axisLine={false} />
            <Tooltip content={<CustomTooltip />} />
            <Area type="monotone" dataKey="approved" stroke="#22c55e" strokeWidth={2} fill="url(#colorApproved)" name="Approved" />
            <Area type="monotone" dataKey="suspicious" stroke="#ef4444" strokeWidth={2} fill="url(#colorSuspicious)" name="Suspicious" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Location breakdown */}
      {locationData.length > 0 && (
        <div className="card">
          <h2 className="font-semibold text-white mb-4">Transactions by Location</h2>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={locationData} margin={{ top: 0, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#6b7280' }} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: '#6b7280' }} tickLine={false} axisLine={false} />
              <Tooltip content={<CustomTooltip />} />
              <Legend wrapperStyle={{ fontSize: 11, color: '#9ca3af' }} />
              <Bar dataKey="total" fill="#3b82f6" name="Total" radius={[3, 3, 0, 0]} />
              <Bar dataKey="suspicious" fill="#ef4444" name="Suspicious" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
