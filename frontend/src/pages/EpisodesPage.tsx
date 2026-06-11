// src/pages/EpisodesPage.tsx
import { getFeed, ingestEpisode, listEpisodes, reingestEpisode } from '@/api/client'
import { EpisodeRow } from '@/components/EpisodeRow'
import { Button } from '@/components/ui/button'
import { ButtonGroup } from '@/components/ui/button-group'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

const PAGE_SIZE = 20

export default function EpisodesPage() {
  const { feedId } = useParams<{ feedId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'ingested'>('all')
  const [page, setPage] = useState(1)

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
    onSuccess: async () => await queryClient.invalidateQueries({ queryKey: ['episodes', feedId] })
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

  const ingestedCount = (episodes ?? []).filter((ep) => ep.pipeline_status === 'READY').length

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

  if (isLoading && episodes) return <div>Loading episodes...</div>

  return (

    <div className="space-y-6">
      {feed && (
        <div className="space-y-1">
          <h1 className="text-2xl font-bold">{feed.title ?? feed.rss_url}</h1>
          {feed.description && (
            <p className="text-sm text-muted-foreground line-clamp-2">
              {feed.description}
            </p>
          )}
          <p className="text-sm text-muted-foreground">{feed.episode_count} episodes</p>
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
  )
}