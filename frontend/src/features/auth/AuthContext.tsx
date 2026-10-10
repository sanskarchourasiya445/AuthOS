import React, { createContext, useContext, useState, useCallback, useMemo } from 'react'
import type { AuthenticatedUser, LoginCredentials } from '../../types/auth'
import { api } from '../../lib/api/endpoints'
import { setAuthToken } from '../../lib/api/client'
import { SYNTHETIC_PERSONAS } from './personas'

interface AuthContextType {
  user: AuthenticatedUser | null
  token: string | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
  activePersonaKey: string | null
  isReviewer: boolean
  isAuditor: boolean
  isAdmin: boolean
  loginAsPersona: (personaKey: string) => Promise<void>
  loginWithCredentials: (credentials: LoginCredentials) => Promise<void>
  logout: () => void
  clearError: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthenticatedUser | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [activePersonaKey, setActivePersonaKey] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  const clearError = useCallback(() => setError(null), [])

  const loginWithCredentials = useCallback(async (credentials: LoginCredentials, personaKey?: string) => {
    setIsLoading(true)
    setError(null)
    try {
      const response = await api.auth.login(credentials)
      setAuthToken(response.access_token)
      setToken(response.access_token)
      setUser(response.user)
      if (personaKey) {
        setActivePersonaKey(personaKey)
      } else {
        const found = Object.values(SYNTHETIC_PERSONAS).find(
          (p) => p.credentials.username === credentials.username
        )
        setActivePersonaKey(found ? found.key : null)
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Authentication failed'
      setError(message)
      setAuthToken(null)
      setToken(null)
      setUser(null)
      setActivePersonaKey(null)
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [])

  const loginAsPersona = useCallback(
    async (personaKey: string) => {
      const persona = SYNTHETIC_PERSONAS[personaKey]
      if (!persona) {
        throw new Error(`Unknown persona: ${personaKey}`)
      }
      await loginWithCredentials(persona.credentials, personaKey)
    },
    [loginWithCredentials]
  )

  const logout = useCallback(() => {
    setAuthToken(null)
    setToken(null)
    setUser(null)
    setActivePersonaKey(null)
    setError(null)
  }, [])

  const isReviewer = useMemo(() => user?.role === 'clinician_reviewer', [user])
  const isAuditor = useMemo(() => user?.role === 'auditor', [user])
  const isAdmin = useMemo(() => user?.role === 'admin', [user])

  const value = useMemo(
    () => ({
      user,
      token,
      isAuthenticated: Boolean(token && user),
      isLoading,
      error,
      activePersonaKey,
      isReviewer,
      isAuditor,
      isAdmin,
      loginAsPersona,
      loginWithCredentials,
      logout,
      clearError,
    }),
    [
      user,
      token,
      isLoading,
      error,
      activePersonaKey,
      isReviewer,
      isAuditor,
      isAdmin,
      loginAsPersona,
      loginWithCredentials,
      logout,
      clearError,
    ]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
