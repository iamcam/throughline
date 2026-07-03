// src/pages/FeedsPage.tsx
import { addFeed, deleteFeed, listFeeds, refreshFeed } from '@/api/client';
import FeedKebab from '@/components/FeedKebab';
import { Button } from '@/components/ui/button';
import { Card, CardTitle } from '@/components/ui/card';

import { Input } from '@/components/ui/input';
import { formatRelativeDate } from '@/lib/date';
import { invalidateFeedAndEpisodes } from '@/lib/queryInvalidation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { LucideActivity, LucideAlertCircle, LucideArrowUpRight } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';


export default function FeedsPage() {
    const [url, setUrl] = useState('')
    const queryClient = useQueryClient()
    const navigate = useNavigate()

    const { data: feeds, isLoading, isError } = useQuery({
        queryKey: ['feeds'],
        queryFn: listFeeds,
    })

    const addMutation = useMutation({
        mutationFn: addFeed,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['feeds'] })
            setUrl('')
        },
    })

    const deleteMutation = useMutation({
        mutationFn: deleteFeed,
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['feeds'] }),
    })

    const refreshMutation = useMutation({
        mutationFn: refreshFeed,
        onSuccess: (_, feedId) => invalidateFeedAndEpisodes(queryClient, feedId),
    })

    const handleAdd = () => {
        if (!url.trim()) return
        addMutation.mutate(url.trim())
    }

    if (isLoading) return <div>Loading feeds...</div>
    if (isError) return <div className="p-6 text-sm text-destructive">Failed to load feeds. Is the backend running?</div>

    return (
        <div className="space-y-6 p-6 bg-page-background">

            <div className="flex items-center gap-2">
                <Input
                    value={url}
                    onChange={e => setUrl(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleAdd()}
                    placeholder="Apple Podcast or RSS feed URL..."
                    name='Add feed'
                    className="bg-card max-w-72"
                />
                <Button
                    onClick={handleAdd}
                    disabled={addMutation.isPending || !url.trim()}
                    aria-label="Add podcast feed"
                    className=''
                >
                    {addMutation.isPending ? 'Adding...' : 'Add Feed'}
                </Button>
            </div>

            {addMutation.isError && (
                <p className="text-sm text-destructive"><LucideAlertCircle className="inline-block mr-2" /> Failed to add feed. Check the URL and try again.</p>
            )}
            {deleteMutation.isError && (
                <p className="text-sm text-destructive"><LucideAlertCircle className="inline-block mr-2" /> Failed to delete feed. Please try again.</p>
            )}

            {refreshMutation.isError && (
                <p className="text-sm text-destructive"><LucideAlertCircle className="inline-block mr-2" />Failed to refresh feed. Please try again.</p>
            )}
            {feeds?.length === 0 && (
                <p>No feeds yet. Paste an Apple Podcast or RSS URL above to get started.</p>
            )}

            <div className="space-y-4">
                {feeds?.map(feed => (
                    <Card className='shadow-md' key={`feed-card-${feed.id}`}>

                        <div className="flex gap-6 items-stretch px-(--card-spacing) ">
                            {feed.image_url && (
                                <Link to={`/feeds/${feed.id}/episodes`} className="shrink-0" aria-label={`go to feed: ${feed.title}`}>

                                <img className="shadow aspect-square h-42"
                                    onClick={() => navigate(`/feeds/${feed.id}/episodes`)}
                                        src={feed.image_url}
                                        alt="Feed cover artwork"
                                />
                                </Link>
                            )}

                            <div className='space-y-2'>
                                <CardTitle>
                                    <h1 className="text-2xl font-bold ">
                                        <Link to={`/feeds/${feed.id}/episodes`}
                                            className='hover:text-hover'
                                        >
                                            {feed.title ?? feed.rss_url}
                                        </Link>
                                    </h1>
                                </CardTitle>
                                <div className='flex gap-2 items-center text-muted-foreground'>
                                    <p>{feed.episode_count.toLocaleString()} episodes</p>
                                    {feed.episode_count > 0 && (<p><LucideActivity size={12} /></p>)}
                                    <p>{feed.latest_episode_published_at && formatRelativeDate(feed.latest_episode_published_at)}</p>
                                </div>
                                {feed.description && <p>{feed.description}</p>}
                            </div>

                            <div className='flex flex-col justify-between'>
                                <Button size="icon" variant="outline" aria-label={`go to feed: ${feed.title}`} onClick={() => navigate(`/feeds/${feed.id}/episodes`)}>
                                    <LucideArrowUpRight  />
                                </Button>
                                <FeedKebab feedTitle={feed.title}  feedId={feed.id} refreshMutation={refreshMutation} deleteMutation={deleteMutation} />
                            </div>
                        </div>

                    </Card>
                ))}
            </div>
        </div>
    )
}