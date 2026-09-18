/**
 * Adapted from React Bits / ClickSpark (TS-CSS), fetched 2026-09-11.
 * https://reactbits.dev/r/ClickSpark-TS-CSS.json
 * Copyright David Haz — MIT + Commons Clause; see THIRD_PARTY_NOTICES.md.
 * Local changes: scoped triggers, idle suspension, HiDPI and reduced motion.
 */
import { useRef, useEffect, useCallback, type ReactNode, type MouseEvent } from 'react'

interface Spark { x: number; y: number; angle: number; startTime: number }
interface ClickSparkProps {
  children: ReactNode
  sparkSize?: number
  sparkRadius?: number
  sparkCount?: number
  duration?: number
}

export default function ClickSpark({ children, sparkSize = 5, sparkRadius = 17, sparkCount = 6, duration = 320 }: ClickSparkProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const sparksRef = useRef<Spark[]>([])
  const frameRef = useRef(0)
  const drawRef = useRef<(time: number) => void>(() => {})
  const reduceMotionRef = useRef(false)
  const colorRef = useRef('#637267')

  useEffect(() => {
    const canvas = canvasRef.current
    const parent = canvas?.parentElement
    const ctx = canvas?.getContext('2d')
    if (!canvas || !parent || !ctx) return
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const stop = () => {
      cancelAnimationFrame(frameRef.current)
      frameRef.current = 0
      sparksRef.current = []
      ctx.clearRect(0, 0, canvas.width, canvas.height)
    }
    const preferenceChanged = () => {
      reduceMotionRef.current = media.matches
      if (media.matches) stop()
    }
    preferenceChanged()
    media.addEventListener('change', preferenceChanged)

    const resize = () => {
      const rect = parent.getBoundingClientRect()
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(rect.width * ratio)
      canvas.height = Math.round(rect.height * ratio)
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    }
    const observer = new ResizeObserver(resize)
    observer.observe(parent)
    resize()

    const draw = (timestamp: number) => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      sparksRef.current = sparksRef.current.filter(spark => {
        const elapsed = timestamp - spark.startTime
        if (elapsed >= duration) return false
        const progress = Math.max(0, elapsed / duration)
        const eased = progress * (2 - progress)
        const distance = eased * sparkRadius
        const length = sparkSize * (1 - eased)
        ctx.strokeStyle = colorRef.current
        ctx.globalAlpha = 1 - progress
        ctx.lineWidth = 1.5
        ctx.lineCap = 'round'
        ctx.beginPath()
        ctx.moveTo(spark.x + distance * Math.cos(spark.angle), spark.y + distance * Math.sin(spark.angle))
        ctx.lineTo(spark.x + (distance + length) * Math.cos(spark.angle), spark.y + (distance + length) * Math.sin(spark.angle))
        ctx.stroke()
        return true
      })
      frameRef.current = sparksRef.current.length ? requestAnimationFrame(draw) : 0
    }
    drawRef.current = draw
    const visibilityChanged = () => { if (document.hidden) stop() }
    document.addEventListener('visibilitychange', visibilityChanged)
    return () => {
      stop()
      observer.disconnect()
      media.removeEventListener('change', preferenceChanged)
      document.removeEventListener('visibilitychange', visibilityChanged)
    }
  }, [duration, sparkRadius, sparkSize])

  const handleClick = useCallback((event: MouseEvent<HTMLDivElement>) => {
    if (reduceMotionRef.current || event.detail === 0 || !(event.target instanceof Element)) return
    const trigger = event.target.closest<HTMLElement>('[data-click-spark]')
    if (!trigger || !event.currentTarget.contains(trigger)
      || trigger.matches(':disabled, [aria-disabled="true"], .ant-btn-loading')) return
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const x = event.clientX - rect.left
    const y = event.clientY - rect.top
    colorRef.current = getComputedStyle(trigger).color
    const now = performance.now()
    sparksRef.current = [...sparksRef.current.slice(-48), ...Array.from({ length: sparkCount }, (_, i) => ({
      x, y, angle: (2 * Math.PI * i) / sparkCount, startTime: now,
    }))]
    if (!frameRef.current) frameRef.current = requestAnimationFrame(drawRef.current)
  }, [sparkCount])

  return (
    <div className="mnemox-click-spark" onClickCapture={handleClick}>
      {children}
      <canvas ref={canvasRef} className="mnemox-click-spark-canvas" aria-hidden="true" />
    </div>
  )
}
