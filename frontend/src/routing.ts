import type { NativeSession } from './api/session'

export const routes = {
  home: '#/home',
  file: '#/analysis/data/file',
  roles: '#/analysis/data/roles',
  confirmation: '#/analysis/data/confirmation',
  features: '#/analysis/features',
  algorithm: '#/analysis/algorithm',
  quality: '#/analysis/quality',
  result: '#/analysis/result',
  resultThreshold: '#/analysis/result/threshold',
  resultObjects: '#/analysis/result/objects',
} as const

export type CanonicalRoute = typeof routes[keyof typeof routes]
export type DataRoute = typeof routes.file | typeof routes.roles

type ObjectsOutcome = 'TP' | 'TN' | 'FP' | 'FN'
type ObjectsTarget = 'ANY' | 'POSITIVE' | 'NEGATIVE'
type ObjectsSort = 'SCORE_DESC' | 'SCORE_ASC' | 'DISTANCE_TO_THRESHOLD_ASC'
type ObjectsQuickView = 'errors' | 'high' | 'boundary' | 'missed' | 'false-positive' | 'all' | null

export type ObjectsQueryState = {
  search: string
  target: ObjectsTarget
  outcomes: ObjectsOutcome[]
  minScore: number
  maxScore: number
  sort: ObjectsSort
  offset: number
  quickView: ObjectsQuickView
}

const knownRoutes = new Set<string>(Object.values(routes))
const outcomeOrder: ObjectsOutcome[] = ['TP', 'TN', 'FP', 'FN']
const targets = new Set<ObjectsTarget>(['ANY', 'POSITIVE', 'NEGATIVE'])
const sorts = new Set<ObjectsSort>(['SCORE_DESC', 'SCORE_ASC', 'DISTANCE_TO_THRESHOLD_ASC'])
const quickViews = new Set<Exclude<ObjectsQuickView, null>>(['errors', 'high', 'boundary', 'missed', 'false-positive', 'all'])

function quickViewMatchesQuery(quickView: ObjectsQuickView, outcomes: ObjectsOutcome[], sort: ObjectsSort) {
  if (quickView === null) return false
  const preset = {
    errors: { outcomes: ['FP', 'FN'], sort: 'SCORE_DESC' },
    high: { outcomes: [], sort: 'SCORE_DESC' },
    boundary: { outcomes: [], sort: 'DISTANCE_TO_THRESHOLD_ASC' },
    missed: { outcomes: ['FN'], sort: 'SCORE_DESC' },
    'false-positive': { outcomes: ['FP'], sort: 'SCORE_DESC' },
    all: { outcomes: [], sort: 'SCORE_DESC' },
  }[quickView]

  return preset.sort === sort && preset.outcomes.length === outcomes.length && preset.outcomes.every((outcome, index) => outcome === outcomes[index])
}

function hashPath(hash = window.location.hash) {
  return hash.split('?', 1)[0]
}

function hashQuery(hash = window.location.hash) {
  const queryStart = hash.indexOf('?')
  return queryStart === -1 ? '' : hash.slice(queryStart + 1)
}

function scoreParam(value: string | null) {
  if (value === null || value.trim() === '') return null
  const score = Number(value)
  return Number.isFinite(score) && score >= 0 && score <= 1 ? score : null
}

function offsetParam(value: string | null) {
  if (value === null || !/^\d+$/.test(value)) return 0
  const offset = Number(value)
  return Number.isSafeInteger(offset) ? offset : 0
}

function normalizeObjectsQuery(state: ObjectsQueryState): ObjectsQueryState {
  const validMinScore = Number.isFinite(state.minScore) && state.minScore >= 0 && state.minScore <= 1
  const validMaxScore = Number.isFinite(state.maxScore) && state.maxScore >= 0 && state.maxScore <= 1
  const validScoreRange = validMinScore && validMaxScore && state.minScore <= state.maxScore
  const outcomes = outcomeOrder.filter(outcome => state.outcomes.includes(outcome))
  const sort = sorts.has(state.sort) ? state.sort : 'SCORE_DESC'
  const quickView = state.quickView && quickViews.has(state.quickView) && quickViewMatchesQuery(state.quickView, outcomes, sort)
    ? state.quickView
    : null

  return {
    search: state.search.trim(),
    target: targets.has(state.target) ? state.target : 'ANY',
    outcomes,
    minScore: validScoreRange ? state.minScore : 0,
    maxScore: validScoreRange ? state.maxScore : 1,
    sort,
    offset: Number.isSafeInteger(state.offset) && state.offset >= 0 ? state.offset : 0,
    quickView,
  }
}

export function currentRoute(): CanonicalRoute | null {
  const path = hashPath()
  return knownRoutes.has(path) ? path as CanonicalRoute : null
}

export function navigate(route: CanonicalRoute) {
  if (window.location.hash !== route) window.location.hash = route
}

export function replaceRoute(route: CanonicalRoute) {
  window.history.replaceState(null, '', route)
}

export function parseObjectsQuery(hash = window.location.hash): ObjectsQueryState {
  const params = new URLSearchParams(hashQuery(hash))
  const minScore = params.has('min_score') ? scoreParam(params.get('min_score')) : 0
  const maxScore = params.has('max_score') ? scoreParam(params.get('max_score')) : 1
  const validScoreRange = minScore !== null && maxScore !== null && minScore <= maxScore
  const target = params.get('target')
  const sort = params.get('sort')
  const quickView = params.get('quick_view')
  const outcomes = new Set(params.getAll('outcomes').filter((value): value is ObjectsOutcome => outcomeOrder.includes(value as ObjectsOutcome)))

  return normalizeObjectsQuery({
    search: params.get('search')?.trim() ?? '',
    target: targets.has(target as ObjectsTarget) ? target as ObjectsTarget : 'ANY',
    outcomes: outcomeOrder.filter(outcome => outcomes.has(outcome)),
    minScore: validScoreRange ? minScore : 0,
    maxScore: validScoreRange ? maxScore : 1,
    sort: sorts.has(sort as ObjectsSort) ? sort as ObjectsSort : 'SCORE_DESC',
    offset: offsetParam(params.get('offset')),
    quickView: quickViews.has(quickView as Exclude<ObjectsQuickView, null>) ? quickView as Exclude<ObjectsQuickView, null> : null,
  })
}

export function serializeObjectsQuery(state: ObjectsQueryState) {
  const normalized = normalizeObjectsQuery(state)
  const params = new URLSearchParams()
  if (normalized.search) params.set('search', normalized.search)
  if (normalized.target !== 'ANY') params.set('target', normalized.target)
  normalized.outcomes.forEach(outcome => params.append('outcomes', outcome))
  if (normalized.minScore !== 0) params.set('min_score', String(normalized.minScore))
  if (normalized.maxScore !== 1) params.set('max_score', String(normalized.maxScore))
  if (normalized.sort !== 'SCORE_DESC' || normalized.quickView) params.set('sort', normalized.sort)
  if (normalized.offset !== 0) params.set('offset', String(normalized.offset))
  if (normalized.quickView) params.set('quick_view', normalized.quickView)
  return params.toString()
}

export function buildObjectsRoute(state: ObjectsQueryState) {
  const query = serializeObjectsQuery(state)
  return query ? `${routes.resultObjects}?${query}` : routes.resultObjects
}

export function navigateObjects(state: ObjectsQueryState) {
  const route = buildObjectsRoute(state)
  if (window.location.hash !== route) window.location.hash = route
}

export function replaceObjects(state: ObjectsQueryState) {
  const route = buildObjectsRoute(state)
  if (window.location.hash === route) return
  window.history.replaceState(null, '', route)
  window.dispatchEvent(new Event('hashchange'))
}

export function guardedRoute(route: CanonicalRoute, session: NativeSession, allowResultThreshold = false, allowResultObjects = false): CanonicalRoute {
  if (route === routes.home || route === routes.file) return route
  if (route === routes.roles) {
    return session.analysis_active && session.data_substep === 'ROLES' ? route : routes.file
  }
  if (route === routes.confirmation) return session.resume_route
  if (route === routes.features) return session.data_substep === 'PREPARED' ? route : session.resume_route
  if (route === routes.algorithm) return session.data_substep === 'PREPARED' && session.current_step >= 2 ? route : session.resume_route
  if (route === routes.quality) return session.resume_route === routes.quality || session.resume_route === routes.result ? route : session.resume_route
  if (route === routes.result) return session.resume_route === routes.result ? route : session.resume_route
  if (route === routes.resultThreshold) {
    return session.resume_route === routes.result && allowResultThreshold ? route : session.resume_route
  }
  if (route === routes.resultObjects) {
    return session.resume_route === routes.result && allowResultObjects ? route : session.resume_route
  }
  return routes.home
}
