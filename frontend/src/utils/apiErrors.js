export const extractApiErrorMessage = (apiError, fallbackMessage) => {
  const detail = apiError?.response?.data

  if (!detail) {
    return fallbackMessage
  }

  if (typeof detail === 'string') {
    return detail
  }

  if (detail.detail && typeof detail.detail === 'string') {
    return detail.detail
  }

  const messages = []
  Object.values(detail).forEach((value) => {
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (typeof item === 'string') {
          messages.push(item)
        }
      })
      return
    }

    if (typeof value === 'string') {
      messages.push(value)
    }
  })

  if (messages.length > 0) {
    return messages.join(' ')
  }

  return fallbackMessage
}

// El backend deniega como 400 (serializer) o 403 (viewset) según la capa;
// ambas significan "no permitido" para la UI.
export const isPermissionError = (apiError) => {
  const status = apiError?.response?.status
  return status === 400 || status === 403
}
