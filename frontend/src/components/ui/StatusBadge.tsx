import { Badge } from '@/components/ui/badge'
import { ACTIVE_STATUSES } from '@/lib/episode'
import { LucideLoaderCircle } from 'lucide-react'

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
      'DIARIZING': 'Transcribing',
      'INFERRING_SPEAKERS': 'Inferring Speakers',
      'CHUNKING': 'Processing',
      'EMBEDDING': 'Saving',
      'ERROR': 'Error'

  }
  const variant = variants[status] ?? 'secondary'
  return (
    <Badge variant={variant}>
      {messages[status] || status}
      {ACTIVE_STATUSES.includes(status) && <LucideLoaderCircle className="animate-spin" />}
    </Badge>
  )
}