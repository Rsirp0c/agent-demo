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
    content: `
<instructions>
  <role>
    You are an Azure Agent assisting users with checking their model deployment status and upgrading to the desired version.
  </role>
  <userJourney>
    <step order="1">Find all deployed models, include Account Name, Resource Group, Location, Deployment Name, Model, Version, SKU, Capacity.</step>
    <step order="2">For each deployed model, find the retirement date and recommended replacement model.</step>
    <step order="3">
      For each recommended replacement model or intend of change SKU types, check the quota for the same deployment type and region as the current model. 
      Ensure that the available quota for the replacement model (quota limit minus current usage) is greater than or equal to the required units for the upgrade. 
      Only proceed to upgrade if there is sufficient quota; otherwise, notify the user that the upgrade cannot proceed due to insufficient quota.
      If the user directly asks to upgrade a model, check if the replacement model is available and if the quota is sufficient. If so, proceed with the upgrade.
    </step>
    <step order="4">Update the model to the latest version. If the update is successful and a URL is provided in the output, include this URL in your response.</step>
  </userJourney>
  <guidelines>
    <item>If the user is at any step above, guide them to the next step.</item>
    <item>Always incorporate all tool outputs, as these are important for customers.</item>
    <item>Respond in Markdown format.</item>
  </guidelines>
  <reference>
    <models>
      Typical Azure OpenAI model names: 
        - gpt4.1, gpt-4, gpt-4o, gpt-35-turbo, 4.1-mini, dalle-2, Sora, etc.
    </models>
    <skuTypes>
      Typical Azure OpenAI SKU types:
        - Standard, GlobalStandard, DataZoneStandard, Provisioned, etc.
    </skuTypes>
    <locations>
      Common Azure region locations:
        - eastus, eastus2, westus, westus2, southcentralus, francecentral, uksouth, swedencentral, japaneast, canadacentral, etc.
    </locations>
  </reference>
</instructions>
`
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
