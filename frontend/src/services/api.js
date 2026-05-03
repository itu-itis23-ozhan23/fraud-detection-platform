import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const api = axios.create({ baseURL: BASE_URL })

export const fetchFrauds = (params = {}) =>
  api.get('/api/v1/frauds/', { params }).then(r => r.data)

export const fetchUserStatus = (userId) =>
  api.get(`/api/v1/users/${userId}/status`).then(r => r.data)

export const submitTransaction = (payload) =>
  api.post('/api/v1/transactions/', payload).then(r => r.data)

export default api
