// src/components/ExpandableDescription.tsx
import { Button } from '@/components/ui/button'
import { stripMarkdown } from '@/lib/text'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'

interface ExpandableDescriptionProps {
  description: string | null | undefined
  collapsedLines?: number
}

export function ExpandableDescription({
  description,
  collapsedLines = 3,
}: ExpandableDescriptionProps) {
  const [expanded, setExpanded] = useState(false)

  if (!description) return null

  // Because Tailwind needs the class in source to make it work - not used, stripped from the built css
  const CLAMP_CLASSES: Record<number, string> = {
    1: 'line-clamp-1',
    2: 'line-clamp-2',
    3: 'line-clamp-3',
    4: 'line-clamp-4',
    5: 'line-clamp-5',
    6: 'line-clamp-6',
    7: 'line-clamp-7',
    8: 'line-clamp-8',
    9: 'line-clamp-9',
    10: 'line-clamp-10',
    11: 'line-clamp-11',
    12: 'line-clamp-12',
  }
  return (
    <div>
      {expanded ? (
        <ReactMarkdown>{description}</ReactMarkdown>
      ) : (
        <p className={CLAMP_CLASSES[collapsedLines] ?? 'line-clamp-3'}>
          {stripMarkdown(description)}
        </p>
      )}
      <Button
        variant="link"
        size="sm"
        className="px-0 h-auto text-muted-foreground"
        onClick={() => setExpanded(e => !e)}
      >
        {expanded ? 'Show less' : 'More...'}
      </Button>
    </div>
  )
}