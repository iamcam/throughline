import { Badge } from '@/components/ui/badge'

export default function StatusBadge({ status }: { status: string }) {
  const variants: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
    READY: 'default',
    ERROR: 'destructive',
    PENDING: 'outline',
  }
  const messages: { [key: string]: string } = {
      'QUEUED': 'Queued',
      'DOWNLOADING': 'Downloading',
      'TRANSCRIBING': 'Transcribing',
      'INFERRING_SPEAKERS': 'Inferring Speakers',
      'CHUNKING': 'Processing',
      'EMBEDDING': 'Saving',

  }
  const variant = variants[status] ?? 'secondary'
  return <Badge variant={variant}>{messages[status] || status}</Badge>
}