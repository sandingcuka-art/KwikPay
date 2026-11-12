import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './TwoPotApp'
import RailwayDashboard from './RailwayDashboard'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {import.meta.env.VITE_KWIKPAY_HOSTED === 'true' ? <RailwayDashboard /> : <App />}
  </React.StrictMode>
)
