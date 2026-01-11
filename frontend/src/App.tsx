import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ObsidianLayout } from './components/Layout/ObsidianLayout'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ObsidianLayout />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
