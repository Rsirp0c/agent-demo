import { useState } from 'react'
import './App.css'
import MarkdownIt from 'markdown-it'


interface Message {
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
}

interface ToolMessage {
  id: number
  content: string
}

const mdParser = new MarkdownIt()

function App() {
  // Add a default system message
  const systemMessage: Message = {
    role: 'system',
    content: [
      'You are a Azure Agent helping users to check their model deployment status and update to desired version.',
      "User journey is to find all deployed models as first step, then find out the retiring date and recommneded replacemrent model, at last, update the model to the latest version.",
      "If user is at any of the above steps, please guide user to the next step.",
      'When using tools, please try to incorporate all the tools output as those are important information for customers.',
      'Please respond in Markdown format.'
    ].join(' ')
  }
  const [messages, setMessages] = useState<Message[]>([systemMessage])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toolMessages, setToolMessages] = useState<ToolMessage[]>([])

  // Suggestion prompts
  const suggestions = [
    "Show all deployed models",
    "What is the retiring date for my models and the recommended replacement?",
    "Update my model to the recommended version"
  ]

  const handleSend = async () => {
    if (!input.trim()) return

    // Add user message
    const userMessage: Message = {
      role: 'user',
      content: input,
    }
    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch('http://localhost:8000/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({
          messages: [...messages, userMessage],
        }),
      })

      if (!response.ok || !response.body) {
        const errorData = await response.text().catch(() => '')
        throw new Error(errorData || 'Failed to get response from AI')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
         buffer = buffer.replace(/\r/g, '')
        let index
        while ((index = buffer.indexOf('\n\n')) !== -1) {
          const raw = buffer.slice(0, index)
          buffer = buffer.slice(index + 2)
          if (!raw.trim()) continue

          const lines = raw.split('\n')
          let event = ''
          let data = ''
          for (const line of lines) {
            if (line.startsWith('event:')) {
              event = line.slice(6).trim()
            } else if (line.startsWith('data:')) {
              data += line.slice(5).trim()
            }
          }

          if (event === 'tool_call') {
            const content = data
            const id = Date.now() + Math.random()
            setToolMessages((prev) => [...prev, { id, content }])
            
          } else if (event === 'tool_update') {
            const id = Date.now() + Math.random()
            const content = data
            setToolMessages((prev) => [...prev, { id, content }])

          } else if (event === 'final') {
            console.log('FINAL EVENT', data)
            // clear tool messages when final event is received
            setToolMessages([])
            const parsed = JSON.parse(data)
            setMessages((prev) => [
              ...prev,
              {
                role: parsed.role,
                content: parsed.content,
              } as Message,
            ])

          } else if (event === 'error') {
            setError(data)
          }
        }
      }
    } catch (error) {
      console.error('Failed to get response from AI', error)
      setError(error instanceof Error ? error.message : 'An unexpected error occurred')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="chat-container">
      <div className="messages-container">
        {messages
          .filter((message) => message.role !== 'system' && message.role !== 'tool')
          .map((message, index) => (
            <div
              key={index}
              className={`message ${message.role === 'user' ? 'user-message' : 'ai-message'}`}
              dangerouslySetInnerHTML={{ __html: mdParser.render(message.content) }}
            />
        ))}

        {toolMessages.map((m) => (
          <div key={m.id} className="tool-update">
            {m.content}
          </div>
        ))}

        {isLoading && (
          <div className="message ai-message loading-message">
            <div className="spinner">
              <span className="sr-only">Loading...</span>
            </div>
          </div>
        )}

        {error && (
          <div className="message error-message">
            Error: {error}
          </div>
        )}
      </div>
      {/* Suggestion prompts moved here */}
      <div className="suggestions-container">
        {suggestions.map((s, idx) => (
          <button
            key={idx}
            className="suggestion-button"
            onClick={() => setInput(s)}
            disabled={isLoading}
            type="button"
          >
            {s}
          </button>
        ))}
      </div>
      <div className="input-container">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your message..."
          onKeyPress={(e) => e.key === 'Enter' && handleSend()}
          className="message-input"
          disabled={isLoading}
        />
        <button
          onClick={handleSend}
          disabled={isLoading}
          className="send-button"
        >
          {isLoading ? 'Sending...' : 'Send'}
        </button>
      </div>
    </div>
  )
}

export default App
