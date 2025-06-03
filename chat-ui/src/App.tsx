import { useState } from 'react'
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
    content: 'You are a Azure Agent helping users to check their model deployment status and update to desired version. When using tools, please try to incorporate all the tools output as those are important information for customers. Please respond in Markdown format.'
  }
  const [messages, setMessages] = useState<Message[]>([systemMessage])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

      const data = await response.json()
      
      // Add AI response
      const aiMessage: Message = {
        role: 'assistant',
        content: data.message.content,
      }
      setMessages((prev) => [...prev, aiMessage])
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
