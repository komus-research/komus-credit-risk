import { HomePage } from './pages/HomePage'
import { DataPage } from './pages/DataPage'

export function App() {
  return window.location.hash === '#native-data' ? <DataPage /> : <HomePage />
}
