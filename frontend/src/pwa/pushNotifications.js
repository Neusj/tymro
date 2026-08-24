import { pushApi } from '../api/client'

export function isPushSupported() {
  return (
    typeof window !== 'undefined' &&
    'Notification' in window &&
    'serviceWorker' in navigator &&
    'PushManager' in window
  )
}

export function browserNotificationPermission() {
  if (!isPushSupported()) {
    return 'unsupported'
  }
  return Notification.permission
}

export function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = `${base64String}${padding}`.replace(/-/g, '+').replace(/_/g, '/')
  const rawData = window.atob(base64)
  const outputArray = new Uint8Array(rawData.length)
  for (let i = 0; i < rawData.length; i += 1) {
    outputArray[i] = rawData.charCodeAt(i)
  }
  return outputArray
}

export async function enablePushNotifications(vapidPublicKey) {
  if (!isPushSupported()) {
    return { ok: false, reason: 'unsupported' }
  }
  if (!vapidPublicKey) {
    return { ok: false, reason: 'not_configured' }
  }

  let permission = Notification.permission
  if (permission === 'default') {
    permission = await Notification.requestPermission()
  }
  if (permission !== 'granted') {
    await pushApi.updatePreferences({ prompt_status: permission === 'denied' ? 'blocked' : 'dismissed' })
    return { ok: false, reason: permission }
  }

  const registration = await navigator.serviceWorker.ready
  let subscription = await registration.pushManager.getSubscription()
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
    })
  }

  await pushApi.registerSubscription(subscription.toJSON())
  const preferences = await pushApi.getPreferences()
  return { ok: true, preferences }
}

export async function disablePushNotifications() {
  if (!isPushSupported()) {
    await pushApi.updatePreferences({ push_enabled: false })
    return { ok: true }
  }
  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.getSubscription()
  if (subscription) {
    await pushApi.removeSubscription(subscription.endpoint)
    await subscription.unsubscribe()
  }
  await pushApi.updatePreferences({ push_enabled: false })
  return { ok: true }
}
