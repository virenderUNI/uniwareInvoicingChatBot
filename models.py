from pydantic import BaseModel
from typing import List, Dict, Optional

class Message(BaseModel):
    role: str
    parts: List[str]

class ChatHistory(BaseModel):
    messages: List[Dict] # Flexible for different message formats

class ChatResponse(BaseModel):
    response: str