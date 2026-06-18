// src/pages/EpisodeDetailPage.tsx
import { getEpisode, ingestEpisode, isError404, listSpeakers, reingestEpisode } from '@/api/client'
import { ChatInterface } from '@/components/ChatInterface'
import { ExpandableDescription } from '@/components/ExpandableDescription'
import { SpeakerRow } from '@/components/SpeakerRow'
import { TranscriptViewer } from '@/components/TranscriptViewer'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter } from '@/components/ui/card'
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import { Separator } from '@/components/ui/separator'
import StatusBadge from '@/components/ui/StatusBadge'
import { useEpisodeStatus } from '@/hooks/useEpisodeStatus'
import { ACTIVE_STATUSES, formatDate, formatDuration } from '@/lib/episode'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { LoaderCircle, LucideCircleAlert, LucideCloudDownload, LucideCopy, LucideEllipsis, LucideMessageCircleDashed, LucideRefreshCw, LucideX, LucideXCircle, Sparkles } from 'lucide-react'
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
      chatPanelRef.current?.resize("33%")
    }
  }
  const { episodeId } = useParams<{ episodeId: string }>()
  const queryClient = useQueryClient()

  const { data: episode, isLoading, isError, error } = useQuery({
    queryKey: ['episode', episodeId],
    queryFn: () => getEpisode(episodeId!),
    enabled: !!episodeId,
  })

  const { data: speakers, isLoading: isSpeakersLoading, isError: speakersError } = useQuery({
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

  if (isLoading) return (
    <div className="p-6"><LucideEllipsis className='inline-block mr-2 animate-pulse' />Loading episode...</div>
  )
  if (isError || !episodeId) return (
    <div className="p-6 text-destructive">
      {isError404(error) ? "Episode not found" : (
        <><LucideCircleAlert className='inline-block mr-2' /> Failed to load episode.</>
      )}
    </div>
  )
  if (!episode) return (
    <div className="p-6 text-destructive">
      <LucideCircleAlert className='inline-block mr-2' /> Failed to load episode.
    </div>
  )

  return (
    <ResizablePanelGroup orientation="horizontal" className="h-full">
      <ResizablePanel defaultSize="100%" minSize="50%">
        <div className="space-y-6 overflow-y-auto h-full p-6">

          {/* Header row — replaces the back button */}
          <div className="flex items-center justify-between">
            <h1 className="font-bold">{episode.title ?? 'Untitled'}</h1>
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
              </div>
              <Button variant="outline" onClick={() => navigator.clipboard.writeText(episode.id)}>
                <LucideCopy />{episode.id}
              </Button>
            </div>
            <div className='flex flex-col items-end gap-2'>
              <Button
                disabled={isActive || ingestMutation.isPending || reingestMutation.isPending}
                onClick={() => status === 'READY' ? reingestMutation.mutate() : ingestMutation.mutate()}
              >
                {isActive ? <LoaderCircle className="animate-spin " /> : null}

                {isActive ? 'Ingesting...' : status === 'READY' ? <><LucideRefreshCw />Reingest</> : <><LucideCloudDownload />Ingest</>}
              </Button>

              {status && status !== 'READY' && <StatusBadge status={status} />}
            </div>
          </div>
          <Card>
            <CardContent>
              {episode && episode.description && episode.audio_url && (
                <div className='flex flex-col gap-4'>
                  <audio
                    src={episode.audio_url}
                    controls
                    className="mt-2 w-92 max-w-full h-8"
                  />

                  <CardDescription>
                    <ExpandableDescription collapsedLines={4} description={episode.description} />
                  </CardDescription>
                </div>
            )}

            {isActive && stage && (
              <p className="text-sm text-muted-foreground">
                {stage}{progress != null ? ` — ${Math.round(progress * 100)}%` : ''}
              </p>
            )}
            {ingestMutation.isError && (
              <p className="text-sm text-destructive"><LucideXCircle className='inline-block mr-2'/>Failed to start ingestion. Please try again.</p>
            )}
            {reingestMutation.isError && (
                <p className="text-sm text-destructive"><LucideXCircle className='inline-block mr-2' />Failed to reingest. Please try again.</p>
            )}
              <CardFooter>

              </CardFooter>
            </CardContent>

          </Card>

          {status === 'READY' && (
            <>
              <Separator />
              <div className="space-y-2">
                <h2 className="font-semibold">Speakers</h2>
                {isSpeakersLoading && <div className='text-muted-foreground'>...</div>}
                {speakersError && (
                  <p className="text-sm text-muted-foreground">
                    <LucideMessageCircleDashed className='inline-block mr-2' size={16} />
                    Failed to load speakers.
                  </p>
                )}
                {!isSpeakersLoading && !speakersError && !speakers?.length && (
                  <p className="text-sm text-muted-foreground">No speakers identified.</p>
                )}
                {!speakersError && speakers?.map(speaker => (
                  <SpeakerRow
                    key={speaker.speaker_id}
                    speaker={speaker}
                    episodeId={episodeId}
                  />
                ))}
              </div>
              <Separator />
              <h2 className="font-semibold">Transcript</h2>
              <TranscriptViewer episodeId={episodeId} />
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