// src/components/EpisodeKebab.tsx
import { useEpisodeActions } from '@/hooks/useQueueActions';
import { ACTIVE_STATUSES, canReset, REINGESTABLE_STATUSES } from '@/lib/episode';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";


import { LucideEllipsis, LucideIterationCcw, LucideRefreshCw } from 'lucide-react';

import EpisodeResetConfirmation from '@/components/ui/EpisodeDestructiveConfirmation';
import { useState } from 'react';


export interface MutationLike {
  mutate: (episodeId: string) => void;
  isPending: boolean;
}

interface EpisodeKebabProps {
  episodeId: string
  feedId: string
  episodeTitle: string | null
  status: string
  disabled?: boolean
}


export default function EpisodeKebab({ disabled, episodeId, episodeTitle, feedId, status }: EpisodeKebabProps) {
  const [isOpen, setIsOpen] = useState(false)
  const { retryMutation: reingestMutation, resetMutation } = useEpisodeActions({ episodeId, feedId })

  const busy = reingestMutation.isPending || resetMutation.isPending
  // const error = reingestMutation.error ?? resetMutation.error
  const canReingest = REINGESTABLE_STATUSES.includes(status)
  const showReset = canReset(status)

  const isCancel = ACTIVE_STATUSES.includes(status)

  const onReset = () => {
    if (resetMutation.isPending) return
    setIsOpen(false)
    resetMutation.mutate()
  }

  const onCancel = () => {
    setIsOpen(false)
  }

  return (
    <div>
      <EpisodeResetConfirmation episodeTitle={episodeTitle} isOpen={isOpen} onReset={onReset} onCancel={onCancel} status={status} />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button disabled={disabled} variant="outline" aria-label='Episode Actions'><LucideEllipsis /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className='w-auto'>
          {canReingest && (
            <DropdownMenuItem
              disabled={busy}
              onClick={() => reingestMutation.mutate()}
            >
              <LucideRefreshCw /> Re-transcribe
            </DropdownMenuItem>
          )}
          {canReingest && showReset && <DropdownMenuSeparator />}
          {showReset && (
            <DropdownMenuItem variant="destructive"
              disabled={busy}
              onClick={() => setIsOpen(true)}
            >
              <LucideIterationCcw />
              {isCancel ? "Cancel Job" : "Reset Episode"}
            </DropdownMenuItem>
          )}

        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}