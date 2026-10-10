import React, { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../../features/auth/AuthContext'
import { SignInModal } from '../../features/auth/SignInModal'
import { Button } from '../common/Button'

interface HeaderProps {
  activeCaseId?: string | null
}

export const Header: React.FC<HeaderProps> = ({ activeCaseId }) => {
  const { user, isAuthenticated, logout } = useAuth()
  const [isSignInOpen, setIsSignInOpen] = useState(false)
  const location = useLocation()

  const isQueueActive = location.pathname === '/' || location.pathname === '/cases'
  const isWorkspaceActive = location.pathname.startsWith('/cases/')

  const roleBadgeClass =
    user?.role === 'clinician_reviewer'
      ? 'role-reviewer'
      : user?.role === 'auditor'
      ? 'role-auditor'
      : user?.role === 'admin'
      ? 'role-admin'
      : ''

  return (
    <>
      <header className="app-header">
        <div className="brand-section">
          <Link to="/" style={{ textDecoration: 'none', color: 'inherit' }}>
            <div className="brand-title">
              <span>AuthOS</span>
              <span className="brand-badge">PRE-SUBMISSION EVIDENCE LINTER</span>
            </div>
          </Link>
        </div>

        <div className="actor-session-bar">
          <div className="user-chip" id="userChip" role="status">
            <span id="actorName">{isAuthenticated ? user?.name : 'Unauthenticated'}</span>
            <span className={`role-badge ${roleBadgeClass}`} id="actorRoleBadge">
              {isAuthenticated ? (user?.role || 'USER') : 'NONE'}
            </span>
          </div>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => setIsSignInOpen(true)}
            id="btnSwitchActor"
          >
            {isAuthenticated ? 'Switch Actor' : 'Sign In'}
          </Button>

          {isAuthenticated && (
            <Button
              variant="secondary"
              size="sm"
              onClick={logout}
              id="btnLogout"
            >
              Sign Out
            </Button>
          )}
        </div>
      </header>

      <nav className="app-nav" aria-label="Main Navigation">
        <Link
          to="/cases"
          className={`nav-tab ${isQueueActive ? 'active' : ''}`}
          id="tabQueue"
        >
          📋 Case Queue
        </Link>
        {activeCaseId ? (
          <Link
            to={`/cases/${activeCaseId}`}
            className={`nav-tab ${isWorkspaceActive ? 'active' : ''}`}
            id="tabWorkspace"
          >
            🔬 Review Workspace ({activeCaseId})
          </Link>
        ) : (
          <span
            className={`nav-tab ${isWorkspaceActive ? 'active' : ''}`}
            id="tabWorkspace"
            style={{ opacity: 0.6, cursor: 'not-allowed' }}
            title="Select a case from the queue to open workspace"
          >
            🔬 Review Workspace
          </span>
        )}
      </nav>

      <SignInModal isOpen={isSignInOpen} onClose={() => setIsSignInOpen(false)} />
    </>
  )
}
