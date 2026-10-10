import React, { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom'
import { AuthProvider, useAuth } from '../features/auth/AuthContext'
import { ToastProvider } from '../components/common/Toast'
import { AppShell } from '../components/layout/AppShell'
import { CaseQueueScreen } from '../features/cases/CaseQueueScreen'
import { CaseWorkspaceScreen } from '../features/workspace/CaseWorkspaceScreen'

// Wrapper to pass activeCaseId to AppShell
const WorkspaceRoute: React.FC = () => {
  const { caseId } = useParams<{ caseId: string }>()
  return (
    <AppShell activeCaseId={caseId}>
      <CaseWorkspaceScreen />
    </AppShell>
  )
}

const QueueRoute: React.FC = () => {
  return (
    <AppShell activeCaseId={null}>
      <CaseQueueScreen />
    </AppShell>
  )
}

const InitialAuthBootstrap: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, loginAsPersona } = useAuth()
  const [bootstrapped, setBootstrapped] = useState(false)

  useEffect(() => {
    if (!isAuthenticated && !bootstrapped) {
      setBootstrapped(true)
      // Auto-authenticate as default clinical reviewer (Dr. Sarah Chen, MD)
      loginAsPersona('dr_chen').catch(() => {
        // Fallback gracefully to unauthenticated state if backend isn't ready
      })
    }
  }, [isAuthenticated, bootstrapped, loginAsPersona])

  return <>{children}</>
}

export const App: React.FC = () => {
  const basename =
    typeof window !== 'undefined' && window.location.pathname.startsWith('/app') ? '/app' : '/'

  return (
    <BrowserRouter basename={basename}>
      <AuthProvider>
        <ToastProvider>
          <InitialAuthBootstrap>
            <Routes>
              <Route path="/" element={<Navigate to="/cases" replace />} />
              <Route path="/cases" element={<QueueRoute />} />
              <Route path="/cases/:caseId" element={<WorkspaceRoute />} />
              <Route path="*" element={<Navigate to="/cases" replace />} />
            </Routes>
          </InitialAuthBootstrap>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
