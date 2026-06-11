// src/pages/EpisodeDetailPage.tsx
import { getEpisode, ingestEpisode, listSpeakers, reingestEpisode } from '@/api/client'
import { SpeakerRow } from '@/components/SpeakerRow'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { useEpisodeStatus } from '@/hooks/useEpisodeStatus'
import { ACTIVE_STATUSES, formatDate, formatDuration } from '@/lib/episode'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, LoaderCircle } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'


export default function EpisodeDetailPage() {
  const { episodeId } = useParams<{ episodeId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: episode, isLoading } = useQuery({
    queryKey: ['episode', episodeId],
    queryFn: () => getEpisode(episodeId!),
    enabled: !!episodeId,
  })

  const { data: speakers } = useQuery({
    queryKey: ['speakers', episodeId],
    queryFn: () => listSpeakers(episodeId!),
    enabled: !!episodeId && episode?.pipeline_status === 'READY',
  })

  const liveStatus = useEpisodeStatus(
    episode && ACTIVE_STATUSES.includes(episode.pipeline_status) ? episodeId! : null
  )

  const status = liveStatus?.status ?? episode?.pipeline_status
  const stage = liveStatus?.stage ?? episode?.pipeline_stage
  const progress = liveStatus?.progress ?? episode?.pipeline_progress
  const isActive = ACTIVE_STATUSES.includes(status ?? '')

  const ingestMutation = useMutation({
    mutationFn: () => ingestEpisode(episodeId!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['episode', episodeId] }),
  })

  const reingestMutation = useMutation({
    mutationFn: () => reingestEpisode(episodeId!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['episode', episodeId] }),
  })

  if (isLoading) return <div>Loading episode...</div>
  if (!episode) return <div>Episode not found.</div>

  return (
    <div className="space-y-6">
      <Button variant="outline" size="sm" onClick={() => navigate(-1)}>
        Back
      </Button>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <CardTitle>{episode.title ?? 'Untitled'}</CardTitle>
              <div className="flex items-center gap-3 text-sm text-muted-foreground">
                <span>{formatDate(episode.published_at)}</span>
                <span>{formatDuration(episode.duration_seconds)}</span>
                <Badge variant={status === 'READY' ? 'default' : status === 'ERROR' ? 'destructive' : 'secondary'}>
                  {status}
                </Badge>
              </div>
            </div>
            <Button
              disabled={isActive || ingestMutation.isPending || reingestMutation.isPending}
              onClick={() => status === 'READY' ? reingestMutation.mutate() : ingestMutation.mutate()}
            >
              {isActive ? <LoaderCircle className="animate-spin " /> : null}

              {isActive ? 'Ingesting...' : status === 'READY' ? 'Reingest' : 'Ingest'}
            </Button>
          </div>
        </CardHeader>
        <CardContent>

        {episode.description && (
          <CardDescription>{episode.description}</CardDescription>
        )}

        {isActive && stage && (
          <p className="text-sm text-muted-foreground">
            {stage}{progress != null ? ` — ${Math.round(progress * 100)}%` : ''}
          </p>
        )}
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => navigator.clipboard.writeText(episode.id)}>
            <Copy />{episode.id}
          </Button>
        </div>
        </CardContent>

      </Card>

      {status === 'READY' && (
        <>
          <Separator />
          <div className="space-y-2">
            <h2 className="font-semibold">Speakers</h2>
            {!speakers?.length && (
              <p className="text-sm text-muted-foreground">No speakers identified.</p>
            )}
            {speakers?.map(speaker => (
              <SpeakerRow
                key={speaker.speaker_id}
                speaker={speaker}
                episodeId={episodeId!}
              />
            ))}
          </div>
        </>
      )}

      {status === 'PENDING' && (
        <p className="text-sm text-muted-foreground">
          Ingest this episode to identify speakers.
        </p>
      )}

      {status === 'ERROR' && (
        <p className="text-sm text-destructive">
          Ingestion failed. Try reingesting the episode.
        </p>
      )}
    </div>
  )
}