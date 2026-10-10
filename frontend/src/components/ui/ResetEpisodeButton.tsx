import { useEpisodeActions } from "@/hooks/useQueueActions";
import { useState } from "react";
import { Button } from "./button";
import EpisodeResetConfirmation from "./EpisodeDestructiveConfirmation";

interface ResetEpisodeButtonProps {
  episodeId: string
  title: string | null
  feedId: string
  status: string
  resetLabel: string
  disabled: boolean
}

// For Resetting an episode or cancelling from the job queue
export function ResetEpisodeButton({ episodeId, title, status, feedId, disabled, resetLabel }: ResetEpisodeButtonProps) {

  const [isOpen, setIsOpen] = useState(false)

  const onCancel = () => {
    setIsOpen(false)
  }
  const onReset = () => {
    if (resetMutation.isPending) return
    setIsOpen(false)
    resetMutation.mutate()
  }

  const { resetMutation } = useEpisodeActions({ episodeId, feedId })
  return (
    <div>
      <EpisodeResetConfirmation episodeTitle={title} isOpen={isOpen} onReset={onReset} onCancel={onCancel} status={status}  />
      <Button size="xs" variant="secondary" className="rounded-full" onClick={() => setIsOpen(true)} disabled={disabled}>{resetLabel}</Button>
      </div>
  )
}