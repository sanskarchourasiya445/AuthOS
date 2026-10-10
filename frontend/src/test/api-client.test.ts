import { describe, it, expect, beforeEach, vi } from 'vitest'
import { apiFetch, setAuthToken, getAuthToken } from '../lib/api/client'
import { ApiError } from '../types/api'

describe('API Client', () => {
  beforeEach(() => {
    setAuthToken(null)
    vi.restoreAllMocks()
  })

  it('manages in-memory token correctly without local storage', () => {
    expect(getAuthToken()).toBeNull()
    setAuthToken('mock-jwt-token-123')
    expect(getAuthToken()).toBe('mock-jwt-token-123')
    setAuthToken(null)
    expect(getAuthToken()).toBeNull()
  })

  it('injects Bearer token into Authorization header when present', async () => {
    setAuthToken('active-token-xyz')
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    )
    vi.stubGlobal('fetch', fetchMock)

    await apiFetch('/api/v1/health')
    expect(fetchMock).toHaveBeenCalled()
    const callHeaders = fetchMock.mock.calls[0][1].headers as Headers
    expect(callHeaders.get('Authorization')).toBe('Bearer active-token-xyz')
  })

  it('parses structured ErrorEnvelope on 4xx/5xx responses', async () => {
    const errorEnvelope = {
      error: {
        code: 'ACCESS_DENIED',
        message: 'Access denied: Case does not belong to user.',
      },
    }
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(errorEnvelope), {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    )
    vi.stubGlobal('fetch', fetchMock)

    try {
      await apiFetch('/api/v1/cases/CASE-SYN-999')
      expect.fail('Should have thrown an ApiError')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      const apiErr = err as ApiError
      expect(apiErr.statusCode).toBe(403)
      expect(apiErr.code).toBe('ACCESS_DENIED')
      expect(apiErr.message).toContain('Access denied')
    }
  })

  it('handles network failure cleanly', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Connection refused')))
    await expect(apiFetch('/api/v1/health')).rejects.toThrow('Connection refused')
  })
})
