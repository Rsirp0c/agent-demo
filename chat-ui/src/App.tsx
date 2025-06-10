import { useEffect, useRef, useState } from 'react'
import './App.css'
import MarkdownIt from 'markdown-it'


interface Message {
  role: 'user' | 'assistant' | 'system'
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
  const [sseConnected, setSseConnected] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  // Suggestion prompts
  const suggestions = [
    "Show all deployed models",
    "What is the retiring date for my models and the recommended replacement?",
    "Update my model to the recommended version"
  ]

  useEffect(() => {
    const es = new EventSource('http://localhost:8000/api/chat/stream')
    eventSourceRef.current = es

    es.onopen = () => setSseConnected(true)

    es.onmessage = (ev) => {
      try {
        const data: Message = JSON.parse(ev.data)
        setMessages((prev) => [...prev, data])
      } catch (err) {
        console.error('Failed to parse SSE message', err)
      }
    }

    es.onerror = (err) => {
      console.error('SSE connection error', err)
      setSseConnected(false)
      es.close()
    }

    return () => {
      es.close()
    }
  }, [])

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
      // Call the backend API
      const response = await fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          messages: [...messages, userMessage],
        }),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Failed to get response from AI')
      }

      if (!sseConnected) {
        const data = await response.json()
        const aiMessage: Message = {
          role: 'assistant',
          content: data.message.content,
        }
        setMessages((prev) => [...prev, aiMessage])
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
          .filter((message) => message.role !== 'system')
          .map((message, index) => (
            <div
              key={index}
              className={`message ${message.role === 'user' ? 'user-message' : 'ai-message'}`}
              dangerouslySetInnerHTML={{ __html: mdParser.render(message.content) }}
            />
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
