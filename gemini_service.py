import google.generativeai as genai
from config import GOOGLE_API_KEY
from typing import List, Dict, Optional
from datetime import datetime

genai.configure(api_key=GOOGLE_API_KEY)

def send_message_gemini(model_name: str, messages: List[Dict], system_instruction: Optional[str] = None) -> str:
    """
    Sends a message to Gemini and returns the response.
    ... (rest of your send_message_gemini function)
    """
    try:
        generation_config = genai.types.GenerationConfig(
            temperature=0.5
        )
        safety_settings = {
            "HARM_CATEGORY_HARASSMENT": "BLOCK_ONLY_HIGH",
            "HARM_CATEGORY_HATE_SPEECH": "BLOCK_ONLY_HIGH",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_ONLY_HIGH",
            "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_ONLY_HIGH"
        }

        model = genai.GenerativeModel(model_name,system_instruction=system_instruction,generation_config=generation_config,safety_settings=safety_settings)
        chat = model.start_chat(history=messages)
        print(messages[-1]["parts"][-1])
        response = chat.send_message(messages[-1]["parts"][-1])
        return response.text
    except Exception as e:
        print(f"Error sending message: {e}")
        return "Sorry, I encountered an error."