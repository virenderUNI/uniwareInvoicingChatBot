from pydantic import BaseModel
from typing import List, Dict

class Message(BaseModel):
    role: str
    parts: List[str]

class ChatHistory(BaseModel):
    messages: List[Dict] # Flexible for different message formats

class ChatResponse(BaseModel):
    response: str
    type: str
