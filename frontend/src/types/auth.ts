export type UserRole = 'clinician_reviewer' | 'auditor' | 'admin'

export interface AuthenticatedUser {
  sub: string
  name: string
  role: UserRole | string
  cases: string[]
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: AuthenticatedUser
}

export interface LoginCredentials {
  username: string
  password?: string
}

export interface SyntheticPersona {
  key: string
  name: string
  role: UserRole
  roleLabel: string
  scope: string
  credentials: LoginCredentials
}
