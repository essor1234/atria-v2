import 'reflect-metadata'
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './index.css'
import { wsClient } from './api/websocket'
import { applyTheme, useThemeStore } from './stores/theme'

// Apply the persisted Celesnity theme scope (.cosmos / .daybreak) before the
// first paint so there is no light-on-dark flash.
applyTheme(useThemeStore.getState().theme)

// Connect WebSocket on app start
wsClient.connect()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
