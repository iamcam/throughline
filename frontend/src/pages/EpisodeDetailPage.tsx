// src/pages/EpisodeDetailPage.tsx
import { deleteEpisodeTranscript, getEpisode, getFeed, ingestEpisode, isError404, listSpeakers, reingestEpisode } from '@/api/client'
import { ChatInterface } from '@/components/ChatInterface'
import EpisodeKebab from '@/components/EpisodeKebab'
import { ExpandableDescription } from '@/components/ExpandableDescription'
import { SpeakerRow } from '@/components/SpeakerRow'
import { TranscriptViewer } from '@/components/TranscriptViewer'
import { Button } from '@/components/ui/button'

import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import { Separator } from '@/components/ui/separator'
import StatusBadge from '@/components/ui/StatusBadge'
import { useEpisodeStatus } from '@/hooks/useEpisodeStatus'
import { formatDate, formatDuration } from '@/lib/date'
import { ACTIVE_STATUSES } from '@/lib/episode'
import { invalidateEpisode } from '@/lib/queryInvalidation'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { LucideChevronLeft, LucideCircleAlert, LucideCloudDownload, LucideEllipsis, LucideLoaderCircle, LucideMessageCircleDashed, LucideX, LucideXCircle, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { usePanelRef } from 'react-resizable-panels'
import { useNavigate, useParams } from 'react-router-dom'

export default function EpisodeDetailPage() {
  const [chatOpen, setChatOpen] = useState(false)
  const chatPanelRef = usePanelRef()
  const navigate = useNavigate()

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

  const { data: feed } = useQuery({
    queryKey: ['feeds', episode?.feed_id],
    queryFn: () => getFeed(episode!.feed_id),
    enabled: !!episodeId && !!episode,
  })

  const liveStatus = useEpisodeStatus(
    episode && ACTIVE_STATUSES.includes(episode.pipeline_status) ? episodeId! : null
  )

  const status = liveStatus?.status ?? episode?.pipeline_status
  const stage = liveStatus?.stage ?? episode?.pipeline_stage
  const progress = liveStatus?.progress ?? episode?.pipeline_progress
  const isActive = ACTIVE_STATUSES.includes(status ?? '')
  const coverArt = feed?.image_url || null

  const ingestMutation = useMutation({
    mutationFn: () => ingestEpisode(episodeId!),
    onSuccess: () => invalidateEpisode(queryClient, episodeId!, episode!.feed_id),
  })

  const reingestMutation = useMutation({
    mutationFn: (episodeId: string) => reingestEpisode(episodeId),
    onSuccess: (_data, episodeId) => invalidateEpisode(queryClient, episodeId, episode!.feed_id),
  })

  const deleteTranscriptMutation = useMutation({
    mutationFn: (episodeId: string) => deleteEpisodeTranscript(episodeId),
    onSuccess: (_data, episodeId) => invalidateEpisode(queryClient, episodeId, episode!.feed_id),
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

  if( status ) return (
    <ResizablePanelGroup orientation="horizontal" className="h-full">
      <ResizablePanel defaultSize="100%" minSize="50%" className='scrollbar-thin scrollbar-gutter-auto'>
        <div className="space-y-6 h-full p-6 ">
          {feed &&
            <Button variant="link" size="default"
              className='px-0 hover:text-hover'
              aria-label="back to feed"
              onClick={() => navigate(`/feeds/${feed.id}/episodes`)}>
            <LucideChevronLeft />
            {feed.title}
          </Button>}

          <div className='flex flex-row gap-4'>

            {/* Left column - cover art, if any */}
            {coverArt && <div className='shrink-0'><img className="aspect-square w-54" src={coverArt} alt="cover artwork for episode" /></div>}

            {/* Center - title, description, etc column */}
            <div className='grow flex flex-col gap-2'>
              <div className='flex flex-col gap-2 grow items-start'>
                <h1 className="font-bold">{episode.title ?? 'Untitled'}</h1>

                <div className="flex items-center gap-3 text-sm text-muted-foreground">
                  <span>{formatDate(episode.published_at)}</span>
                  <span>{formatDuration(episode.duration_seconds)}</span>
                </div>

                {/* <CopyButton copyValue={episode.id} displayText={episode.id.slice(0, 4) + "..." + episode.id.slice(-4)} /> */}
              </div>

              {episode && episode.audio_url && (
                <div className=''>
                  <audio
                    src={episode.audio_url}
                    controls
                    className="mt-2 w-92 max-w-full h-8"
                  />
                </div>
              )}

            </div>

            {/* Right / Buttons column */}
            <div className={'flex flex-col items-end ' + (!chatOpen ? 'justify-between' : 'justify-end')}>
              {!chatOpen && (
                <Button disabled={status !== "READY"} variant="outline" size="sm" aria-label="open AI chat" onClick={toggleChat}>
                  <Sparkles className="h-4 w-4 mr-1" />
                  Ask AI
                </Button>
              )}

              <div className='flex flex-col items-end gap-2'>

                {(status === "ERROR" || status === "PENDING") && (
                  <div className='flex gap-2 items-center'>
                    {status === "ERROR" && <StatusBadge status={status} />}

                    <Button
                      disabled={isActive}
                      onClick={() => ingestMutation.mutate()}
                      aria-label="Transcribe episode"
                    >
                      <LucideCloudDownload /> Transcribe
                    </Button>
                  </div>
                )}

              {ACTIVE_STATUSES.includes(status) ? (
                <div className='flex items-center gap-2'>
                {ACTIVE_STATUSES.includes(status) && <StatusBadge status={status} />}
                <Button size="icon" variant="outline" aria-label="loading" disabled={true}><LucideLoaderCircle className='animate-spin' /></Button>
                </div>
              ) : (status === "READY" ? (
                <EpisodeKebab
                  disabled={isActive}
                  episodeId={episode.id}
                  episodeTitle={episode.title}
                  reingestMutation={reingestMutation}
                  deleteTranscriptMutation={deleteTranscriptMutation}
                />
              ) : undefined)
              }


              </div>

            </div>
          </div>

          {episode && episode.description && (
            <>
              <h2 className="font-semibold">Summary</h2>
              <ExpandableDescription collapsedLines={3} description={episode.description} />
            </>
          )}

        {isActive && stage && (
          <p className="text-sm text-muted-foreground">
            {stage}{progress != null ? ` — ${Math.round(progress * 100)}%` : ''}
          </p>
        )}
        {ingestMutation.isError && (
          <p className="text-sm text-destructive"><LucideXCircle className='inline-block mr-2'/>Failed to start transcription. Please try again.</p>
        )}
        {reingestMutation.isError && (
            <p className="text-sm text-destructive"><LucideXCircle className='inline-block mr-2' />Failed to transcribe. Please try again.</p>
        )}

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
                {!speakersError && speakers && (
                  <div className='text-xs text-muted-foreground' >Speaker names are inferred and may contain mistakes. Pleae verify.</div>
                )}
            </div>
            <Separator />
            <h2 className="font-semibold">Transcript</h2>
            <TranscriptViewer episodeId={episodeId} />
          </>
        )}

          {status === 'PENDING' && (
            <p className="text-sm text-muted-foreground">
              Transcribe this episode to identify speakers.
            </p>
          )}

          {status === 'ERROR' && (
            <p className="text-sm text-destructive">
              Transcription failed. Please try again.
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
        <div className="flex items-center shrink-0 p-2 bg-background border-b px-2">
          <h2 className="flex-1">Ask The Pod</h2>
          <Button variant="outline" size="icon" className="rounded-full" aria-label="close chat" onClick={toggleChat}><LucideX /></Button>
        </div>

        <div className="flex-1 min-h-0 overflow-hidden">
            {episodeId && (<ChatInterface scopeEpisodeIds={[episodeId]} />)}
          </div>
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}