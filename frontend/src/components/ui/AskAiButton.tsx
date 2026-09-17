import { Button } from "@/components/ui/button";
import { LucideSparkles } from "lucide-react";
import type { MouseEventHandler } from "react";

interface AskAiButtonProps {
  disabled?: boolean
  onClick: MouseEventHandler
  label?: string
  className?: string
}


function AskAiButton({ disabled = false, onClick, label="Ask AI", className="" }: AskAiButtonProps) {

  return (
    <div className={className}>
      <Button variant="outline" size="sm" disabled={disabled} aria-label="open ai chat" onClick={onClick} className="">
      <LucideSparkles className="h-4 w-4 mr-1" />
        {label}
      </Button>
    </div>
  )
}

export default AskAiButton;