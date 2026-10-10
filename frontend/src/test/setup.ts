import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// Automatically unmount and cleanup DOM after each test
afterEach(() => {
  cleanup()
})
