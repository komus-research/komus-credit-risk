import type { ReactNode } from 'react'

type IconName = 'algorithm' | 'alert-circle' | 'arrow' | 'box' | 'chart' | 'check' | 'clock' | 'download' | 'file' | 'folder' | 'home' | 'info' | 'layers' | 'menu' | 'model' | 'plus' | 'search' | 'settings' | 'table' | 'users' | 'warning'

const paths: Record<IconName, ReactNode> = {
  algorithm: <><path d="m12 2.8 7.5 4.3v8.7L12 20l-7.5-4.2V7.1L12 2.8Z" /><circle cx="12" cy="11.5" r="3.4" /><path d="M12 6.1v2M12 14.9v2M6.5 11.5h2M15.5 11.5h2" /></>,
  'alert-circle': <><circle cx="12" cy="12" r="9" /><path d="M12 7.5v5m0 3h.01" /></>,
  arrow: <path d="m9 18 6-6-6-6M3 12h11" />,
  box: <><path d="m12 2 8 4.5v9L12 20l-8-4.5v-9L12 2Z" /><path d="m4.4 6.8 7.6 4.3 7.6-4.3M12 11v9" /></>,
  check: <><circle cx="12" cy="12" r="9" /><path d="m8 12 2.6 2.6L16 9" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 6v6l4 2" /></>,
  chart: <><path d="M4 20h16M6 16V9h3v7H6Zm6 0V4h3v12h-3Zm6 0v-5h3v5h-3Z" /></>,
  download: <><path d="M12 3v12m-5-5 5 5 5-5" /><path d="M5 17v4h14v-4" /></>,
  file: <><path d="M6 2h8l5 5v15H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z" /><path d="M14 2v6h5M8 13h8M8 17h8" /></>,
  folder: <path d="M3 6.5h6l1.8 2H21v9A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5v-11Z" />,
  home: <path d="m3 10 9-7 9 7v10h-6v-6H9v6H3V10Z" />,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5m0-8h.01" /></>,
  layers: <><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5M3 16l9 5 9-5" /></>,
  menu: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></>,
  table: <><rect x="3.5" y="3" width="17" height="18" rx="2" /><path d="M3.5 8h17M9 8v13m5-13v13M3.5 13h17" /></>,
  users: <><circle cx="9" cy="8" r="3" /><path d="M3.5 19v-1.2A4.8 4.8 0 0 1 8.3 13h1.4a4.8 4.8 0 0 1 4.8 4.8V19h-11Z" /><path d="M16 5.5a3 3 0 0 1 0 5.8m1.2 2h.5a3.8 3.8 0 0 1 3.8 3.8V19h-3.2" /></>,
  model: <><rect x="4" y="4" width="12" height="12" rx="2" /><path d="M8 8h8v8a2 2 0 0 1-2 2H8V8ZM4 12H2v8a2 2 0 0 0 2 2h8v-2" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.8 1.8 0 0 0 .36 2l.06.06-2.1 2.1-.06-.06a1.8 1.8 0 0 0-2-.36 1.8 1.8 0 0 0-1.1 1.65v.1h-3v-.1a1.8 1.8 0 0 0-1.1-1.65 1.8 1.8 0 0 0-2 .36l-.06.06-2.1-2.1.06-.06a1.8 1.8 0 0 0 .36-2 1.8 1.8 0 0 0-1.66-1.1H5v-3h.1a1.8 1.8 0 0 0 1.66-1.1 1.8 1.8 0 0 0-.36-2l-.06-.06 2.1-2.1.06.06a1.8 1.8 0 0 0 2 .36 1.8 1.8 0 0 0 1.1-1.66V3h3v.1a1.8 1.8 0 0 0 1.1 1.66 1.8 1.8 0 0 0 2-.36l.06-.06 2.1 2.1-.06.06a1.8 1.8 0 0 0-.36 2 1.8 1.8 0 0 0 1.66 1.1h.1v3h-.1A1.8 1.8 0 0 0 19.4 15Z" /></>,
  warning: <><path d="m12 3 10 18H2L12 3Z" /><path d="M12 9v5m0 3h.01" /></>,
}

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return <svg aria-hidden="true" className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>
}
