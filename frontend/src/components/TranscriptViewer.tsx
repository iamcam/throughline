// src/components/TranscriptViewer.tsx
import { getTranscript } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useQuery } from '@tanstack/react-query'
import { LucideChevronDown, LucideChevronRight, LucideChevronUp } from 'lucide-react'
import { useState } from 'react'

const COLLAPSED_SEGMENTS = 6

interface TranscriptViewerProps {
  episodeId: string
  collapsedSegments?: number,
  className?: string
}

export function TranscriptViewer({ episodeId, collapsedSegments = COLLAPSED_SEGMENTS, className }: TranscriptViewerProps) {
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
    <div className={className + " space-y-3"}>
      {canCollapse && expanded && (
        <Button
          variant="link"
          size="sm"
          className="px-0 h-auto text-muted-foreground"
          onClick={() => setExpanded(e => !e)}
        >
          <LucideChevronDown /> Show less
        </Button>
      )}
      {visible.map((seg, idx) => (
        <div key={`${seg.sequence_order}`} className="text-sm grid grid-cols-4 sm:grid-cols-6 sm:gap-2">
          {(visible[idx - 1]?.speaker_id === seg.speaker_id) ? <></> :
            (
                <div className='sm:text-end font-mono col-span-full sm:col-span-1 text-primary font-semibold wrap-anywhere'>{(seg.display_name ?? seg.speaker_id)}:</div>
            )
          }
          <div className="block col-start-1 sm:col-start-2 col-span-full">{seg.text}</div>
        </div>
      ))}
      {canCollapse && (
        <>

          <Button
          variant="link"
          size="sm"
          className="px-0 h-auto text-muted-foreground"
          onClick={() => setExpanded(e => !e)}
          >
            {expanded ? <LucideChevronUp /> : <LucideChevronRight />}

            {expanded
              ? 'Show less'
              : 'Show all'}
          </Button>
        </>
      )}
    </div>
  )
}