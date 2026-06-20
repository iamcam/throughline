// src/components/SpeakerRow.tsx
import type { Speaker } from '@/api/client'
import { updateSpeakers } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { LucideBadgeCheck, LucideBadgeQuestionMark, LucidePencil, LucideStar } from 'lucide-react'
import { useState, type ReactElement } from 'react'

interface SpeakerRowProps {
  speaker: Speaker
  episodeId: string
}


function ConfidenceRating({ confidence }: { confidence: string | null }) {
  const rating: Record<string, 1 | 2 | 3> = {
    high: 3,
    medium: 2,
    low: 1
  }
  if (!confidence) return null
  const stars = rating[confidence]
  const output: ReactElement[] = []
  for (let ii = 0; ii < stars; ii++){
    output.push(<LucideStar size={14} />)
  }
  return <div className="flex">{output}</div>
}

export function SpeakerRow({ speaker, episodeId }: SpeakerRowProps) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(speaker.display_name ?? '')
  const queryClient = useQueryClient()

  const updateMutation = useMutation({
    mutationFn: () => updateSpeakers(episodeId, [{
      speaker_id: speaker.speaker_id,
      display_name: name.trim() || null,
    }]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['speakers', episodeId] })
      setOpen(false)
    },
  })

  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <div className="flex items-center gap-4">
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button variant="outline" size="xs"><LucidePencil /></Button>
          </PopoverTrigger>
          <PopoverContent className="w-72 space-y-4">
            <div className="space-y-2">
              <Label htmlFor={`speaker-name-${speaker.speaker_id}`}>
                Speaker name
              </Label>
              <Input
                id={`speaker-name-${speaker.speaker_id}`}
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="Enter speaker name..."
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setName(speaker.display_name ?? '')
                  setOpen(false)
                }}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                disabled={updateMutation.isPending}
                onClick={() => updateMutation.mutate()}
              >
                {updateMutation.isPending ? 'Saving...' : 'Save'}
              </Button>
            </div>
            {updateMutation.isError && (
              <p className="text-destructive text-sm">Failed to save. Try again.</p>
            )}
          </PopoverContent>
        </Popover>
        <span className="font-medium min-w-24">
          {speaker.display_name ?? <div className='text-sm italic text-muted-foreground' onClick={(e) => { e.stopPropagation(); setOpen(true)}}>Add name</div>}
        </span>
        {speaker.name_inferred && !speaker.name_confirmed ? (
          <Badge variant="outline"><LucideBadgeQuestionMark />Unconfirmed</Badge>
        ) : (
             speaker.display_name && (<Badge variant="outline" className="bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300"><LucideBadgeCheck /></Badge>)
        )}
        {!speaker.name_confirmed && (<div className='text-sm'><ConfidenceRating confidence={speaker.confidence} /></div>)}
      </div>

    </div>
  )
}