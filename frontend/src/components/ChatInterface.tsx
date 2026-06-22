// src/components/ChatInterface.tsx
import type { CitationResult } from '@/api/client'
import { sendChatMessage } from '@/api/client'
import { CitationList } from '@/components/CitationList'
import { SearchFilterList } from '@/components/SearchFilterList'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useChatSession } from '@/hooks/useChatSession'
import { LucideCircleAlert, LucidePodcast } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'

// -- Types --------------------------------------------------------------------─

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: CitationResult[]
  isThinking?: boolean
}

// -- MessageBubble ------------------------------------------------------------─

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex mb-4 ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`shadow max-w-[80%] rounded-lg px-4 py-2.5 text-sm ${isUser ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground'
        }`}>
        {message.isThinking ? (
          <span className="text-muted-foreground animate-pulse">Thinking...</span>
        ) : (
          <>
            <ReactMarkdown
              components={{
                p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                ul: ({ children }) => <ul className="list-disc pl-4 mb-2">{children}</ul>,
                ol: ({ children }) => <ol className="list-decimal pl-4 mb-2">{children}</ol>,
                code: ({ children }) => (
                  <code className="bg-background/20 rounded px-1 py-0.5 text-xs font-mono">
                    {children}
                  </code>
                ),
              }}
            >
              {message.content}
            </ReactMarkdown>
            {message.citations && (
              <CitationList citations={message.citations} />
            )}
          </>
        )}
      </div>
    </div>
  )
}

// -- ChatInterface ------------------------------------------------------------─

interface ChatInterfaceProps {
  scopeFeedIds?: string[]
  scopeEpisodeIds?: string[]
}

export function ChatInterface({ scopeFeedIds, scopeEpisodeIds }: ChatInterfaceProps) {
  const [sheetOpen, setSheetOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const { sessionId, isCreating, error: sessionError, resetSession } = useChatSession(
    scopeFeedIds,
    scopeEpisodeIds,
  )

  const handleSend = async () => {
    const text = input.trim()
    if (!text || !sessionId || isSending) return

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
    }
    const thinkingMessage: Message = {
      id: 'thinking',
      role: 'assistant',
      content: '',
      isThinking: true,
    }

    setMessages(prev => [...prev, userMessage, thinkingMessage])
    setInput('')
    setIsSending(true)

    try {
      const response = await sendChatMessage(sessionId, text)
      setMessages(prev => [
        ...prev.filter(m => m.id !== 'thinking'),
        {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: response.message,
          citations: response.citations,
        },
      ])
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status
      setMessages(prev => [
        ...prev.filter(m => m.id !== 'thinking'),
        {
          id: `error-${Date.now()}`,
          role: 'assistant',
          content: status === 404
            ? 'Session expired. Starting a new one...'
            : 'Something went wrong. Please try again.',
        },
      ])
      if (status === 404) resetSession()
    } finally {
      setIsSending(false)
    }
  }

  // only show the knowledge base button when no scope is set
  // scoped contexts (feed/episode pages) don't need it
  const showKnowledgeBase = !scopeFeedIds && !scopeEpisodeIds

  return (
    <div className="flex flex-col h-full">
      {/* Session error — shown in all contexts */}
      {sessionError && (
        <p className="text-sm text-destructive px-4 py-2 shrink-0 flex items-center gap-2"><LucideCircleAlert className='' />{sessionError}</p>
      )}

      {/* Toolbar — only in unscoped context */}
      {showKnowledgeBase && (
        <div className="flex items-center gap-3 border-b px-4 py-2 shrink-0">
          <Button variant="outline" size="sm" onClick={() => setSheetOpen(true)}>
            <LucidePodcast /> Episodes
          </Button>
          <span className="text-sm text-muted-foreground">
            {isCreating && 'Starting session...'}
          </span>
        </div>
      )}


      {/* Messages */}
      <div className="overflow-y-auto flex-1 px-4 py-6">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center">
            <p className="text-sm text-muted-foreground">Ask anything about your podcasts.</p>
          </div>
        ) : (
          <>
            {messages.map(msg => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            <div ref={bottomRef} />
          </>
        )}
      </div>

      {/* Input */}
      <div className="sticky bottom-0 px-4 py-3">
        <div className="flex items-end justify-center-safe gap-2">
          <Textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            placeholder="Ask a question… (Enter to send, Shift+Enter for newline)"
            disabled={!sessionId || isSending}
            className="max-w-150 min-h-16 max-h-42 bg-background"
          />
          <Button
            onClick={handleSend}
            disabled={!input.trim() || !sessionId || isSending}
          >
            Send
          </Button>
        </div>
      </div>

      {showKnowledgeBase && (
        <SearchFilterList open={sheetOpen} onClose={() => setSheetOpen(false)} />
      )}

    </div>
  )
}