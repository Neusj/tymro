import { useEffect, useRef, useState } from 'react'
import { BrowserQRCodeReader } from '@zxing/browser'

// Escáner de QR in-app. Controla la cámara y el <video> al 100% para que se vea
// nítido y profesional (cámara trasera, alta resolución, sin escalado que pixele),
// con un marco/retícula de escaneo encima. Llama a `onDecode(text)` una sola vez por
// lectura y se pausa hasta que el padre lo reinicie (cambiando `paused`).
export default function QrCameraScanner({ onDecode, onError, paused = false }) {
  const videoRef = useRef(null)
  const controlsRef = useRef(null)
  const decodedRef = useRef(false)
  const [cameraError, setCameraError] = useState('')
  const [starting, setStarting] = useState(true)
  // Cambiar este valor fuerza un reinicio del efecto (botón "Reintentar").
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (paused) {
      return undefined
    }

    let cancelled = false
    decodedRef.current = false
    setCameraError('')
    setStarting(true)

    const reader = new BrowserQRCodeReader(undefined, {
      delayBetweenScanAttempts: 150,
    })

    const constraints = {
      audio: false,
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1280 },
        height: { ideal: 720 },
      },
    }

    reader
      .decodeFromConstraints(constraints, videoRef.current, (result, err, controls) => {
        if (cancelled) {
          return
        }
        if (!controlsRef.current) {
          controlsRef.current = controls
          setStarting(false)
        }
        if (result && !decodedRef.current) {
          decodedRef.current = true
          // Pausamos el stream apenas leemos para no re-disparar la misma lectura.
          controls.stop()
          controlsRef.current = null
          onDecode?.(result.getText())
        }
        // `err` se dispara en cada frame sin QR (NotFoundException): se ignora.
      })
      .catch((startError) => {
        if (cancelled) {
          return
        }
        setStarting(false)
        const message = describeCameraError(startError)
        setCameraError(message)
        onError?.(startError)
      })

    return () => {
      cancelled = true
      try {
        controlsRef.current?.stop()
      } catch {
        /* noop */
      }
      controlsRef.current = null
      stopVideoStream(videoRef.current)
    }
  }, [paused, attempt, onDecode, onError])

  if (cameraError) {
    return (
      <div className="rounded-2xl border border-brand-red/50 bg-brand-red/10 p-5 text-sm text-red-200">
        <p className="font-medium">{cameraError}</p>
        <button
          type="button"
          onClick={() => setAttempt((value) => value + 1)}
          className="mt-3 rounded-lg border border-red-300/50 px-3 py-2 text-xs font-semibold text-red-100"
        >
          Reintentar
        </button>
      </div>
    )
  }

  return (
    <div className="relative aspect-square w-full overflow-hidden rounded-2xl border border-brand-line bg-black">
      <video
        ref={videoRef}
        className="h-full w-full object-cover"
        muted
        autoPlay
        playsInline
      />
      {/* Overlay con marco de escaneo: esquinas resaltadas + línea de barrido. */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute inset-0 bg-black/30" />
        <div className="absolute left-1/2 top-1/2 h-[62%] w-[62%] -translate-x-1/2 -translate-y-1/2">
          <div className="absolute inset-0 rounded-2xl shadow-[0_0_0_9999px_rgba(0,0,0,0.45)]" />
          <Corner className="left-0 top-0 border-l-2 border-t-2 rounded-tl-xl" />
          <Corner className="right-0 top-0 border-r-2 border-t-2 rounded-tr-xl" />
          <Corner className="bottom-0 left-0 border-b-2 border-l-2 rounded-bl-xl" />
          <Corner className="bottom-0 right-0 border-b-2 border-r-2 rounded-br-xl" />
          {!starting ? (
            <div className="absolute inset-x-3 top-1/2 h-0.5 -translate-y-1/2 bg-brand-orange/80 shadow-[0_0_12px_2px_rgba(255,122,0,0.6)]" />
          ) : null}
        </div>
      </div>
      {starting ? (
        <p className="absolute inset-x-0 bottom-3 text-center text-xs font-medium text-white/80">
          Iniciando cámara…
        </p>
      ) : null}
    </div>
  )
}

function Corner({ className }) {
  return <span className={`absolute h-7 w-7 border-brand-orange ${className}`} />
}

function stopVideoStream(video) {
  const stream = video?.srcObject
  if (stream && typeof stream.getTracks === 'function') {
    stream.getTracks().forEach((track) => track.stop())
  }
  if (video) {
    video.srcObject = null
  }
}

function describeCameraError(error) {
  const name = error?.name || ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'No diste permiso para usar la cámara. Habilítala en tu navegador y reintenta.'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return 'No encontramos una cámara disponible en este dispositivo.'
  }
  if (name === 'NotReadableError') {
    return 'La cámara está siendo usada por otra aplicación. Ciérrala y reintenta.'
  }
  return 'No se pudo iniciar la cámara. Reintenta.'
}
