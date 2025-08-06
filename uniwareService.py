import requests
from typing import Dict, Any

from dns.edns import COOKIE

from database import fetch_chat_session_auth
import logging,traceback



def make_unicommerce_request(
        tenant_code : str,
        endpoint: str,
        method: str,
        chat_sesion_id: str,
        data: Dict[str, Any] = None,
        custom_headers: Dict[str, str] = None,
        custom_cookies: Dict[str, str] = None,
) -> requests.Response:
    """
    Make a request to Unicommerce staging API

    Args:
        endpoint: API endpoint (e.g., '/data/channel/getChannels')
        method: HTTP method (GET, POST, etc.)
        data: Request payload for POST/PUT requests
        custom_headers: Additional headers to merge with default headers
        custom_cookies: Additional cookies to merge with default cookies

    Returns:
        requests.Response object
        :param tenant_code:
    """
    session_auth = fetch_chat_session_auth(chat_sesion_id)
    if session_auth["isJSession"] is True:
        access_token =  session_auth["token"]
        HEADERS = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
            'Content-Type': 'application/json',
            'Cookie' : f"JSESSIONID={access_token};"
        }
        COOKIES = {}
    else:
        access_token = session_auth["token"]
        HEADERS = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
            'Content-Type': 'application/json',
            "Authorization": f"Bearer {access_token}"
        }
        COOKIES = {}

    url = f"https://{tenant_code}.unicommerce.com/{endpoint}"
    headers = {**HEADERS, **(custom_headers or {})}
    cookies = {**COOKIES ,**(custom_cookies or {})}

    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, cookies=cookies)
        elif method.upper() in ["POST", "PUT", "PATCH", "DELETE"]:
            response = requests.request(
                method,
                url,
                headers=headers,
                cookies=cookies,
                json=data or {}
            )
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        return response

    except requests.exceptions.RequestException as e:
        print(f"Request failed: {str(e)}")
        raise



def simplify_channels(channel_data):
    """
    Extracts only the essential channel information from the API response

    Args:
        channel_data: The full channels JSON response

    Returns:
        List of simplified channel dictionaries with:
        - channelCode
        - channelName
        - sourceCode
        - sourceName
    """
    simplified_channels = []

    for channel in channel_data.get('channels', []):
        simplified = {
            'channelId' : channel.get('channelId'),
            'channelCode': channel.get('code'),
            'channelName': channel.get('name'),
            'sourceCode': channel.get('sourceDTO', {}).get('code'),
            'sourceName': channel.get('sourceDTO', {}).get('name')
        }
        simplified_channels.append(simplified)

    channel_header = "Available channels (format: channelId -> Name(Code) → Source: SourceName(Code)):\n"
    channels_str = channel_header + "\n".join([
        f"• {ch['channelId']} -> {ch['channelName']}({ch['channelCode']}) → Source: {ch['sourceName']}({ch['sourceCode']})"
        for ch in simplified_channels
    ])

    return channels_str


def simplify_warehouses(warehouse_data):
    """
    Extracts only the essential warehouse information from the API response

    Args:
        warehouse_data: The full warehouse JSON response

    Returns:
        List of simplified warehouse dictionaries with:
        - code
        - displayName
    """
    simplified_warehouses = []

    warehouse_header = "Available warehouses, FORMAT FOR NAMING (facilityCOde: facility DisplayName):\n"
    for warehouse in warehouse_data.get('facilityDTOList', []):
        simplified = {
            'facilityCode': warehouse.get('code'),
            'facilityDisplayName': warehouse.get('displayName')
        }
        simplified_warehouses.append(simplified)

    # Convert to string representation
    warehouses_str = warehouse_header + "\n".join([
        f"{wh['facilityCode']}: {wh['facilityDisplayName']}"
        for wh in simplified_warehouses
    ])

    return warehouses_str