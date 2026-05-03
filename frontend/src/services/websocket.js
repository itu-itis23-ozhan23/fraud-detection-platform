const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'

let socket = null
const listeners = new Set()

// ── Browser Notifications ────────────────────────────────────────────────────

export async function requestNotificationPermission() {
  if (!('Notification' in window)) return false
  if (Notification.permission === 'granted') return true
  const result = await Notification.requestPermission()
  return result === 'granted'
}

function showFraudNotification(alert) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return

  const reasonLabels = {
    velocity_exceeded: '⚡ Velocity',
    amount_exceeded: '💰 Amount',
    impossible_travel: '✈️ Travel',
  }
  const reasons = (alert.fraud_reasons || []).map(r => reasonLabels[r] || r).join(', ')

  const n = new Notification(`🚨 Fraud Alert — ${alert.user_id}`, {
    body: `₺${Number(alert.amount).toLocaleString('tr-TR')} @ ${alert.location}\n${reasons}`,
    icon: '/favicon.ico',
    tag: alert.id,
    requireInteraction: false,
  })

  n.onclick = () => { window.focus(); n.close() }
  setTimeout(() => n.close(), 6000)
}

export function connectWebSocket() {
  if (socket && socket.readyState === WebSocket.OPEN) return

  socket = new WebSocket(WS_URL)

  socket.onopen = () => {
    console.log('[WS] Connected')
    notifyListeners({ type: 'connection', status: 'connected' })
  }

  socket.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      // Fire browser notification for fraud alerts
      if (msg.type === 'alert' && msg.data) {
        showFraudNotification(msg.data)
      }
      notifyListeners(msg)
    } catch (e) {
      console.error('[WS] Parse error', e)
    }
  }

  socket.onclose = () => {
    console.log('[WS] Disconnected — reconnecting in 3s...')
    notifyListeners({ type: 'connection', status: 'disconnected' })
    setTimeout(connectWebSocket, 3000)
  }

  socket.onerror = (err) => {
    console.error('[WS] Error', err)
  }
}

function notifyListeners(msg) {
  listeners.forEach(fn => fn(msg))
}

export function addMessageListener(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function sendPing() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send('ping')
  }
}
