// src/components/ElapsedTime.tsx
import { useNow } from '@/hooks/useNow'
import { formatElapsed } from '@/lib/date'

export function ElapsedTime({ since, className }: { since: string | null, className?: string | undefined }) {
  const now = useNow()
  if (!since) return null
  return (
    <time dateTime={since} title={new Date(since).toLocaleString()} className={className}>
      {formatElapsed(since, now)}
    </time>
  )
}