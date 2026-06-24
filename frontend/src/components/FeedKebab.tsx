// src/components/FeedKebab.tsx
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


import { LucideCloudBackup, LucideEllipsis, LucideTrash } from 'lucide-react';

import { useState } from 'react';


interface MutationLike {
  mutate: (feedId: string) => void;
  isPending: boolean;
}

interface KebabPopoverProps {
  feedId: string;
  feedTitle?: string | null;
  deleteMutation: MutationLike;
  refreshMutation: MutationLike;
}

interface KebabDeleteProps {
  isOpen: boolean;
  feedTitle?: string | null;
  onDelete: () => void;
  onCancel: () => void;
}

function Confirmation({ isOpen, onDelete, onCancel, feedTitle }: KebabDeleteProps) {
  return (
    <AlertDialog open={isOpen}>
      <AlertDialogContent size="sm">
        <AlertDialogHeader>
          <AlertDialogTitle>Delete Feed?</AlertDialogTitle>
          <AlertDialogDescription>
            Are you sure you want to delete {!feedTitle && 'this feed?'}
            {feedTitle && (<span className='text-primary block p-1 text-md font-semibold italic'>{feedTitle}?</span>)}
            It will remove all episodes and transcription content.
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

export default function FeedKebab({ feedId, feedTitle, deleteMutation, refreshMutation }: KebabPopoverProps) {
  const [isOpen, setIsOpen] = useState(false)

  const onDelete = () => {
    if (deleteMutation.isPending) return;
    setIsOpen(false);
    deleteMutation.mutate(feedId)
  }

  const onCancel = () => {
    setIsOpen(false)
  }

  return (
    <div>
      <Confirmation feedTitle={feedTitle} isOpen={isOpen} onDelete={onDelete} onCancel={onCancel}/>
      <DropdownMenu>
        <DropdownMenuTrigger asChild disabled={deleteMutation.isPending || refreshMutation.isPending}>
          <Button variant="outline" aria-label='Feed Actions'><LucideEllipsis /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className='w-auto'>
          <DropdownMenuItem
            disabled={refreshMutation.isPending}
            onClick={() => {  refreshMutation.mutate(feedId) }}
          >
            <LucideCloudBackup /> Refresh Feed
          </DropdownMenuItem>

          <DropdownMenuSeparator />

          <DropdownMenuItem variant="destructive"
            disabled={deleteMutation.isPending}
            onClick={() => {  setIsOpen(true); }}
          >
            <LucideTrash />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
