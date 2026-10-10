import { ApiError } from '../../types/api'
import type { ErrorEnvelope } from '../../types/api'

let inMemoryAuthToken: string | null = null

export function setAuthToken(token: string | null): void {
  inMemoryAuthToken = token
}

export function getAuthToken(): string | null {
  return inMemoryAuthToken
}

export const API_BASE_URL = '/api/v1'

export async function apiFetch<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = endpoint.startsWith('/') ? endpoint : `${API_BASE_URL}/${endpoint}`
  const headers = new Headers(options.headers || {})

  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  if (inMemoryAuthToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${inMemoryAuthToken}`)
  }

  let response: Response
  try {
    response = await fetch(url, {
      ...options,
      headers,
    })
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Network request failed'
    throw new ApiError(message, 0, 'NETWORK_ERROR')
  }

  if (!response.ok) {
    let errorCode = 'API_ERROR'
    let errorMessage = `Request failed with status ${response.status}`
    let details: Record<string, unknown> | undefined

    try {
      const errorJson = (await response.json()) as ErrorEnvelope | { detail?: unknown }
      if ('error' in errorJson && errorJson.error) {
        errorCode = errorJson.error.code || errorCode
        errorMessage = errorJson.error.message || errorMessage
        details = errorJson.error.details
      } else if ('detail' in errorJson) {
        if (typeof errorJson.detail === 'string') {
          errorMessage = errorJson.detail
        } else if (typeof errorJson.detail === 'object' && errorJson.detail !== null) {
          const det = errorJson.detail as { code?: string; message?: string }
          errorCode = det.code || errorCode
          errorMessage = det.message || errorMessage
        }
      }
    } catch {
      // Non-JSON response
      errorMessage = response.statusText || errorMessage
    }

    throw new ApiError(errorMessage, response.status, errorCode, details)
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T
  }

  try {
    return (await response.json()) as T
  } catch {
    return {} as T
  }
}
