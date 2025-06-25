import os, json, secrets
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from openai import AzureOpenAI
from schema import ChatRequest, ChatResponse, Message
from tools import available_tools, call_function 

load_dotenv()
app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

        # Initial assistant call
        response = client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_MODEL_NAME"),
                messages=messages,
                tools=available_tools,
                tool_choice="auto",
            )
        assistant_message = response.choices[0].message

        # Multi-round tool call handling
        while assistant_message.tool_calls:
            print(f"\nLLM called tools: {assistant_message.tool_calls}")
            messages.append({
                "role": "assistant",
                "tool_calls": assistant_message.tool_calls
            })

            for tool_call in assistant_message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                # Call the actual function (your implementation)
                result = await call_function(name, args)

                print(f"\nTool {name}, result is: {result}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result)
                })

            # Continue the loop with updated messages
            response = client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_MODEL_NAME"),
                messages=messages,
                tools=available_tools,
                tool_choice="auto"
            )
            assistant_message = response.choices[0].message

        print(f"\nMessages: {messages}")
        print(f"\nLLM final response: {assistant_message.content}")

        return ChatResponse(
            message=Message(
                role=assistant_message.role,
                content=assistant_message.content or ""
            )
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream")
async def chat_stream(chat_request: ChatRequest):
    async def event_generator():
        try:
            print(f"\nUser asks: {chat_request.messages[-1].content}")
            messages = [
                {"role": msg.role, "content": msg.content}
                for msg in chat_request.messages
            ]

            response = client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_MODEL_NAME"),
                messages=messages,
                tools=available_tools,
                tool_choice="auto",
            )
            assistant_message = response.choices[0].message

            while assistant_message.tool_calls:
                print(f"\nLLM called tools: {assistant_message.tool_calls}")
                messages.append({"role": "assistant", "tool_calls": assistant_message.tool_calls})

                for tool_call in assistant_message.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)

                    yield {"event": "tool_call", "data": name}

                    result = await call_function(name, args)

                    print(f"\nTool {name}, result is: {result}")
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    })
                    yield {"event": "tool_update", "data": json.dumps(result)}

                response = client.chat.completions.create(
                    model=os.getenv("AZURE_OPENAI_MODEL_NAME"),
                    messages=messages,
                    tools=available_tools,
                    tool_choice="auto",
                )
                assistant_message = response.choices[0].message

            # print(f"\nMessages: {messages}")
            print(f"\nLLM final response: {assistant_message.content}")

            final_payload = json.dumps({
                "role": assistant_message.role,
                "content": assistant_message.content or "",
            })
            yield {"event": "final", "data": final_payload}
        except Exception as e:
            yield {"event": "error", "data": str(e)}

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
