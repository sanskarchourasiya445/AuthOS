export interface ErrorDetail {
  code: string
  message: string
  details?: Record<string, unknown>
}

export interface ErrorEnvelope {
  error: ErrorDetail
}

export class ApiError extends Error {
  statusCode: number
  code: string
  details?: Record<string, unknown>

  constructor(message: string, statusCode: number, code: string = 'API_ERROR', details?: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.statusCode = statusCode
    this.code = code
    this.details = details
  }
}
