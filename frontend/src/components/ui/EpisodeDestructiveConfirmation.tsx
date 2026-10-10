import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { ACTIVE_STATUSES } from "@/lib/episode";


interface EpisodeResetConfirmationProps {
  isOpen: boolean
  episodeTitle?: string | null
  status: string
  onReset: () => void
  onCancel: () => void
}

export default function EpisodeResetConfirmation({ isOpen, onReset: onDestructive, onCancel, episodeTitle, status }: EpisodeResetConfirmationProps) {
  const isCancel = ACTIVE_STATUSES.includes(status)
  const title = isCancel ? `Cancel Processing?` : `Reset Episode?`
  const body = isCancel
    ? "Are you sure you want to cancel transcription for"
    : "Are you sure you want to reset all data for"

  return (
    <AlertDialog open={isOpen}>
      <AlertDialogContent size="sm">
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>
            {body} {
              !episodeTitle ? 'this episode?' :
                (<span className='text-primary block p-1 text-md font-semibold italic'>{episodeTitle}?</span>)
            }
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel variant="outline" onClick={onCancel}>{isCancel ? "No" : "Cancel"}</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={onDestructive}>{isCancel ? "Cancel Job" : "Reset"}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}