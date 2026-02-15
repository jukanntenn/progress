import { Route, Routes } from 'react-router-dom'
import { ToastProvider } from './components/ui/toast'
import Config from './pages/Config'
import ReportDetail from './pages/ReportDetail'
import ReportList from './pages/ReportList'

function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/" element={<ReportList />} />
        <Route path="/report/:id" element={<ReportDetail />} />
        <Route path="/config" element={<Config />} />
      </Routes>
    </ToastProvider>
  )
}

export default App

