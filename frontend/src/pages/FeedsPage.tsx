// src/pages/FeedsPage.tsx
import { addFeed, deleteFeed, listFeeds, refreshFeed } from '@/api/client';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Trash } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function FeedsPage() {
    const [url, setUrl] = useState('')
    const queryClient = useQueryClient()
    const navigate = useNavigate()

    const { data: feeds, isLoading } = useQuery({
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
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['feeds'] }),
    })

    const handleAdd = () => {
        if (!url.trim()) return
        addMutation.mutate(url.trim())
    }

    if (isLoading) return <div>Loading feeds...</div>

    return (
        <div className="space-y-6">
            <div className="flex gap-2">
                <Input
                    value={url}
                    onChange={e => setUrl(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleAdd()}
                    placeholder="Paste RSS feed URL..."
                    className="grow"
                />
                <Button
                    onClick={handleAdd}
                    disabled={addMutation.isPending || !url.trim()}
                >
                    {addMutation.isPending ? 'Adding...' : 'Add Feed'}
                </Button>
            </div>

            {addMutation.isError && (
                <p>Failed to add feed. Check the URL and try again.</p>
            )}

            {feeds?.length === 0 && (
                <p>No feeds yet. Paste an RSS URL above to get started.</p>
            )}

            <div className="space-y-4">
                {feeds?.map(feed => (
                    <Card
                        key={feed.id}
                        onClick={() => navigate(`/feeds/${feed.id}/episodes`)}
                    >
                        <CardHeader>
                            <h1 className="text-2xl font-bold">{feed.title ?? feed.rss_url}</h1>
                        </CardHeader>
                        <CardContent>
                            <p>{feed.episode_count} episodes</p>
                            {feed.description && <p>{feed.description}</p>}
                        </CardContent>

                        <CardFooter className="flex gap-2">
                            <Button
                                className="grow"
                                disabled={refreshMutation.isPending}
                                onClick={(e) => { e.stopPropagation(); refreshMutation.mutate(feed.id) }}
                            >
                                Refresh
                            </Button>
                                <Button
                                variant="destructive"
                                size="icon"
                                disabled={deleteMutation.isPending}
                                onClick={(e) => { e.stopPropagation(); deleteMutation.mutate(feed.id) }}
                            >
                                <Trash />
                            </Button>
                        </CardFooter>
                    </Card>
                ))}
            </div>
        </div>
    )
}