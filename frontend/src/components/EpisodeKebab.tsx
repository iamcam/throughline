// src/components/EpisodeKebab.tsx
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

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

import { LucideEllipsis, LucideRefreshCw, LucideTrash } from 'lucide-react';

import { useState } from 'react';


export interface MutationLike {
  mutate: (episodeId: string) => void;
  isPending: boolean;
}

interface EpisodeKebabProps {
  disabled: boolean;
  episodeId: string;
  episodeTitle?: string | null;
  reingestMutation: MutationLike;
  deleteTranscriptMutation: MutationLike;
}

interface DeleteConfirmationProps {
  isOpen: boolean;
  episodeTitle?: string | null;
  onDelete: () => void;
  onCancel: () => void;
}

function Confirmation({ isOpen, onDelete, onCancel, episodeTitle }: DeleteConfirmationProps) {
  return (
    <AlertDialog open={isOpen}>
      <AlertDialogContent size="sm">
        <AlertDialogHeader>
          <AlertDialogTitle>Delete Transcript?</AlertDialogTitle>
          <AlertDialogDescription>
            Are you sure you want to delete the transcript for {
              !episodeTitle ? 'this episode?' :
                (<span className='text-primary block p-1 text-md font-semibold italic'>{episodeTitle}?</span>)
            }
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel variant="outline" onClick={onCancel}>Cancel</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={onDelete}>Delete</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export default function EpisodeKebab({ disabled, episodeId, episodeTitle, reingestMutation, deleteTranscriptMutation }: EpisodeKebabProps) {
  const [isOpen, setIsOpen] = useState(false)

  const onDelete = () => {
    if (deleteTranscriptMutation.isPending) return;
    setIsOpen(false);
    deleteTranscriptMutation.mutate(episodeId)
  }

  const onCancel = () => {
    setIsOpen(false)
  }

  return (
    <div>
      <Confirmation episodeTitle={episodeTitle} isOpen={isOpen} onDelete={onDelete} onCancel={onCancel} />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button disabled={disabled} variant="outline" aria-label='Episode Actions'><LucideEllipsis /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className='w-auto'>
          <DropdownMenuItem
            disabled={reingestMutation.isPending}
            onClick={() => { reingestMutation.mutate(episodeId) }}
          >
            <LucideRefreshCw /> Reingest
          </DropdownMenuItem>

          <DropdownMenuSeparator />

          <DropdownMenuItem variant="destructive"
            disabled={deleteTranscriptMutation.isPending}
            onClick={() => { setIsOpen(true); }}
          >
            <LucideTrash />
            Delete transcript
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}