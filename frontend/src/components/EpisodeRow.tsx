// src/components/EpisodeRow.tsx
import type { Episode } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import StatusBadge from '@/components/ui/StatusBadge'
import { useEpisodeStatus } from '@/hooks/useEpisodeStatus'
import { formatDate, formatDuration } from '@/lib/date'
import { ACTIVE_STATUSES } from '@/lib/episode'
import { stripMarkdown } from '@/lib/text'
import { LoaderCircle, LucideArrowUpRight, LucideCloudDownload, LucideRefreshCw, LucideSparkles } from 'lucide-react'
import { Link } from 'react-router-dom'


interface EpisodeRowProps {
  episode: Episode
  onIngest: (episodeId: string) => void
  onReingest: (episodeId: string) => void
  link: string
}


export function EpisodeRow({ episode, link, onIngest, onReingest }: EpisodeRowProps) {

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
            <Link to={link} className="hover:text-cyan-500 transition-colors">{episode.title ?? 'Untitled'}</Link>
          </CardTitle>
          {episode.description && (
            <CardDescription>
              <div className="text-sm text-muted-foreground flex gap-4 py-2">
                <div>{formatDate(episode.published_at)}</div>
                <div>{formatDuration(episode.duration_seconds)}</div>
              </div>
              {isActive && stage && (
                <div className="text-sm text-muted-foreground">
                  {stage}{progress != null ? ` — ${Math.round(progress * 100)}%` : ''}
                </div>
              )}
              <div className="line-clamp-2">
                {stripMarkdown(episode.description)}
              </div>
            </CardDescription>
          )}
        </div>

        <LucideArrowUpRight className='shrink-0' />

      </CardHeader>
      <CardContent >
        <div className="flex justify-end items-center">

          <div className="flex flex-col items-end gap-2">
              <Button
              disabled={isActive}
              onClick={(e) => {
                e.stopPropagation();
                if (status === 'READY') onReingest(episode.id)
                else onIngest(episode.id);
              }}
              >
              {isActive ? <LoaderCircle className="animate-spin " /> : null}
              {isActive ? 'Ingesting...' : status === 'READY' ? <><LucideRefreshCw />Reingest</> : <><LucideCloudDownload />Ingest</>}
            </Button>
            {ACTIVE_STATUSES.includes(status) && <StatusBadge status={status} />}

          </div>
        </div>
        <div className="flex items-center gap-2 ">
          {/* <Button variant="outline" onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(episode.id) }}>
            <Copy />{episode.id.slice(0,5)} … {episode.id.slice(-5)}
          </Button> */}
        </div>
      </CardContent>
    </Card>
  )
}

