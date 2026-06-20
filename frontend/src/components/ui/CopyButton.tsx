// src/components/ui/CopyButton.tsx
import { LucideCopy } from "lucide-react"
import { Button } from "./button"
interface CopyButtonProps {
  displayText?: string
  copyValue: string
}


export default function CopyButton({ displayText, copyValue }: CopyButtonProps) {
  return (<Button variant="outline" onClick={() => navigator.clipboard.writeText(copyValue)}>
    <LucideCopy />{displayText}
  </Button>)
}
