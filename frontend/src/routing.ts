import type { NativeSession } from './api/session'

export const routes = {
  home: '#/home',
  file: '#/analysis/data/file',
  roles: '#/analysis/data/roles',
  confirmation: '#/analysis/data/confirmation',
  features: '#/analysis/features',
  algorithm: '#/analysis/algorithm',
} as const

export type CanonicalRoute = typeof routes[keyof typeof routes]
export type DataRoute = typeof routes.file | typeof routes.roles

const knownRoutes = new Set<string>(Object.values(routes))

export function currentRoute(): CanonicalRoute | null {
  return knownRoutes.has(window.location.hash) ? window.location.hash as CanonicalRoute : null
}

export function navigate(route: CanonicalRoute) {
  if (window.location.hash !== route) window.location.hash = route
}

export function replaceRoute(route: CanonicalRoute) {
  window.history.replaceState(null, '', route)
}

export function guardedRoute(route: CanonicalRoute, session: NativeSession): CanonicalRoute {
  if (route === routes.home || route === routes.file) return route
  if (route === routes.roles) {
    return session.analysis_active && session.data_substep === 'ROLES' ? route : routes.file
  }
  if (route === routes.confirmation) return session.resume_route
  if (route === routes.features) return session.data_substep === 'PREPARED' ? route : session.resume_route
  if (route === routes.algorithm) return session.resume_route === routes.algorithm ? route : session.resume_route
  return routes.home
}
