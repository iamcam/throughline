// src/components/EpisodeRow.tsx
import type { Episode } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useEpisodeStatus } from '@/hooks/useEpisodeStatus'
import { ACTIVE_STATUSES, formatDate, formatDuration } from '@/lib/episode'
import { Copy, LoaderCircle, LucideArrowUpRight, LucideCloudDownload, LucideRefreshCw, LucideSparkles } from 'lucide-react'


interface EpisodeRowProps {
  episode: Episode
  onIngest: (episodeId: string) => void
  onReingest: (episodeId: string) => void
  onNavigate: (episodeId: string) => void
}


export function EpisodeRow({ episode, onIngest, onReingest, onNavigate }: EpisodeRowProps) {

  const liveStatus = useEpisodeStatus(ACTIVE_STATUSES.includes(episode.pipeline_status) ? episode.id : null)
  const status = liveStatus?.status ?? episode.pipeline_status
  const stage = liveStatus?.stage ?? episode.pipeline_stage
  const progress = liveStatus?.progress ?? episode.pipeline_progress
  const isActive = ACTIVE_STATUSES.includes(status)
  const isReady = status === 'READY'

  return (
    <Card className={isReady ? 'border-2 border-accent' : ''}>
      <CardHeader className='flex flex-row'>
        <div className='flex-1 w-100'>
          <CardTitle className="line-clamp-2 flex flex-row gap-2 items-center">
            {isReady && <LucideSparkles className="text-accent size-4" />}
            {episode.title ?? 'Untitled'}
          </CardTitle>
            {episode.description && (<CardDescription className="line-clamp-2">{episode.description}</CardDescription>)}
        </div>
        <Button variant="outline" size="icon" onClick={() => onNavigate(episode.id)}>
          <LucideArrowUpRight className='shrink-0' />
        </Button>
      </CardHeader>
      <CardContent >
        <div className="flex justify-between items-center">
          <div className="text-sm text-muted-foreground flex gap-4 items-center">

            <span>{formatDate(episode.published_at)}</span>
            <span>{formatDuration(episode.duration_seconds)}</span>
            {status !== 'READY' && <StatusBadge status={status} />}
          </div>
            {isActive && stage && (
              <div className="text-sm text-muted-foreground">
                {stage}{progress != null ? ` — ${Math.round(progress * 100)}%` : ''}
              </div>
            )}

          <div className="flex gap-2">
              <Button
              disabled={isActive}
              onClick={() => status === 'READY' ? onReingest(episode.id) : onIngest(episode.id)}
            >
              {isActive ? <LoaderCircle className="animate-spin " /> : null}
              {isActive ? 'Ingesting...' : status === 'READY' ? <><LucideRefreshCw />Reingest</> : <><LucideCloudDownload />Ingest</>}
            </Button>
          </div>
        </div>
        <div className="flex items-center gap-2 ">
          <Button variant="outline"  onClick={() => navigator.clipboard.writeText(episode.id)}>
            <Copy />{episode.id.slice(0,5)} … {episode.id.slice(-5)}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function StatusBadge({ status }: { status: string }) {
  const variants: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
    READY: 'default',
    ERROR: 'destructive',
    PENDING: 'outline',
  }
  const variant = variants[status] ?? 'secondary'
  return <Badge variant={variant}>{status}</Badge>
}