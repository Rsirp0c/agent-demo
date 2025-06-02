import os, json, requests, secrets
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from openai import AzureOpenAI
from schema import ChatRequest, ChatResponse, Message
from tools import available_tools, call_function



load_dotenv()
app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # React app URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Azure OpenAI
client = AzureOpenAI(
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)


@app.get("/")
async def root():
    return {"message": "Healthy and running!"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(chat_request: ChatRequest):
    try:
        print(f"\nUser asks: {chat_request.messages[-1].content}")
        messages = [{"role": msg.role, "content": msg.content} for msg in chat_request.messages]

        request_params = {
            "model": os.getenv("AZURE_OPENAI_MODEL_NAME"),
            "messages": messages,
            "tools": available_tools,  
        }

        # calling APIs
        response = client.chat.completions.create(**request_params)
        assistant_message = response.choices[0].message

        # Handle tool calls if present
        if assistant_message.tool_calls:
            print(f"\nLLM call tools: {assistant_message.tool_calls}")
            messages.append({"role": "assistant", "content": None, "tool_calls": assistant_message.tool_calls})
            
            for tool_call in assistant_message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                
                result = await call_function(name, args)
                
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result)
                    }
                )
            
            # Make a second API call
            second_response = client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_MODEL_NAME"),
                messages=messages,
            )
            assistant_message = second_response.choices[0].message
        
        print(f"\nLLM response: {assistant_message}")

        return ChatResponse(
            message=Message(
                role=assistant_message.role,
                content=assistant_message.content or ""
            )
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)