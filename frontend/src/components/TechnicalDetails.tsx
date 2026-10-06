import { createContext, useContext, useLayoutEffect, useRef, type ComponentPropsWithoutRef } from 'react'

export type TechnicalDetailsPreference = { expanded: boolean; loaded: boolean }

export const TechnicalDetailsPreferenceContext = createContext<TechnicalDetailsPreference>({ expanded: false, loaded: false })

/** A lifecycle-safe, user-controllable disclosure for technical/provenance facts. */
export function TechnicalDetails({ children, ...props }: ComponentPropsWithoutRef<'details'>) {
  const preference = useContext(TechnicalDetailsPreferenceContext)
  const reference = useRef<HTMLDetailsElement>(null)
  useLayoutEffect(() => {
    if (preference.loaded && reference.current) reference.current.open = preference.expanded
  }, [preference.expanded, preference.loaded])
  return <details ref={reference} {...props}>{children}</details>
}
