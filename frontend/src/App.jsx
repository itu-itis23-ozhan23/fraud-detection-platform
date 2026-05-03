import { useState, useEffect } from 'react'
import { connectWebSocket, addMessageListener, sendPing } from './services/websocket'
import Header from './components/Header'
import TransactionStream from './components/TransactionStream'
import FraudChart from './components/FraudChart'
import AlertPanel from './components/AlertPanel'
import UserDetail from './components/UserDetail'
import AnomalySimulator from './components/AnomalySimulator'

export default function App() {
  const [selectedUser, setSelectedUser] = useState(null)
  const [stats, setStats] = useState({ total: 0, suspicious: 0, approved: 0 })
  const [activeTab, setActiveTab] = useState('dashboard') // dashboard | user | simulator

  // Boot WebSocket
  useEffect(() => {
    connectWebSocket()

    // Keep-alive ping
    const ping = setInterval(sendPing, 30_000)

    // Aggregate stats
    const remove = addMessageListener((msg) => {
      if (msg.type === 'transaction') {
        const tx = msg.data
        setStats(prev => {
          const isUpdate = tx.status !== 'PENDING'
          if (isUpdate) {
            return {
              total: prev.total + 1,
              suspicious: prev.suspicious + (tx.status === 'SUSPICIOUS' ? 1 : 0),
              approved: prev.approved + (tx.status === 'APPROVED' ? 1 : 0),
            }
          }
          return prev
        })
      }
    })

    return () => { clearInterval(ping); remove() }
  }, [])

  const handleUserSelect = (userId) => {
    setSelectedUser(userId)
    setActiveTab('user')
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-950">
      <Header stats={stats} />

      {/* Mobile tab nav */}
      <div className="md:hidden flex border-b border-gray-800 bg-gray-900">
        {[
          { id: 'dashboard', label: '📊 Dashboard' },
          { id: 'simulator', label: '🎮 Simulator' },
          { id: 'user', label: '👤 User' },
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 py-3 text-sm font-medium transition-colors
              ${activeTab === tab.id ? 'text-white border-b-2 border-blue-500' : 'text-gray-500'}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Main layout */}
      <main className="flex-1 p-4 max-w-screen-2xl mx-auto w-full">
        {/* Desktop: 4-column grid (3+3+3+3) */}
        <div className="hidden md:grid grid-cols-12 gap-4 h-[calc(100vh-80px)]">
          {/* Left: Transaction stream */}
          <div className="col-span-3 overflow-hidden">
            <TransactionStream onUserSelect={handleUserSelect} />
          </div>

          {/* Center-left: Charts + Alerts */}
          <div className="col-span-3 overflow-y-auto space-y-4">
            <FraudChart />
            <AlertPanel onUserSelect={handleUserSelect} />
          </div>

          {/* Center-right: Simulator */}
          <div className="col-span-3 overflow-hidden">
            <AnomalySimulator />
          </div>

          {/* Right: User detail */}
          <div className="col-span-3 overflow-hidden">
            <UserDetail userId={selectedUser} />
          </div>
        </div>

        {/* Mobile: single panel */}
        <div className="md:hidden h-[calc(100vh-130px)]">
          {activeTab === 'dashboard' && (
            <div className="space-y-4 overflow-y-auto h-full">
              <div className="h-80">
                <TransactionStream onUserSelect={handleUserSelect} />
              </div>
              <FraudChart />
              <AlertPanel onUserSelect={handleUserSelect} />
            </div>
          )}
          {activeTab === 'simulator' && <AnomalySimulator />}
          {activeTab === 'user' && (
            <UserDetail userId={selectedUser} onClose={() => setActiveTab('dashboard')} />
          )}
        </div>
      </main>
    </div>
  )
}
