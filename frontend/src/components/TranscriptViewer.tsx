// src/components/TranscriptViewer.tsx
import { getTranscript } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useQuery } from '@tanstack/react-query'
import { LucideChevronDown, LucideChevronUp } from 'lucide-react'
import { useState } from 'react'

const COLLAPSED_SEGMENTS = 6

interface TranscriptViewerProps {
  episodeId: string
  collapsedSegments?: number
}

export function TranscriptViewer({ episodeId, collapsedSegments = COLLAPSED_SEGMENTS }: TranscriptViewerProps) {
  const [expanded, setExpanded] = useState(false)

  const { data: transcript, isLoading, isError } = useQuery({
    queryKey: ['transcript', episodeId],
    queryFn: () => getTranscript(episodeId),
  })

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading transcript...</p>
  if (isError) return <p className="text-sm text-destructive">Failed to load transcript.</p>
  if (!transcript?.segments.length) return <p className="text-sm text-muted-foreground">No transcript available.</p>

  const visible = expanded
    ? transcript.segments
    : transcript.segments.slice(0, collapsedSegments)

  const canCollapse = transcript.segments.length > collapsedSegments

  return (
    <div className="space-y-3">
      {canCollapse && expanded && (
        <Button
          variant="link"
          size="sm"
          className="px-0 h-auto text-muted-foreground"
          onClick={() => setExpanded(e => !e)}
        >
          <LucideChevronUp /> Show less
        </Button>
      )}
      {visible.map((seg) => (
        <div key={seg.sequence_order} className="text-sm">
          {/* <span className="text-muted-foreground font-medium">
            {seg.display_name ?? seg.speaker_id}
          </span> */}
          <p className="mt-0.5">{seg.text}</p>
        </div>
      ))}
      {canCollapse && (
        <>
          {expanded ? null : <div>...</div>}
          <Button
          variant="link"
          size="sm"
          className="px-0 h-auto text-muted-foreground"
          onClick={() => setExpanded(e => !e)}
          >
            {expanded ? <LucideChevronUp /> : <LucideChevronDown />}

            {expanded
              ? 'Show less'
              : 'Show all'}
          </Button>
        </>
      )}
    </div>
  )
}