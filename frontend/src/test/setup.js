import '@testing-library/jest-dom'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// Desmonta el árbol de React entre tests (evita fugas de estado/DOM).
afterEach(() => {
  cleanup()
})
