from typing import List, Optional
from pydantic import BaseModel

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    tools: Optional[List[dict]] = None

class ChatResponse(BaseModel):
    message: Message

class SubscriptionRequest(BaseModel):
    subscription_id: str