// src/components/CitationList.tsx
import type { CitationResult } from '@/api/client';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { ChevronDown } from 'lucide-react';
import { useState } from 'react';

function CitationCard({ citation, index }: { citation: CitationResult; index: number }) {
  const [audioOpen, setAudioOpen] = useState(false)
  const seekSrc = citation.audio_url
    ? `${citation.audio_url}#t=${Math.max(0, (citation.start_ms - 3000) / 1000)}`
    : ''

  return (
    <div className="rounded-md border px-3 py-2 text-sm space-y-1">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">
          {index + 1}. {citation.display_name ?? 'Unknown Speaker'}
        </span>
        <span>·</span>
        <span>{citation.timestamp_display}</span>
      </div>
      <div className='text-sm font-normal'>
        {citation.episode_title && (
            <span className="">{citation.episode_title}</span>
        )}
      </div>

      {/* <p className=''>
        <CopyButton copyValue={citation.chunk_id} displayText={citation.chunk_id.slice(0, 4) + "..." + citation.chunk_id.slice(-4)} />
        <Badge variant="outline" > {citation.similarity_score}</Badge>
      </p> */}


      <p className="text-muted-foreground">{citation.text}</p>

      {citation.audio_url && (
        <Collapsible open={audioOpen} onOpenChange={setAudioOpen}>
          <CollapsibleTrigger className="flex items-center gap-1 text-xs text-primary hover:underline">
            <ChevronDown className={`h-3 w-3 transition-transform ${audioOpen ? 'rotate-180' : ''}`} />
            {audioOpen ? 'Hide clip' : 'Show Clip'}
          </CollapsibleTrigger>
          <CollapsibleContent>
            <audio
              src={seekSrc}
              controls
              className="mt-2 w-92 max-w-full h-8"
            />
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}

interface CitationListProps {
  citations: CitationResult[]
}

export function CitationList({ citations }: CitationListProps) {
  const [open, setOpen] = useState(false)

  if (!citations.length) return null
  const topCitations = [...citations]
    .sort((a, b) => b.similarity_score - a.similarity_score)
    .slice(0, 7)
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex items-center gap-1 mt-2 text-xs text-muted-foreground hover:text-foreground transition-colors">
        <ChevronDown className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`} />
        {topCitations.length} {topCitations.length === 1 ? 'source' : 'sources'}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-2 space-y-2">
          {topCitations.map((c, i) => (
            <CitationCard key={`citation-${i}-${c.chunk_id}`} citation={c} index={i} />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}