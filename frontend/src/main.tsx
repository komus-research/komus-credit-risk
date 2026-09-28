import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

type Health = { status: 'ok' }

async function nativeHealth(): Promise<Health> {
  const response = await fetch('/api/v1/health')
  if (!response.ok) throw new Error('Native API is unavailable.')
  return response.json() as Promise<Health>
}

function App() {
  return (
    <main>
      <h1>AXION</h1>
      <p>Native foundation is connected to the API boundary.</p>
      <button
        onClick={() => void nativeHealth().then(() => window.alert('Native API: ok'))}
      >
        Check native API
      </button>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode><App /></StrictMode>,
)
