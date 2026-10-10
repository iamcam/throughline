// src/components/EpisodeRow.tsx
import { getEpisodeArtworkUrl, type Episode } from '@/api/client'
import EpisodeKebab from '@/components/EpisodeKebab'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import CoverArt from '@/components/ui/CoverArt'
import StatusBadge from '@/components/ui/StatusBadge'
import { useEpisodeStatus } from '@/hooks/useEpisodeStatus'
import { formatDate, formatDuration } from '@/lib/date'
import { ACTIVE_STATUSES, canReset } from '@/lib/episode'
import { stripMarkdown } from '@/lib/text'
import { LucideCloudDownload, LucideSparkles } from 'lucide-react'
import { Link } from 'react-router-dom'


interface EpisodeRowProps {
  episode: Episode
  onIngest: (episodeId: string) => void
  link: string
}

export function EpisodeRow({ episode, link, onIngest }: EpisodeRowProps) {

  const liveStatus = useEpisodeStatus(episode.id, episode.pipeline_status)
  const status = liveStatus?.status ?? episode.pipeline_status
  const isActive = ACTIVE_STATUSES.includes(status)
  const isReady = status === 'READY'

  return (
    <Card className={"pb-0 drop-shadow " + (isReady ? 'border-2 border-accent' : '')}>
      {isReady && <LucideSparkles className="text-accent size-4 absolute top-2 left-2" />}
      <CardHeader className='flex flex-col sm:flex-row gap-(--card-spacing)'>
        {episode.image_url && <Link to={link}>
          <CoverArt src={episode.image_url}
            alt="Episode cover artwork"
            className="w-42 max-w-full flex items-center justify-center shadow-md aspect-square text-primary"
            proxySrc={getEpisodeArtworkUrl(episode.id)}
          />
      </Link>}
          <div className='flex-1 w-full'>

          <CardTitle className="text-xl line-clamp-2 flex flex-row gap-2 ">
            <Link to={link} className="hover:text-hover transition-colors">{episode.title ?? 'Untitled'}</Link>
          </CardTitle>
          {episode.description && (
            <CardDescription className='text-md'>
              <div className="flex gap-4 pb-4 flex-wrap items-center w-auto">
                <div>{formatDate(episode.published_at)}</div>
                <div>{formatDuration(episode.duration_seconds)}</div>
              </div>
              <div className="line-clamp-4 sm:line-clamp-2 text-foreground">
                {stripMarkdown(episode.description)}
              </div>
            </CardDescription>
          )}
        </div>

      </CardHeader>
      <CardContent className='text-primary pb-6'>
        <div className="flex justify-end items-center">

          <div className="flex flex-col items-end gap-2">

            {status === "PENDING" || status === "ERROR" ? (
              <div className='flex gap-2 items-center'>
                {status === "ERROR" && (<StatusBadge status="ERROR" />)}

                <Button
                  disabled={isActive}
                  onClick={(e) => {
                    e.stopPropagation();
                    onIngest(episode.id);
                  }}
                >
                  <LucideCloudDownload /> Transcribe
                </Button>
                </div>
            ) : undefined}


            <div className='flex items-center gap-2'>
              {ACTIVE_STATUSES.includes(status) && (
                <StatusBadge status={status} />
              )}
              {(ACTIVE_STATUSES.includes(status) || status === "READY") && (
                  <EpisodeKebab
                    disabled={!canReset(status)}
                    episodeId={episode.id}
                    episodeTitle={episode.title}
                    feedId={episode.feed_id}
                    status={status}
                  />
                )}
              </div>


          </div>
        </div>
        {/* Episode ID copy button */}
        {/* <div className="flex items-center gap-2 ">
          <Button variant="outline" onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(episode.id) }}>
            <LucideCopy />{episode.id.slice(0,5)} … {episode.id.slice(-5)}
          </Button>
        </div> */}
      </CardContent>
    </Card>
  )
}

