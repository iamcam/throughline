// src/pages/EpisodesPage.tsx
import { getFeed, ingestEpisode, listEpisodes, reingestEpisode } from '@/api/client'
import { ChatInterface } from '@/components/ChatInterface'
import { EpisodeRow } from '@/components/EpisodeRow'
import { Button } from '@/components/ui/button'
import { ButtonGroup } from '@/components/ui/button-group'
import { Input } from '@/components/ui/input'
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import { Separator } from '@/components/ui/separator'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { LucideX, Sparkles } from 'lucide-react'
import { useState } from 'react'
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

  const { data: feed } = useQuery({
    queryKey: ['feed', feedId],
    queryFn: () => getFeed(feedId!),
    enabled: !!feedId,
  })

  const { data: episodes, isLoading } = useQuery({
    queryKey: ['episodes', feedId],
    queryFn: () => listEpisodes(feedId!),
    enabled: !!feedId,
  })

  const ingestMutation = useMutation({
    mutationFn: (episodeId: string) => ingestEpisode(episodeId),
    onSuccess: async () => await queryClient.invalidateQueries({ queryKey: ['episodes', feedId] }),
  })

  const reingestMutation = useMutation({
    mutationFn: (episodeId: string) => reingestEpisode(episodeId),
    onSuccess: async () => await queryClient.invalidateQueries({ queryKey: ['episodes', feedId] }),
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

  if (isLoading && episodes) return <div>Loading episodes...</div>

  return (
    <ResizablePanelGroup orientation="horizontal" className="h-full">
      {/* Main content */}
      <ResizablePanel defaultSize="100%" minSize="50%">
        <div className="space-y-6 overflow-y-auto h-full p-6">

          {feed && (
            <div className="flex items-start justify-between">
              <div className="space-y-1">
                <h1 className="text-2xl font-bold">{feed.title ?? feed.rss_url}</h1>
                {feed.description && (
                  <p className="text-sm text-muted-foreground line-clamp-2">
                    {feed.description}
                  </p>
                )}
                <p className="text-sm text-muted-foreground">{feed.episode_count} episodes</p>
              </div>
              {!chatOpen && (
                <Button variant="outline" size="sm" onClick={toggleChat}>
                  <Sparkles className="h-4 w-4 mr-1" />
                  Ask AI
                </Button>
              )}
            </div>
          )}

          <Separator />

          <Input
            placeholder="Search episodes..."
            value={search}
            onChange={e => handleSearch(e.target.value)}
            className="grow"
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

          <div className="space-y-2">
            {paginated.length === 0 && (
              <p className="text-muted-foreground text-sm">No episodes match your search.</p>
            )}
            {paginated.map(episode => (
              <EpisodeRow
                key={episode.id}
                episode={episode}
                onIngest={(id) => ingestMutation.mutate(id)}
                onReingest={(id) => reingestMutation.mutate(id)}
                onNavigate={(id) => navigate(`/episodes/${id}`)}
              />
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