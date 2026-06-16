// src/components/SpeakerRow.tsx
import type { Speaker } from '@/api/client'
import { updateSpeakers } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { LucideBadgeCheck, LucideBadgeQuestionMark, LucidePencil } from 'lucide-react'
import { useState } from 'react'

interface SpeakerRowProps {
  speaker: Speaker
  episodeId: string
}

function ConfidenceBadge({ confidence }: { confidence: string | null }) {
  const variants: Record<string, 'default' | 'secondary' | 'outline'> = {
    high: 'default',
    medium: 'secondary',
    low: 'outline',
  }
  if (!confidence) return null
  return <Badge variant={variants[confidence] ?? 'outline'}>{confidence}</Badge>
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
        <span className="font-medium">
          {speaker.display_name ?? speaker.speaker_id}
        </span>
        {!speaker.name_confirmed && <ConfidenceBadge confidence={speaker.confidence} />}
        {speaker.name_inferred && !speaker.name_confirmed ? (
          <Badge variant="outline"><LucideBadgeQuestionMark />Unconfirmed</Badge>
        ) : (
            <Badge variant="outline" className="bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300"><LucideBadgeCheck /></Badge>
        )}
      </div>

    </div>
  )
}