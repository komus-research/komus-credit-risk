import { useCallback, useEffect, useRef, useState } from 'react'
import { getNativeSession, type NativeSession } from './api/session'
import { DataPage } from './pages/DataPage'
import { HomePage } from './pages/HomePage'
import { AlgorithmPage } from './pages/AlgorithmPage'
import { FeaturesPage } from './pages/FeaturesPage'
import { QualityPage } from './pages/QualityPage'
import { ResultPage } from './pages/ResultPage'
import { ObjectsPage } from './pages/ObjectsPage'
import { ObjectDetailPage } from './pages/ObjectDetailPage'
import { ThresholdPage } from './pages/ThresholdPage'
import { GlobalExplanationPage } from './pages/GlobalExplanationPage'
import { currentRoute, guardedRoute, isObjectDetailRoute, navigate, navigateObjects, objectIdFromRoute, parseObjectsQuery, replaceRoute, routes, type AppRoute } from './routing'

const recoveryText = 'Сессия подготовки была сброшена. Загрузите файл повторно.'

export function App() {
  const [route, setRoute] = useState<AppRoute>(() => currentRoute() ?? routes.home)
  const [session, setSession] = useState<NativeSession | null>(null)
  const [sessionReady, setSessionReady] = useState(false)
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null)
  const requestedRoute = useRef<AppRoute>(route)
  const resultThresholdAccess = useRef(false)
  const resultObjectsAccess = useRef(false)

  const sync = useCallback(async (requested: AppRoute, stale = false) => {
    requestedRoute.current = requested
    try {
      const next = await getNativeSession()
      if (requestedRoute.current !== requested || currentRoute() !== requested) return
      setSession(next)
      setSessionReady(true)
      const allowed = guardedRoute(requested, next, resultThresholdAccess.current, resultObjectsAccess.current)
      if (allowed !== requested) {
        if (requested === routes.resultThreshold) resultThresholdAccess.current = false
        if (requested === routes.resultObjects || isObjectDetailRoute(requested)) resultObjectsAccess.current = false
        if (stale || (requested === routes.roles && allowed === routes.file)) setRecoveryMessage(recoveryText)
        replaceRoute(allowed)
        requestedRoute.current = allowed
        setRoute(allowed)
      }
    } catch {
      if (requestedRoute.current !== requested || currentRoute() !== requested) return
      setSessionReady(false)
      // Keep the current view while the API is temporarily unavailable.
    }
  }, [])

  useEffect(() => {
    const onHashChange = () => {
      const next = currentRoute()
      if (next === null) {
        resultThresholdAccess.current = false
        resultObjectsAccess.current = false
        replaceRoute(routes.home)
        requestedRoute.current = routes.home
        setRoute(routes.home)
        void sync(routes.home)
        return
      }
      if (next !== routes.resultThreshold) resultThresholdAccess.current = false
      if (next !== routes.resultObjects && !isObjectDetailRoute(next)) resultObjectsAccess.current = false
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
  const openResultThreshold = useCallback(() => {
    resultThresholdAccess.current = true
    navigate(routes.resultThreshold)
  }, [])
  const openResultObjects = useCallback(() => {
    resultObjectsAccess.current = true
    navigate(routes.resultObjects)
  }, [])
  const backToObjects = useCallback(() => {
    resultObjectsAccess.current = true
    navigateObjects(parseObjectsQuery())
  }, [])
  const continueAnalysis = useCallback(() => { if (session) navigate(session.resume_route) }, [session])
  const handleDatasetUploaded = useCallback(() => {
    setRecoveryMessage(null)
    navigate(routes.roles)
  }, [])
  const recoverStaleSession = useCallback(() => void sync(requestedRoute.current, true), [sync])

  if (route === routes.home) return <HomePage session={session} onContinue={continueAnalysis} />
  if (route === routes.features) return <FeaturesPage onHome={openHome} onSessionChange={setSession} />
  if (route === routes.algorithm) return <AlgorithmPage onHome={openHome} />
  if (route === routes.quality) return <QualityPage onHome={openHome} />
  if (route === routes.result) return <ResultPage onHome={openHome} onOpenThreshold={openResultThreshold} onOpenObjects={openResultObjects} />
  if (route === routes.resultGlobalExplanation) return <GlobalExplanationPage onHome={openHome} />
  if (route === routes.resultThreshold) return <ThresholdPage onHome={openHome} />
  if (route === routes.resultObjects) return <ObjectsPage onHome={openHome} />
  if (isObjectDetailRoute(route)) return <ObjectDetailPage objectId={objectIdFromRoute(route)!} onBack={backToObjects} onHome={openHome} />
  return <DataPage route={route} sessionReady={sessionReady} onHome={openHome} onDatasetUploaded={handleDatasetUploaded} onStaleSession={recoverStaleSession} recoveryMessage={recoveryMessage} />
}
