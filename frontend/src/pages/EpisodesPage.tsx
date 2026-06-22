// src/pages/EpisodesPage.tsx
import { deleteEpisodeTranscript, deleteFeed, getFeed, ingestEpisode, isError404, listEpisodes, refreshFeed, reingestEpisode } from '@/api/client'
import { ChatInterface } from '@/components/ChatInterface'
import { EpisodeRow } from '@/components/EpisodeRow'
import FeedKebab from '@/components/FeedKebab'
import { Button } from '@/components/ui/button'
import { ButtonGroup } from '@/components/ui/button-group'
import { Input } from '@/components/ui/input'
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import { Separator } from '@/components/ui/separator'
import { formatRelativeDate } from '@/lib/date'
import { invalidateAfterFeedDelete, invalidateEpisode, invalidateFeedAndEpisodes } from '@/lib/queryInvalidation'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { LucideActivity, LucideChevronLeft, LucideCircleAlert, LucideX, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { usePanelRef } from 'react-resizable-panels'


import { useNavigate, useParams } from 'react-router-dom'

const PAGE_SIZE = 20

export default function EpisodesPage() {
  const { feedId } = useParams<{ feedId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'ingested'>('all')
  const [page, setPage] = useState(1)
  const [chatOpen, setChatOpen] = useState(false)
  const chatPanelRef = usePanelRef()
  const scrollContainerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollContainerRef?.current?.scrollTo({ top: 0, behavior: 'smooth' })
  }, [page])


  const { data: feed, isLoading: isFeedLoading, isError: isFeedError, error: feedError } = useQuery({
    queryKey: ['feed', feedId],
    queryFn: () => getFeed(feedId!),
    enabled: !!feedId,
  })

  const { data: episodes, isLoading: isEpisodesLoading, isError: isEpisodesError, error: episodesError } = useQuery({
    queryKey: ['episodes', feedId],
    queryFn: () => listEpisodes(feedId!),
    enabled: !!feedId,
  })

  const ingestMutation = useMutation({
    mutationFn: (episodeId: string) => ingestEpisode(episodeId),
    onSuccess: (_data, episodeId) => invalidateEpisode(queryClient, episodeId, feedId!),
  })

  const reingestMutation = useMutation({
    mutationFn: (episodeId: string) => reingestEpisode(episodeId),
    onSuccess: (_data, episodeId) => invalidateEpisode(queryClient, episodeId, feedId!),
  })

  const deleteTranscriptMutation = useMutation({
    mutationFn: (episodeId: string) => deleteEpisodeTranscript(episodeId),
    onSuccess: (_data, episodeId) => invalidateEpisode(queryClient, episodeId, feedId!),
  })

  const refreshMutation = useMutation({
    mutationFn: refreshFeed,
    onSuccess: (_, feedId) => invalidateFeedAndEpisodes(queryClient, feedId),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteFeed,
    onSuccess: (_, feedId) => {
      invalidateAfterFeedDelete(queryClient, feedId);
      navigate(`/feeds/`);
    },
  })

  const filtered = (episodes ?? [])
    .filter(ep => filter === 'all' || ep.pipeline_status === 'READY')
    .filter(ep => {
      if (!search.trim()) return true
      const q = search.toLowerCase()
      return (
        ep.title?.toLowerCase().includes(q) ||
        ep.description?.toLowerCase().includes(q)
      )
    })

  const ingestedCount = (episodes ?? []).filter(ep => ep.pipeline_status === 'READY').length
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const handleSearch = (value: string) => {
    setSearch(value)
    setPage(1)
  }

  const handleFilter = (value: 'all' | 'ingested') => {
    setFilter(value)
    setPage(1)
  }

  const toggleChat = () => {
    if (chatOpen) {
      chatPanelRef.current?.collapse()
    } else {
      chatPanelRef.current?.expand()
    }
  }

  if (isFeedLoading || isEpisodesLoading) return <div>Loading episodes...</div>

  if (isFeedError) {
    return(
    <p className="text-sm text-destructive">
      {isError404(feedError) ? 'Feed not found.' : 'Failed to load feed details.'}
    </p>
    )
  }

  return (
    <ResizablePanelGroup orientation="horizontal" className="h-full">
      {/* Main content */}
      <ResizablePanel defaultSize="100%" minSize="50%">
        <div ref={scrollContainerRef} className="space-y-6 overflow-y-auto h-full p-6">
          {feed && (
            <div className="flex justify-between">
              <Button variant="link"
                className='p-0'
                onClick={() => navigate(`/feeds/`)}>
                <LucideChevronLeft />
                Feeds
              </Button>

            </div>
          )}
          {feed && (
            <div className="flex items-stretch justify-between gap-6">
              {feed.image_url && <div className='shrink-0 w-1/3 aspect-square  max-h-64 max-w-64 '><img src={feed.image_url} /></div>}

              <div className="space-y-1">
                <h1 className="text-2xl font-bold">{feed.title ?? feed.rss_url}</h1>


                <div className='text-sm flex gap-2 items-center text-muted-foreground'>
                  {feed.episode_count > 0 ? (<>
                    <p>{feed.episode_count} {feed.episode_count === 1 ? "episode" : "episodes"}</p>
                    {feed.episode_count > 0 && (<p><LucideActivity size={12} /></p>)}
                    <p>{feed.latest_episode_published_at && formatRelativeDate(feed.latest_episode_published_at)}</p>

                  </>) : (
                    <p>No episodes</p>
                  )}
                </div>


                {feed.description && (
                  <p className="text-md ">
                    {feed.description}
                  </p>
                )}
              </div>

              <div className='flex flex-col justify-between items-end '>
                {!chatOpen ? (
                  <Button variant="outline" size="sm" disabled={!ingestedCount} onClick={toggleChat}>
                    <Sparkles className="h-4 w-4 mr-1" />
                    Ask AI
                  </Button>
                ) : <div></div>}

                <FeedKebab feedTitle={feed.title}  feedId={feed.id} refreshMutation={refreshMutation} deleteMutation={deleteMutation} />
              </div>
            </div>
          )}

          <Separator />
          {!isEpisodesError && (
            <>
              <Input
                placeholder="Search episodes..."
                value={search}
                onChange={e => handleSearch(e.target.value)}
                className="max-w-100"
              />

              <ButtonGroup>
                <Button
                  variant={filter === 'all' ? 'default' : 'outline'}
                  onClick={() => handleFilter('all')}
                >
                  All
                </Button>
                <Button
                  variant={filter === 'ingested' ? 'default' : 'outline'}
                  onClick={() => handleFilter('ingested')}
                >
                  Ingested ({ingestedCount})
                </Button>
              </ButtonGroup>
            </>
          )}
          {ingestMutation.isError && (
            <p className="text-sm text-destructive"><LucideCircleAlert className='inline-block mr-2' />Failed to start ingestion. Please try again.</p>
          )}
          {reingestMutation.isError && (
            <p className="text-sm text-destructive"><LucideCircleAlert className='inline-block mr-2' />Failed to reingest. Please try again.</p>
          )}
          <div className="space-y-2">
            {episodesError && (
              <p className="text-sm text-destructive"><LucideCircleAlert className='inline-block mr-2' />Failed to load episodes. {episodesError.message}</p>
            )}

            {episodes && episodes.length === 0 && (
              <p className="text-muted-foreground text-sm">No episodes found. Try refreshing the feed.</p>
            )}
            {episodes && episodes.length > 0 && episodes && paginated.length === 0 && (
              <p className="text-muted-foreground text-sm">No episodes match your search.</p>
            )}

            {paginated.map(episode => (
              <EpisodeRow
                key={episode.id}
                episode={episode}
                onIngest={(id) => ingestMutation.mutate(id)}
                // onReingest={(id) => reingestMutation.mutate(id)}
                link={`/episodes/${episode.id}`}
                reingestMutation={reingestMutation}
                deleteTranscriptMutation={deleteTranscriptMutation} />
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <Button
                variant="outline"
                disabled={page === 1}
                onClick={() => setPage(p => p - 1)}
              >
                Previous
              </Button>
              <span className="text-sm text-muted-foreground">
                Page {page} of {totalPages}
              </span>
              <Button
                variant="outline"
                disabled={page === totalPages}
                onClick={() => setPage(p => p + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </div>
      </ResizablePanel>

      {/* Chat panel */}
      <ResizableHandle withHandle />
      <ResizablePanel
        panelRef={chatPanelRef}
        defaultSize={0}
        minSize={320}
        maxSize="50%"
        collapsible
        onResize={(size) => setChatOpen(size.asPercentage > 0)}
        className="h-full flex flex-col "
      >
        <div className="flex items-center shrink-0 p-2 bg-background border-b">
          <h2 className="flex-1">Ask The Pod</h2>
          <Button variant="outline" size="icon" className="rounded-full" onClick={toggleChat}><LucideX /></Button>
        </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            {feedId && (<ChatInterface scopeFeedIds={[feedId]} />)}
          </div>

      </ResizablePanel>

    </ResizablePanelGroup>
  )
}