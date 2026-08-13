import { useEffect, useState } from 'react'
import { applyPwaUpdate, getUpdateState, subscribeToPwaUpdates } from './updatePrompt'

export default function usePwaUpdate() {
  const [state, setState] = useState(getUpdateState)

  useEffect(() => subscribeToPwaUpdates(setState), [])

  return {
    ...state,
    updateApp: applyPwaUpdate,
  }
}

