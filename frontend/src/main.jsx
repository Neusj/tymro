import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import './registerSW'
// Arranca la captura del evento `beforeinstallprompt` lo antes posible (es one-shot).
import './pwa/installPrompt'
import { shouldShowPublicLandingForWindow } from './utils/publicLandingHost'

const root = ReactDOM.createRoot(document.getElementById('root'))

async function bootstrap() {
  if (shouldShowPublicLandingForWindow()) {
    const { default: PublicLandingPage } = await import('./pages/PublicLandingPage')
    root.render(
      <React.StrictMode>
        <PublicLandingPage />
      </React.StrictMode>,
    )
    return
  }

  const [{ BrowserRouter }, { AuthProvider }, { default: App }] = await Promise.all([
    import('react-router-dom'),
    import('./auth/AuthContext'),
    import('./App'),
  ])

  root.render(
    <React.StrictMode>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </React.StrictMode>,
  )
}

bootstrap()
