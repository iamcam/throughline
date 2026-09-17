import { LucideAudioLines } from 'lucide-react'
import { useState, type ReactNode } from 'react'

type Stage = 'direct' | 'proxy' | 'placeholder'

interface CoverArtProps {
  src?: string | null
  proxySrc?: string
  fallback?: ReactNode
  alt: string
  className?: string
}

function initialStage(src?: string | null, proxySrc?: string): Stage {
  if (src) return 'direct'
  if (proxySrc) return 'proxy'
  return 'placeholder'
}

function CoverArt({ src, proxySrc, fallback, alt, className }: CoverArtProps) {
  const [stage, setStage] = useState<Stage>(() => initialStage(src, proxySrc))
  const [prevSrc, setPrevSrc] = useState(src)
  const [prevProxySrc, setPrevProxySrc] = useState(proxySrc)

  if (src !== prevSrc || proxySrc !== prevProxySrc) {
    setPrevSrc(src)
    setPrevProxySrc(proxySrc)
    setStage(initialStage(src, proxySrc))
  }

  const handleError = () => {
    if (stage === 'direct' && proxySrc) {
      setStage('proxy')
    } else {
      setStage('placeholder')
    }
  }

  if (stage === 'placeholder') {
    return (
      <div className={`flex items-center justify-center bg-muted ${className ?? ''}`}>
        {fallback || <LucideAudioLines size={72} />}
      </div>
    )
  }

  return (
    <img
      src={stage === 'direct' ? src! : proxySrc!}
      alt={alt}
      className={className}
      referrerPolicy="no-referrer"
      onError={handleError}
    />
  )
}

export default CoverArt