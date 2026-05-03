import { useState } from 'react'
import { submitTransaction } from '../services/api'

const CITIES = [
  { name: 'Istanbul', lat: 41.0082, lon: 28.9784 },
  { name: 'Ankara', lat: 39.9334, lon: 32.8597 },
  { name: 'Izmir', lat: 38.4192, lon: 27.1287 },
  { name: 'Antalya', lat: 36.8969, lon: 30.7133 },
  { name: 'Bursa', lat: 40.1826, lon: 29.0665 },
  { name: 'Trabzon', lat: 41.0015, lon: 39.7178 },
]

const rand = (min, max) => +(Math.random() * (max - min) + min).toFixed(2)
const randCity = () => CITIES[Math.floor(Math.random() * CITIES.length)]
const sleep = (ms) => new Promise(r => setTimeout(r, ms))

const SCENARIOS = [
  {
    id: 'velocity',
    label: '⚡ Velocity Burst',
    description: 'Sends 8 transactions from the same user in ~5 seconds',
    color: 'orange',
    danger: 'border-orange-700 bg-orange-950/30 hover:bg-orange-900/30',
    badge: 'bg-orange-900/60 text-orange-300',
  },
  {
    id: 'amount',
    label: '💰 Giant Amount',
    description: 'Seeds normal amounts, then fires a 6× spike',
    color: 'yellow',
    danger: 'border-yellow-700 bg-yellow-950/30 hover:bg-yellow-900/30',
    badge: 'bg-yellow-900/60 text-yellow-300',
  },
  {
    id: 'travel',
    label: '✈️ Impossible Travel',
    description: 'Istanbul → Antalya within 1 second',
    color: 'purple',
    danger: 'border-purple-700 bg-purple-950/30 hover:bg-purple-900/30',
    badge: 'bg-purple-900/60 text-purple-300',
  },
  {
    id: 'combo',
    label: '🔥 Full Combo',
    description: 'Triggers all three criteria at once (max fraud score)',
    color: 'red',
    danger: 'border-red-700 bg-red-950/40 hover:bg-red-900/40',
    badge: 'bg-red-900/60 text-red-300',
  },
]

function ScenarioButton({ scenario, running, onRun }) {
  const isRunning = running === scenario.id
  return (
    <button
      onClick={() => onRun(scenario.id)}
      disabled={running !== null}
      className={`w-full text-left p-3 rounded-xl border transition-all
        ${running !== null && !isRunning ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}
        ${scenario.danger}`}
    >
      <div className="flex items-center justify-between">
        <span className="font-semibold text-sm text-white">{scenario.label}</span>
        {isRunning ? (
          <span className="text-xs animate-pulse text-white">Running…</span>
        ) : (
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${scenario.badge}`}>
            FIRE
          </span>
        )}
      </div>
      <p className="text-xs text-gray-400 mt-0.5">{scenario.description}</p>
    </button>
  )
}

export default function AnomalySimulator() {
  const [running, setRunning] = useState(null)
  const [log, setLog] = useState([])
  const [userId, setUserId] = useState('sim_user_001')

  const addLog = (msg, type = 'info') => {
    setLog(prev => [{ msg, type, ts: new Date().toLocaleTimeString() }, ...prev].slice(0, 20))
  }

  const send = async (uid, amount, city) => {
    try {
      await submitTransaction({
        user_id: uid,
        amount,
        location: city.name,
        latitude: city.lat,
        longitude: city.lon,
      })
      addLog(`✓ ${uid} → ₺${amount} @ ${city.name}`, 'ok')
    } catch (e) {
      addLog(`✗ Error: ${e.message}`, 'err')
    }
  }

  const runScenario = async (id) => {
    setRunning(id)
    setLog([])
    const uid = userId || 'sim_user_001'

    try {
      if (id === 'velocity') {
        addLog(`⚡ Velocity burst starting for ${uid}…`)
        const city = randCity()
        for (let i = 0; i < 8; i++) {
          await send(uid, rand(50, 300), city)
          await sleep(600)
        }
        addLog('🎯 Velocity burst complete — check stream!', 'ok')
      }

      else if (id === 'amount') {
        addLog(`💰 Seeding normal amounts for ${uid}…`)
        const city = randCity()
        for (const amt of [80, 95, 110, 90, 105]) {
          await send(uid, amt, city)
          await sleep(400)
        }
        const spike = rand(480, 700)
        addLog(`💥 Firing spike: ₺${spike}`)
        await send(uid, spike, city)
        addLog('🎯 Amount spike complete!', 'ok')
      }

      else if (id === 'travel') {
        addLog(`✈️ Istanbul → Antalya for ${uid}…`)
        await send(uid, rand(100, 400), { name: 'Istanbul', lat: 41.0082, lon: 28.9784 })
        await sleep(800)
        await send(uid, rand(100, 400), { name: 'Antalya', lat: 36.8969, lon: 30.7133 })
        addLog('🎯 Impossible travel fired!', 'ok')
      }

      else if (id === 'combo') {
        addLog(`🔥 Full combo for ${uid}…`)
        // Seed amounts
        const city1 = { name: 'Istanbul', lat: 41.0082, lon: 28.9784 }
        for (const amt of [80, 90, 85]) {
          await send(uid, amt, city1)
          await sleep(300)
        }
        // Velocity burst from Istanbul
        for (let i = 0; i < 6; i++) {
          await send(uid, rand(60, 200), city1)
          await sleep(500)
        }
        // Impossible travel + giant amount
        const spike = rand(450, 700)
        addLog(`💥 Teleporting to Trabzon + spike ₺${spike}`)
        await send(uid, spike, { name: 'Trabzon', lat: 41.0015, lon: 39.7178 })
        addLog('🎯 Full combo complete — max fraud score expected!', 'ok')
      }
    } finally {
      setRunning(null)
    }
  }

  return (
    <div className="card flex flex-col h-full">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-lg">🎮</span>
        <h2 className="font-semibold text-white">Anomaly Simulator</h2>
      </div>

      {/* User ID input */}
      <div className="mb-4">
        <label className="text-xs text-gray-500 mb-1 block">Target User ID</label>
        <input
          type="text"
          value={userId}
          onChange={e => setUserId(e.target.value)}
          placeholder="sim_user_001"
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500"
        />
      </div>

      {/* Scenario buttons */}
      <div className="space-y-2 mb-4">
        {SCENARIOS.map(s => (
          <ScenarioButton key={s.id} scenario={s} running={running} onRun={runScenario} />
        ))}
      </div>

      {/* Log */}
      {log.length > 0 && (
        <div className="flex-1 overflow-y-auto bg-gray-950 rounded-lg p-2 font-mono text-xs space-y-0.5 border border-gray-800">
          {log.map((l, i) => (
            <div key={i} className={`flex gap-2
              ${l.type === 'ok' ? 'text-green-400' : l.type === 'err' ? 'text-red-400' : 'text-gray-400'}`}>
              <span className="text-gray-600 flex-shrink-0">{l.ts}</span>
              <span>{l.msg}</span>
            </div>
          ))}
        </div>
      )}

      {log.length === 0 && (
        <div className="flex-1 flex items-center justify-center text-gray-600 text-sm">
          Select a scenario above to fire it
        </div>
      )}
    </div>
  )
}
