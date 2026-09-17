// src/components/TranscriptViewer.tsx
import { getTranscript, type TranscriptSegment } from '@/api/client'
import { Button } from '@/components/ui/button'
import { formatTimestamp } from '@/lib/date'
import { useQuery } from '@tanstack/react-query'
import { LucideChevronDown, LucideChevronRight, LucideChevronUp } from 'lucide-react'
import { useState } from 'react'

const COLLAPSED_SEGMENTS = 6

interface TranscriptViewerProps {
  episodeId: string
  collapsedSegments?: number,
  className?: string
}

const group_transcript = (segments: TranscriptSegment[]) => {

  const grouped: TranscriptSegment[] = []
  segments.forEach((segment: TranscriptSegment, idx: number) => {
    const new_seg = { ...segment }
    if (segments[idx - 1]?.speaker_id !== segment.speaker_id) {
      grouped.push(new_seg)
    } else if (segments[idx - 1]?.speaker_id === segment.speaker_id) {
      grouped[grouped.length - 1].text += `\n${new_seg.text}`
    }
  })
  return grouped
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

  const grouped = group_transcript(transcript.segments)
  const visible = expanded
    ? grouped
    : grouped.slice(0, collapsedSegments)

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
        <div key={`${seg.sequence_order}`} className="text-sm sm:grid sm:grid-cols-6 sm:gap-4 mb-8">
          {(visible[idx - 1]?.speaker_id === seg.speaker_id) ? <></> :
            (
              <div className='sm:text-end font-mono sm:col-span-1 wrap-anywhere'>
                <div className='text-primary font-semibold '>{(seg.display_name ?? seg.speaker_id)}</div>
                <div className='text-xs text-muted-foreground'>{formatTimestamp(seg.start_ms/1000)}</div>
              </div>
            )
          }
          <div className="sm:block sm:col-start-2 sm:col-span-full whitespace-pre-line">{seg.text}</div>
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