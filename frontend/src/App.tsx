import { useCallback, useEffect, useRef, useState } from 'react'
import { getNativeSession, type NativeSession } from './api/session'
import { DataPage } from './pages/DataPage'
import { HomePage } from './pages/HomePage'
import { currentRoute, guardedRoute, navigate, replaceRoute, routes, type CanonicalRoute } from './routing'

const recoveryText = 'Сессия подготовки была сброшена. Загрузите файл повторно.'

export function App() {
  const [route, setRoute] = useState<CanonicalRoute>(() => currentRoute() ?? routes.home)
  const [session, setSession] = useState<NativeSession | null>(null)
  const [sessionReady, setSessionReady] = useState(false)
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null)
  const requestedRoute = useRef(route)

  const sync = useCallback(async (requested: CanonicalRoute, stale = false) => {
    requestedRoute.current = requested
    try {
      const next = await getNativeSession()
      if (requestedRoute.current !== requested || currentRoute() !== requested) return
      setSession(next)
      setSessionReady(true)
      const allowed = guardedRoute(requested, next)
      if (allowed !== requested) {
        if (stale || (requested === routes.roles && allowed === routes.file)) setRecoveryMessage(recoveryText)
        replaceRoute(allowed)
        requestedRoute.current = allowed
        setRoute(allowed)
      }
    } catch {
      setSessionReady(false)
      // Keep the current view while the API is temporarily unavailable.
    }
  }, [])

  useEffect(() => {
    const onHashChange = () => {
      const next = currentRoute()
      if (next === null) {
        replaceRoute(routes.home)
        requestedRoute.current = routes.home
        setRoute(routes.home)
        void sync(routes.home)
        return
      }
      requestedRoute.current = next
      setRoute(next)
      setSessionReady(false)
      void sync(next)
    }
    if (currentRoute() === null) replaceRoute(routes.home)
    onHashChange()
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [sync])

  useEffect(() => {
    let revalidationInFlight = false
    let lastRevalidationAt = 0

    const revalidateOpenAnalysis = () => {
      const requested = currentRoute()
      if (!requested || requested === routes.home) return

      const now = Date.now()
      if (revalidationInFlight || now - lastRevalidationAt < 300) return
      revalidationInFlight = true
      lastRevalidationAt = now
      void sync(requested).finally(() => { revalidationInFlight = false })
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') revalidateOpenAnalysis()
    }

    window.addEventListener('focus', revalidateOpenAnalysis)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      window.removeEventListener('focus', revalidateOpenAnalysis)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [sync])

  const openHome = useCallback(() => navigate(routes.home), [])
  const continueAnalysis = useCallback(() => { if (session) navigate(session.resume_route) }, [session])
  const handleDatasetUploaded = useCallback(() => {
    setRecoveryMessage(null)
    navigate(routes.roles)
  }, [])
  const recoverStaleSession = useCallback(() => void sync(requestedRoute.current, true), [sync])

  if (route === routes.home) return <HomePage session={session} onContinue={continueAnalysis} />
  return <DataPage route={route} sessionReady={sessionReady} onHome={openHome} onDatasetUploaded={handleDatasetUploaded} onStaleSession={recoverStaleSession} recoveryMessage={recoveryMessage} />
}
