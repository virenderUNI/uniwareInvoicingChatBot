import google.generativeai as genai
from config import GOOGLE_API_KEY
from typing import List, Dict, Optional, Union
from datetime import datetime
from google.generativeai.types import FunctionDeclaration
from google.protobuf.json_format import MessageToDict

from proto_utils import normalize_gemini_args

genai.configure(api_key=GOOGLE_API_KEY)

switch_facility_tool = FunctionDeclaration(
    name="switch_facility",
    description=(
        "Switches the seller's active warehouse (facility) to a different one. "
    ),
    parameters={
        "type": "object",
        "properties": {
            "facilityCode": {
                "type": "string",
                "description": (
                    "The internal facilityCode corresponding to the warehouse the user wants to switch to. "
                    "Use facilityCode (not displayName) for facilityCode by mapping from [System Feed] facility list."
                )
            }
        },
        "required": ["facilityCode"]
    }
)

fetch_order_tool = FunctionDeclaration(
    name="fetch_order",
    description="Fetches a seller’s orders or picklists before processing, using provided filter options.",
    parameters={
        "type": "object",
        "properties": {
            "entity": {
                "type": "string",
                "description": "Target entity: either 'SaleOrder' or 'Picklist'."
            },
            "filterOptions": {
                "type": "array",
                "description": (
                    "List of filters to narrow down which orders to fetch. "
                    "Use channel ID (not name) for channelFilter by mapping from [System Feed] channel list. "
                    "If the entity is 'SaleOrder' and no 'orderStatusFilter' is explicitly given by the user, "
                    "you must add {'key': 'orderStatusFilter', 'selectedValues': ['CREATED']} by default."
                    "However if user suggests otherwise, you should skip orderStatusFilter."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Filter type (e.g., orderCodeFilter, picklistCodeFilter, channelFilter)"
                        },
                        "selectedValues": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["key", "selectedValues"]
                }
            }
        },
        "required": ["entity", "filterOptions"]
    }
)

# process_order_tool = FunctionDeclaration(
#     name="process_order",
#     description="Processes validated orders from the current session. Call only after validate_order.",
#     parameters={
#         "type": "object",
#         "properties": {},
#         "required": []
#     }
# )

process_order_tool = FunctionDeclaration(
    name="process_order",
    description="Processes selected orders from the current session. Gemini should select and return only orders that the seller has confirmed.",
    parameters={
        "type": "object",
        "properties": {
            "orders": {
                "type": "array",
                "description": "List of confirmed orders to process. Each order must include shipment code, saleOrderNum, and channel info from context.",
                "items": {
                    "type": "object",
                    "properties": {
                        "saleOrderNum": {"type": "string"},
                        "shipment": {"type": "string"},
                        "channel": {"type": "string"},
                        "channelName": {"type": "string"},
                        "channelId": {"type": "integer"}
                    },
                    "required": ["saleOrderNum", "shipment", "channel", "channelName", "channelId"]
                }
            }
        },
        "required": ["orders"]
    }
)

tools = [fetch_order_tool, process_order_tool,switch_facility_tool]


def extract_gemini_response_parts(response):
    """
    Handles mixed Gemini responses: text and/or tool call.
    Returns:
        {
            "tool_call": { "name": str, "args": dict },  # if any
            "text_response": str                         # if any
        }
    """
    result = {}
    parts = response.candidates[0].content.parts
    text_blocks = []

    for part in parts:
        # Check for tool call
        if hasattr(part, "function_call") and part.function_call:
            result["tool_call"] = {
                "name": part.function_call.name,
                "args": normalize_gemini_args(part.function_call.args)
            }
        # Check for natural language text
        elif hasattr(part, "text") and part.text.strip():
            text_blocks.append(strip_markdown_escapes(part.text.strip()))

    if text_blocks:
        result["text_response"] = "\n\n".join(text_blocks)

    return result


def send_message_gemini(
    model_name: str,
    messages: List[Dict],
    system_instruction: Optional[str] = None
) -> Union[str, Dict]:
    """
    Sends a message to Gemini and returns either:
    - a string (text response), or
    - a dict with tool_call if Gemini wants to invoke a function.
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

        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_instruction,
            generation_config=generation_config,
            safety_settings=safety_settings,
            tools=tools
        )

        # Use generate_content directly (tool mode)
        response = model.generate_content(messages)

        # part = response.candidates[0].content.parts[0]
        # if part.function_call is not None and part.function_call.name :
        #     return {
        #         "tool_call": {
        #             "name": part.function_call.name,
        #             "args": normalize_gemini_args(part.function_call.args)
        #         }
        #     }
        #
        # return response.text
        return extract_gemini_response_parts(response)

    except Exception as e:
        print(f"Error sending message: {e}")
        return "Sorry, I encountered an error."


def strip_markdown_escapes(text: str) -> str:
    return text.replace("\\_", "_")

