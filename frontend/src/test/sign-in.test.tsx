import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider } from '../features/auth/AuthContext'
import { SignInModal } from '../features/auth/SignInModal'
import { api } from '../lib/api/endpoints'

describe('SignInModal & Authentication', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders synthetic personas with accessible roles', () => {
    render(
      <AuthProvider>
        <SignInModal isOpen={true} onClose={vi.fn()} />
      </AuthProvider>
    )

    expect(screen.getByText('Clinical Actor Authentication')).toBeInTheDocument()
    expect(screen.getByText('Dr. Sarah Chen, MD')).toBeInTheDocument()
    expect(screen.getByText('Dr. Allison Ross, MD')).toBeInTheDocument()
    expect(screen.getByText('Jane Doe')).toBeInTheDocument()
    expect(screen.getByText('Alex Rivera')).toBeInTheDocument()
  })

  it('authenticates when clicking on a persona', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const loginMock = vi.spyOn(api.auth, 'login').mockResolvedValue({
      access_token: 'mock-token-dr-chen',
      token_type: 'bearer',
      expires_in: 7200,
      user: {
        sub: 'REV-001',
        name: 'Dr. Sarah Chen, MD',
        role: 'clinician_reviewer',
        cases: ['CASE-SYN-001'],
      },
    })

    render(
      <AuthProvider>
        <SignInModal isOpen={true} onClose={onClose} />
      </AuthProvider>
    )

    const chenBtn = screen.getByRole('button', { name: /Dr\. Sarah Chen/i })
    await user.click(chenBtn)

    expect(loginMock).toHaveBeenCalledWith({
      username: 'dr_chen',
      password: 'synthetic-demo-pass-dr-chen',
    })
    expect(onClose).toHaveBeenCalled()
  })

  it('displays authentication error if login fails', async () => {
    const user = userEvent.setup()
    vi.spyOn(api.auth, 'login').mockRejectedValue(new Error('Invalid username or password'))

    render(
      <AuthProvider>
        <SignInModal isOpen={true} onClose={vi.fn()} />
      </AuthProvider>
    )

    const chenBtn = screen.getByRole('button', { name: /Dr\. Sarah Chen/i })
    await user.click(chenBtn)

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password')
  })
})
