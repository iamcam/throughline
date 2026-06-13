// src/pages/EpisodeDetailPage.tsx
import { getEpisode, ingestEpisode, listSpeakers, reingestEpisode } from '@/api/client'
import { ChatInterface } from '@/components/ChatInterface'
import { SpeakerRow } from '@/components/SpeakerRow'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription } from '@/components/ui/card'
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import { Separator } from '@/components/ui/separator'
import { useEpisodeStatus } from '@/hooks/useEpisodeStatus'
import { ACTIVE_STATUSES, formatDate, formatDuration } from '@/lib/episode'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, LoaderCircle, LucideX, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { usePanelRef } from 'react-resizable-panels'
import { useParams } from 'react-router-dom'

export default function EpisodeDetailPage() {
  const [chatOpen, setChatOpen] = useState(false)
  const chatPanelRef = usePanelRef()

  const toggleChat = () => {
    if (chatOpen) {
      chatPanelRef.current?.collapse()
    } else {
      chatPanelRef.current?.expand()
    }
  }
  const { episodeId } = useParams<{ episodeId: string }>()
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
    <ResizablePanelGroup orientation="horizontal" className="h-full">
      <ResizablePanel defaultSize="100%" minSize="50%">
        <div className="space-y-6 overflow-y-auto h-full p-6">

          {/* Header row — replaces the back button */}
          <div className="flex items-center justify-between">
            <h1>{episode.title ?? 'Untitled'}</h1>
            {!chatOpen && (
              <Button disabled={status !== "READY"} variant="outline" size="sm" onClick={toggleChat}>
                <Sparkles className="h-4 w-4 mr-1" />
                Ask AI
              </Button>
            )}
          </div>

          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
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
          <Card>
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
      </ResizablePanel>

      <ResizableHandle withHandle />
      <ResizablePanel
        panelRef={chatPanelRef}
        defaultSize={0}
        minSize={320}
        maxSize="50%"
        collapsible
        onResize={(size) => setChatOpen(size.asPercentage > 0)}
        className="h-full flex flex-col"
      >
        <div className="flex items-center shrink-0 p-2 bg-background border-b">
          <h2 className="flex-1">Ask The Pod</h2>
          <Button variant="outline" size="icon" className="rounded-full" onClick={toggleChat}><LucideX /></Button>
        </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            {episodeId && (<ChatInterface scopeEpisodeIds={[episodeId]} />)}
          </div>
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}