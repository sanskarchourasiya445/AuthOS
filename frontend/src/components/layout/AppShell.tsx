import React from 'react'
import { Header } from './Header'
import { DisclaimerBanner } from './DisclaimerBanner'

interface AppShellProps {
  children: React.ReactNode
  activeCaseId?: string | null
}

export const AppShell: React.FC<AppShellProps> = ({ children, activeCaseId }) => {
  return (
    <>
      <Header activeCaseId={activeCaseId} />
      <main className="main-container">
        <DisclaimerBanner />
        {children}
      </main>
    </>
  )
}
