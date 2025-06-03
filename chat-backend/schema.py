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

class ModelInfo(BaseModel):
    model_name: str
    model_version: str

class Update(BaseModel):
    deployment_name: str
    new_model_name: str
    new_model_version: str
    new_sku_name: Optional[str] = None
    new_sku_capacity: Optional[int] = None

class DeploymentUpdateRequest(BaseModel):
    resource_group: str
    account_name: str
    update: Update




