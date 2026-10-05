import { useCallback, useEffect, useRef, useState } from 'react'
import { getNativeSession, startNewAnalysis, type NativeSession } from './api/session'
import { Sidebar } from './components/Sidebar'
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
  const [confirmingNewAnalysis, setConfirmingNewAnalysis] = useState(false)
  const [startingNewAnalysis, setStartingNewAnalysis] = useState(false)
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
  const beginNewAnalysis = useCallback((confirmReset = false) => {
    setStartingNewAnalysis(true)
    void startNewAnalysis(confirmReset).then(result => {
      if (result.status === 'CONFIRMATION_REQUIRED') setConfirmingNewAnalysis(true)
      else navigate(result.resume_route)
    }).finally(() => setStartingNewAnalysis(false))
  }, [])

  const page = route === routes.home
    ? <HomePage session={session} onContinue={continueAnalysis} onStartNewAnalysis={beginNewAnalysis} startingNewAnalysis={startingNewAnalysis} />
    : route === routes.features
      ? <FeaturesPage onSessionChange={setSession} />
      : route === routes.algorithm
        ? <AlgorithmPage />
        : route === routes.quality
          ? <QualityPage />
          : route === routes.result
            ? <ResultPage onOpenThreshold={openResultThreshold} onOpenObjects={openResultObjects} />
            : route === routes.resultGlobalExplanation
              ? <GlobalExplanationPage />
              : route === routes.resultThreshold
                ? <ThresholdPage />
                : route === routes.resultObjects
                  ? <ObjectsPage />
                  : isObjectDetailRoute(route)
                    ? <ObjectDetailPage objectId={objectIdFromRoute(route)!} onBack={backToObjects} />
                    : <DataPage route={route} sessionReady={sessionReady} onDatasetUploaded={handleDatasetUploaded} onStaleSession={recoverStaleSession} recoveryMessage={recoveryMessage} />
  const shellClass = route === routes.home
    ? 'home-shell'
    : route === routes.file || route === routes.roles || route === routes.confirmation
      ? 'workflow-shell data-shell'
      : route === routes.features || route === routes.algorithm || route === routes.quality
        ? 'workflow-shell features-shell'
        : 'features-shell'

  return <>
    <div className={`app-shell ${shellClass}`}>
      <Sidebar active={route === routes.home ? 'home' : 'analysis'} onHome={openHome} onNewAnalysis={() => beginNewAnalysis()} />
      <div className="app-page">{page}</div>
    </div>
    {confirmingNewAnalysis && <div className="native-modal-backdrop" role="presentation"><section className="native-modal" role="dialog" aria-modal="true" aria-labelledby="new-analysis-title"><h2 id="new-analysis-title">Начать новый анализ?</h2><p>Текущие неподтверждённые данные будут сброшены.</p><div><button className="secondary-action" onClick={() => setConfirmingNewAnalysis(false)}>Отмена</button><button className="destructive-action" disabled={startingNewAnalysis} onClick={() => { setConfirmingNewAnalysis(false); beginNewAnalysis(true) }}>Начать новый</button></div></section></div>}
  </>
}
