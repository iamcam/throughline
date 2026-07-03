// src/components/SearchFilterList.tsx
import type { Episode, Feed } from '@/api/client'
import { listEpisodes, listFeeds } from '@/api/client'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { formatDate, formatDuration } from '@/lib/date'
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'

// -- EpisodeRowShort ----------------------------------------------------------─

function EpisodeRowShort({ episode }: { episode: Episode }) {
  return (
    <div className="flex flex-col gap-0.5 py-2 border-b last:border-0">
      <span className="text-sm font-medium line-clamp-1">
        {episode.title ?? 'Untitled'}
      </span>
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span>{formatDate(episode.published_at)}</span>
        <span>{formatDuration(episode.duration_seconds)}</span>
      </div>
    </div>
  )
}

// -- FeedAccordionItem --------------------------------------------------------─

function FeedAccordionItem({ feed, onNavigate }: { feed: Feed; onNavigate: (path: string) => void }) {
  const { data: episodes } = useQuery({
    queryKey: ['episodes', feed.id],
    queryFn: () => listEpisodes(feed.id),
    // only fetch when we have a feed — but don't eagerly fetch all feeds on open
    enabled: !!feed.id,
    staleTime: 30_000,
  })

  const readyEpisodes = useMemo(
    () => (episodes ?? []).filter(ep => ep.pipeline_status === 'READY'),
    [episodes]
  )

  const hasReady = readyEpisodes.length > 0
  const totalCount = episodes?.length ?? feed.episode_count

  return (
    <AccordionItem value={feed.id}>
      <AccordionTrigger>
        <div className="flex flex-row gap-4">
          <div>{feed.image_url && <img src={feed.image_url} className="size-24" alt="Feed cover artwork"/>}</div>
          <div className="grow flex flex-col justify-center">
            <div className="font-bold">
              {feed.title ?? feed.rss_url}
            </div>
            <div className="text-xs text-muted-foreground">
              {episodes
                ? `${readyEpisodes.length} of ${totalCount}`
                : `${feed.episode_count}`} episodes
            </div>
          </div>
        </div>
      </AccordionTrigger>
      <AccordionContent >
        {!episodes && (
          <p className="text-xs text-muted-foreground py-2">Loading...</p>
        )}
        {episodes && !hasReady && (
          <div className="flex flex-col gap-2 py-1">
            <p className="text-xs text-muted-foreground">
              No ingested episodes yet.
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={() => onNavigate(`/feeds/${feed.id}/episodes`)}
            >
              Add episodes →
            </Button>
          </div>
        )}
        {hasReady && (
          <div className="flex flex-col justify-center">
            <div className="flex flex-col">
              {readyEpisodes.map(ep => (
                <EpisodeRowShort key={ep.id} episode={ep} />
              ))}
            </div>
            <Button
              variant="outline"
              size="sm"
              className="mt-2 "
              onClick={() => onNavigate(`/feeds/${feed.id}/episodes`)}
            >
              Manage episodes →
            </Button>
          </div>
        )}
      </AccordionContent>
    </AccordionItem>
  )
}

// -- SearchFilterList ----------------------------------------------------------

interface SearchFilterListProps {
  open: boolean
  onClose: () => void
}

export function SearchFilterList({ open, onClose }: SearchFilterListProps) {
  const navigate = useNavigate()

  const { data: feeds, isLoading } = useQuery({
    queryKey: ['feeds'],
    queryFn: listFeeds,
    staleTime: 30_000,
  })

  const handleNavigate = (path: string) => {
    onClose()
    navigate(path)
  }

  return (
    <Sheet open={open} onOpenChange={onClose} >
      <SheetContent side="left" className="flex flex-col">
        <SheetHeader>
          <SheetTitle>Chat Feeds</SheetTitle>

        </SheetHeader>
        <SheetDescription className='px-4'>
          Available transcribed episodes
        </SheetDescription>
        {/* Scrollable feed list */}
        <div className="flex-1 overflow-y-auto px-4">
          {isLoading && (
            <p className="text-sm text-muted-foreground">Loading feeds...</p>
          )}
          {feeds?.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No feeds yet. Add one to get started.
            </p>
          )}
          {feeds && feeds.length > 0 && (
            <Accordion type="multiple">
              {feeds.map(feed => (
                <FeedAccordionItem
                  key={feed.id}
                  feed={feed}
                  onNavigate={handleNavigate}
                />
              ))}
            </Accordion>
          )}
        </div>

        <SheetFooter>
          <Button
            variant="outline"
            className="w-full"
            onClick={() => handleNavigate('/feeds')}
          >
            Manage feeds →
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}