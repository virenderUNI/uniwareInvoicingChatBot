from fastapi import FastAPI,HTTPException, Depends
from database import fetch_chat_history, store_message, update_user_order_mappings, get_shipments_by_user, \
    store_message_metadata, archive_user_data, archive_processed_orders_data
from gemini_service import send_message_gemini
from models import ChatHistory, ChatResponse
from typing import List, Dict, Any, Union
import json
from datetime import datetime,timedelta
from fastapi.middleware.cors import CORSMiddleware
import uuid

from uniwareService import make_unicommerce_request, simplify_channels, simplify_warehouses

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or ["*"] for all origins in dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Dependency for getting user ID (replace with your actual authentication)
def get_user_id():
    #  Replace this with your actual authentication logic
    #  For example, you might extract it from a JWT token
    return "user123"  #  Hardcoded for this example

@app.post("/chat")
async def chat(
    history: ChatHistory,
    user_id: str = Depends(get_user_id),
    model_name: str = "gemini-1.5-flash",
    system_instruction: str = """
    You are UniwareBot, an e-commerce fulfillment assistant. You have to provider assistance in identifying what criteria seller is sharing ultimately to process orders or picklist. Orders are combination of ShippingPackages. User can ask to process at Shipping Package level as well, but ultimately that is an order.
    
    BACKGROUND:
    Uniware is an e-commerce software that helps seller in processing orders from various marketplaces stored in their warehouse.
    Order processing is basically asking and generating respective invoices and labels for order/shipment.
    Thus when sellers says they want to process orders, it means they need shipment's invoices and labels.
    Invoice is printed document listing the pricing of the goods, while label is a printed document used to track delivery address for the said order.
    Some Seller process orders individually while some create multiple picklists at warehouse to process the same.
    Engage in conversation with user trying to figure out and restrict the scope orders that need to be processed.  Warehouse and channels are independent of each other. An order is a combination of single or multiple ShippingPackage.
    Order's code in Uniware is ALWAYS unique and sufficient IDENTIFIER in itself. We will be working across a single warehouse at a time.
    
    Follow these STRICT rules:
    
    1. COMMUNICATION PROTOCOL:
       - MODE 1: Natural Language (Seller-facing)
       - MODE 2: Pure JSON (System-facing)
       - TREAT [System Feed] data as a Third-Party reference guide for communication with seller.  
       - Seller DOESN'T have any information regarding [System Feed] , it is supposed to be your guideline and background to communicate with seller.
       - You should reference [System Feed] data to user as user's data itself.
       - NEVER combine both modes in a single response
       - JSON is for internal use
       - You should not combine JSON in a natural language Response 
       - You should ask for confirmation from seller strictly in natural language
       - JSON are returned only when you have confirmed minimum sufficient data required for filtering orders to be processed.
       - In MODE 2, return ONLY valid, complete, and standalone JSON — without any surrounding explanation, commentary, or formatting.
       - ALWAYS ask for clarification wherever mapping fields to values to avoid ambiguity and confusion.
       - ALWAYS present System Feed data to assist user to take decision
    
    2. CORE WORKFLOW (Strictly follow the order):
       - PHASE 1 (Validation): Return VALIDATE action JSON when minimum data is collected. Only return PURE JSON response[MANDATE STEP] for all cases.  
       - PHASE 2 (Processing): Return PROCESS action ONLY after VALIDATE.
       
    
    3. FACILITY WORKFLOW: 
        WAREHOUSE
         - Confirm with user the current facility that we have from [System Feed]
         - If user confirms, work under that warehouse only.
         - If user rejects current facility , suggest him to user SYSTEM's ability to switch Facility before continuing conversation.
    
    4. **ENTITY FILTER CASES (MINIMUM REQUIREMENTS)**:
    
        WAREHOUSE (PARENT)
        - Work under the Facility that we get from System Feed after user confirmation.
        
        **ORDERS (SaleOrder)**:
        - CASE 1: 
          - orderCode(s) → MANDATE

       - CASE 2: 
         * channelCodes - MANDATE (MAP it internally to channelId)
         * fulfillmentTAT (dd-MM-yyyy)  OR  createdDate (dd-MM-yyyy) : - MANDATE 
         
        - CASE 3: 
          - orderStatus ["CREATED"] - Mandate
          - channelIds - MANDATE (MAP it internally to channelId)
          - fulfillmentTat (dd-MM-yyyy)  - OPTIONAL
          - createdDate (dd-MM-yyyy) : - OPTIONAL
         
       - OrderCode in itself is a UNIQUE identifier.
           
       PICKLISTS:
       
       - CASE 1: 
            * picklistCode -MANDATE
       
       SHIPPING_PACKAGES:
       
       - CASE 1: 
            * shippingPackageCode(s) - MANDATE
            
       - CASE 2: 
            * channelCode - MANDATE
            * fulfillmentTAT -OPTIONAL
            * createdDate - OPTIONAL
            
        - CASE 3: 
            * shippingPackageStatus ["CREATED"] - MANDATE
            * channelIds - MANDATE
            * fulfillmentTat -OPTIONAL
            * createdDate - OPTIONAL
        
    
    5. CHANNEL RESOLUTION:
    
         1. Identify ALL channels sharing the sourceCode/channelName
         2. After identifying all channels with matching names and/or sourceCode from [System feed], list these options to user IF there are mutiple channels else take the channel as is.
         3. You should only show list of channel name to user. Keep the matching of channelCode and/or sourceCode internal only.
         4. You can match these names and code case-insensitive internally.
         5. Further, when seller lists only one channel name or code, try to find the nearest exact match for channelName.
         6. If you don't find any then try to match internally with channelCode.
         7. User can also ask for multiple channels with similar names.
         8. User selects one or more channel name,confirm those channel names with seller for inclusion.
         9. Seller only have information for channel Name. Confirm it from System feed which channel(s) to choose.
         10. Internally map these to channelIds. Seller doesn't need to know channelIds.
        
                  
    6. JSON STRUCTURE:
       {
         "action": "VALIDATE"|"PROCESS",
         "entity": "Picklist"|"SaleOrder",
         "filterOptions": [
           {"key": "fieldName", "selectedValues": ["fieldValue"]},
           {"key": "channelFilter", "selectedValues": [channelIds]}
         ]
       }
       FilterOptions Key should follow naming convention as field + Filter, for example , channel will have channelFilter, createdDate will have createdDateFilter and so on.
          
    7. VALIDATION FLOW
        1. After minimum data is collected , for example in orders we have all minimum fields described in permutation B, return PURE JSON with action VALIDATE.
        2. Analyse Validation Data given as [SYSTEM feed]
        3. Based on Validation Data return same JSON with action PROCESS
    
    8. DATA RESOLUTION:
       - Warehouses: Verify codes exist in [SYSTEM feed]
       - When presented with ANY or ALL warehouse ,resolve it list [] of warehouseCodes from [System Feed]
       - Dates: Convert "today"→dd-MM-yyyy internally
       - Don't suggest date format to user. Understand their natural language and convert internally.
       - Warehouses and Channels are INDEPENDENT entities.
       - Seller Facing, only share facility Display names and channel Names with user, keep rest of mapping internal.
    
    9. ERROR HANDLING:
       - Missing data: Ask specific questions
         "Which warehouse is this picklist for?"
         "Should we use created date or fulfillment deadline?"
       - Invalid data: Explain and re-prompt
         "MAGENTO-2 isn't a valid channel code. Options: AMAZON_IN, FLIPKART_UK"
    
    10. STRICT PROHIBITIONS:
       - Refrain from proceeding to any further conversation before seller confirms warehouse.
       - NEVER breach order of coreWorkFlow. Follow PHASES as is.
       - NEVER make assumptions about any data. Ask for clarification
       - NEVER create JSON before minimum requirements are fetched from seller.
       - Never mix JSON with natural language when responding to user
       - Never return JSON string with missing requirements
       - Never auto map channel to codes.
       - Never process across channels without explicit "ALL"
       - For ambiguous names: "Did you mean AMAZON_IN or AMAZON_US?"
       - Never guess - ask for clarification
       - Avoid processing any other ENTITY than ORDER and PICKLIST
       
    11. RESPONSE FORMATTING: 
       - Always use Markdown-style formatting with **bold**, *italics*, and line breaks.
""",
    temperature: float = 0.2,
):
    """
    Endpoint for chatting with the Gemini model.
    """
    # Fetch chat history from MongoDB
    chat_history_from_db = fetch_chat_history(user_id)

    messages_metadata = chat_history_from_db.get("messages_metadata")
    messages = chat_history_from_db.get("messages")

    # Convert database history to the format expected by google.generativeai
    formatted_history = []

    for message in messages_metadata:
        if message["role"] == "user":
            formatted_history.append({"role": "user", "parts": [message["message"]]})
        elif message["role"] == "model":
            formatted_history.append({"role": "model", "parts": [message["message"]]})

    for message in messages:
        if message["role"] == "user":
            formatted_history.append({"role": "user", "parts": [message["message"]]})
        elif message["role"] == "model":
            formatted_history.append({"role": "model", "parts": [message["message"]]})

    #add the current user message.
    formatted_history.extend(history.messages)
    user_message_text = history.messages[-1]["parts"][0] #gets the last message

    # Store user message
    store_message(user_id, user_message_text, "user")

    gemini_response = send_message_gemini(
        model_name, formatted_history, system_instruction
    )
    store_message(user_id, gemini_response, "model")

    formatted_history.append({"role":"model","parts":[gemini_response]}) #add to history

     # Check for JSON in the response (Example logic)
    try:
        response_json = extract_pure_json(gemini_response)

        if response_json.get("action") == "VALIDATE":
            archive_processed_orders_data(get_user_id())
            order_validation_result = validate_order(response_json)
            followup_message = f"[System Feed] Order validation status: {order_validation_result}. Confirm the count to user before processing"
            store_message(user_id, followup_message, "user", metadata={"order_validation": order_validation_result})
            formatted_history.append({"role": "user", "parts": [followup_message]})

        if response_json.get("action") == "PROCESS":
            order_process_result = process_order(response_json)
            followup_message = f"[System Feed] Order Process status: {order_process_result}. Please provide an appropriate response to the user."
            store_message(user_id, followup_message, "user", metadata={"order_process": order_process_result})
            archive_user_data(get_user_id(),False)
            formatted_history.append({"role": "user", "parts": [followup_message]})


        gemini_response_to_user = send_message_gemini(model_name, formatted_history, system_instruction)
        store_message(user_id, gemini_response_to_user, "user")
        return ChatResponse(response=gemini_response_to_user)

    except json.JSONDecodeError:
        return ChatResponse(response=gemini_response) # Return the string


@app.post("/chat/initiate")
async def chat(
        user_id: str = Depends(get_user_id),
        model_name: str = "gemini-1.5-flash",
        system_instruction: str = """
""",
        temperature: float = 0.2,
):
    """
    Endpoint for chatting with the Gemini model.
    """

    formatted_history = []

    archive_user_data(get_user_id(),True)
    channels_response = make_unicommerce_request("/data/channel/getChannels","POST")
    # warehouse_response = make_unicommerce_request("/data/user/facilities","GET")

    store_message(user_id, "Hi, I'm your Uniware assistant. I'll help analyze your data.", "model")

    # Get current date in correct format
    current_date = datetime.now().strftime("%d-%m-%Y")

    store_message_metadata(user_id, f"[System Feed] CHANNELS: {simplify_channels(channels_response.json())}", "user")
    # 3. Store with 'system' type if needed (your storage logic)
    store_message_metadata(user_id, f"[System Feed] CURRENT WAREHOUSE DISPLAY NAME: 1514 Store - 1 ", "user")
    store_message_metadata(user_id, f"[System Feed] TodayDate : {current_date} , calculate relative dates like tomorrow , today , next week , taking this as reference","user")

    return {"sessionId": get_user_id()}


def build_filter(filter_id, selected_values):
    return {
        "id": filter_id,
        "selectedValues": selected_values
    }

def build_request_body(columns, filters, name="DATATABLE SHIPMENTS TAB", no_of_results=200, start=0,
                       fetch_result_count=True, disable_label_many="false"):
    return {
        "columns": columns,
        "fetchResultCount": fetch_result_count,
        "disableLabelMany": disable_label_many,
        "noOfResults": no_of_results,
        "start": start,
        "name": name,
        "filters": filters
    }


def convert_date_format(input_date: str) -> Dict[str, str]:
    """
    Convert dd-MM-yyyy to ISO format with full day range:
    - Start date = previous day at 00:00:00
    - End date = input date at 23:59:59.999
    """
    try:
        # Parse input date
        dt = datetime.strptime(input_date, "%d-%m-%Y")

        # Calculate start date (previous day at 00:00:00)
        start_date = (dt - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        # Calculate end date (input date at 23:59:59.999)
        end_date = dt.replace(hour=23, minute=59, second=59, microsecond=999000)

        return {
            "start": start_date.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "end": end_date.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        }
    except ValueError as e:
        raise ValueError(f"Invalid date format. Expected dd-MM-yyyy, got {input_date}") from e


def transform_filter_options(filter_options: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transform filter options according to business rules
    """
    transformed_filters = []

    for option in filter_options:
        key = option.get("key")
        value = option.get("selectedValues")

        if not key or value is None:
            continue

        if key in "createdDateFilter":
            date_range = convert_date_format(value[0] if isinstance(value, list) else value)
            transformed_filters.append({
                "id": "createdDateRangeFilter",
                "dateRange": date_range
            })

        elif key in "channelFilter":
            transformed_filters.append({
                "id": "channelFilter",
                "selectedValues": value if isinstance(value, list) else [value]
            })

        elif key in "fulfillmentTATFilter":
            date_range = convert_date_format(value[0] if isinstance(value, list) else value)
            transformed_filters.append({
                "id": "fulfillmentTatDateRangeFilter",
                "dateRange": date_range
            })

        elif key in "orderCodeFilter":
            transformed_filters = [{
                "id": "saleOrderCodes",
                "saleOrderCodes": value if isinstance(value, list) else [value]
            }]
            break

        elif key in "orderStatusFilter":
            date_range = convert_date_format(value[0] if isinstance(value, list) else value)
            transformed_filters.append({
                "id": "fulfillmentTatDateRangeFilter",
                "dateRange": date_range
            })
            break

    return transformed_filters

def fetch_picklist_codes_from_filter(filter_options: List[Dict[str, Any]]) -> List[str]:

    picklist_codes = []
    for option in filter_options:
        key = option.get("key")
        value = option.get("selectedValues")

        if not key or value is None:
            continue

        if key == "picklistCodeFilter":
            picklist_codes = value if isinstance(value, list) else [value]

    return picklist_codes



def process_validation_request_filters(input_json: Dict[str, Any]) -> Union[list[dict[str, Any]], dict[str, Any]]:
    """
    Main processing function for Uniware JSON
    """
    if not isinstance(input_json, dict):
        raise ValueError("Input must be a JSON dictionary")

    action = input_json.get("action")
    entity = input_json.get("entity")
    filter_options = input_json.get("filterOptions", [])

    if action not in ["VALIDATE", "PROCESS"]:
        raise ValueError("Invalid action. Must be VALIDATE, PROCESS")

    if entity not in ["Picklist", "SaleOrder"]:
        raise ValueError("Invalid entity. Must be Picklist, SaleOrder")

    # Transform filters only for VALIDATE action
    if action == "VALIDATE" and entity in "SaleOrder":
        transformed_filters = transform_filter_options(filter_options)
        return transformed_filters

    else:
        # For PROCESS/SWITCH, return as-is (or add additional processing if needed)
        return input_json.get("filterOptions")


def validate_order(validation_request: dict) -> str:
    """
    Simulates validating an order with an external system.
    Replace this with your actual order validation logic.
    """
    # Usage
    extracted_data = []
    result = ""

    if validation_request.get("entity", "").upper() == "SALEORDER":

        shipment_columns = ["saleOrderNum", "channel", "picklist", "fulfillmentTat", "shipment"]
        orders_columns = ["saleOrderNum","shipment"]
        shipment_filters = process_validation_request_filters(validation_request)
        if len(shipment_filters) == 1 and shipment_filters[0].get("id") in "saleOrderCodes":
            saleOrdersCodes = shipment_filters[0].get("saleOrderCodes")
            for saleOrder in saleOrdersCodes:
                sale_order_details_request = {
                    "saleOrderCode" : saleOrder
                }
                order_response = make_unicommerce_request("/data/oms/saleorder/fetchShippingPackageDetails","POST",sale_order_details_request)
                if order_response.status_code == 200:
                    order_response_json = order_response.json()
                    if order_response_json.get("successful") is True:
                        shipping_packages = order_response_json.get("shippingPackages",[])
                        for shipping_package in shipping_packages:
                            extracted_data.extend([
                                {"saleOrderNum":saleOrder,"shipment":shipping_package.get("code")}
                            ])
                    else:
                        result = f"\n{result} - No ShippingPackage found for saleOrderCode {saleOrder}"
                else:
                    result=f"\n{result} - Invalid SaleOrderCode {saleOrder}"
        else:
            shipment_request_body = build_request_body(shipment_columns, shipment_filters)
            orders_response = make_unicommerce_request("/data/tasks/export/data","POST",shipment_request_body)
            extracted_data = extract_orders_response(orders_response.json(), shipment_columns, orders_columns)

    elif validation_request.get("entity","").upper() == "PICKLIST":

        picklist_codes = fetch_picklist_codes_from_filter(validation_request.get("filterOptions"))
        for picklist in picklist_codes:
            packlist_request_body= {
                "picklistCode" : picklist
            }
            packlist_response = make_unicommerce_request("/data/oms/packer/packlist/fetch","POST",packlist_request_body)
            if packlist_response.status_code == 200:
                packlist = packlist_response.json().get("packlist", {})

                packlist_items = packlist.get("packlistItems", [])

                order_packlist_data = [
                    {"saleOrderNum": item.get("saleOrderCode"), "shipment": item.get("code")}
                    for item in packlist_items
                    if item.get("saleOrderCode")
                ]
                extracted_data.extend(order_packlist_data)
            else:
                result = f"\n{result} - Invalid PicklistCode, Picklist might not exist"

    if len(extracted_data) > 0:
        update_user_order_mappings(
            user_id=get_user_id(),
            new_orders=extracted_data
        )
        result =  f"Found{len(extracted_data)} orders can be processed based on criteria."
    else:
        result = "Failure. No orders found to be process based on given criteria"

    return result


def extract_orders_response(response_data, column_names, extract_fields) ->list:
    """Dynamically extract fields based on column mapping"""
    column_positions = {name: idx for idx, name in enumerate(column_names)}

    results = []
    for row in response_data.get('rows', []):
        values = row.get('values', [])
        if len(values) >= len(column_names):
            entry = {}
            for field in extract_fields:
                if field in column_positions:
                    entry[field] = values[column_positions[field]]
            if entry:
                results.append(entry)
    return results



def process_order(order_details: dict) -> str:
    """
    Simulates validating an order with an external system.
    Replace this with your actual order validation logic.
    """
    process_order_response = ""
    orders = get_shipments_by_user(get_user_id())

    invoice_success_shipments = []
    invoice_failed_shipments = []
    label_failed_shipments = []
    label_success_shipments = []
    print_invoices = []
    print_invoices_labels =[]
    print_labels= []

    for order in orders:
        process_order_response = process_invoice_for_order(order,print_invoices_labels,print_invoices,invoice_success_shipments,invoice_failed_shipments)
        print(process_order_response)

    if print_invoices_labels:
        print_invoice_label_request = {
            "shippingPackageCodes" : print_invoices_labels
        }
        print_invoices_labels_response = make_unicommerce_request("/data/oms/shipment/printInvoiceAndLabel/bulk","POST",print_invoice_label_request)

        if print_invoices_labels_response.status_code == 200 and "application/pdf" in print_invoices_labels_response.headers.get("Content-Type") :
            file_path = save_pdf_to_temp(print_invoices_labels_response.content,"hoadstaging",get_user_id(),"invoice_label")
            process_order_response = f"Successfully generated invoices , Link to combined pdf : {file_path}"



    if print_invoices:
        print_invoice_request = {
            "invoiceCodes": print_invoices
        }
        print_invoice_response = make_unicommerce_request("/data/oms/invoice/show/bulk","POST",print_invoice_request)
        if print_invoice_response.status_code == 200 and "application/pdf" in print_invoice_response.headers.get("Content-Type") :
            invoice_file_path = save_pdf_to_temp(print_invoice_response.content,"hoadstaging",get_user_id(),"invoice")
            process_order_response = f"Successfully generated invoices , Link to combined pdf : {invoice_file_path}"
            for order in orders:
                process_label_for_order_response = process_label_for_order(order,print_labels,label_success_shipments,label_failed_shipments)
            print_label_request = {
                "shippingPackageCodes" : print_labels
            }
            print_labels_response = make_unicommerce_request("/data/oms/shipment/show/bulk","POST",print_label_request)
            if print_labels_response.status_code == 200 and "application/pdf" in print_labels_response.headers.get("Content-Type"):
                label_file_path = save_pdf_to_temp(print_labels_response.content, "hoadstaging", get_user_id(),"label")
                process_order_response = f"{process_order_response} ,Successfully generated label , Link to combined pdf : {label_file_path}"
            else:
                process_order_response = f"{process_order_response}, But label generation failure , thus not file path"
        else:
            process_order_response= f"Unable to process orders at the time due to internal error"


    return process_order_response

def process_invoice_for_order(order,print_invoices_labels,
    print_invoices,
    invoice_success_shipments,
    invoice_failed_shipments):
    request_body = {
        "shippingPackageCode": order.get('shipment')
    }

    invoice_response = make_unicommerce_request("/data/oms/invoice/create", "POST", request_body)
    status_code = invoice_response.status_code
    shipment = order.get('shipment')

    if 200 <= status_code < 300:
        try:
            data = invoice_response.json()
            successful = data.get("successful", False)
            invoice_code = data.get("invoiceCode")
            shipping_label_link = data.get("shippingLabelLink")

            if successful is True or (successful is False and invoice_code):
                if shipping_label_link is not None:
                    print_invoices_labels.append(shipment)
                    invoice_success_shipments.append(shipment)
                else:
                    print_invoices.append(invoice_code)
                    invoice_success_shipments.append(shipment)

                return f"Invoice created successfully: {invoice_code}"
            else:
                invoice_failed_shipments.append(shipment)
                return f"API returned success status but no invoiceCode. Full response: {data}"

        except ValueError:
            return f"Invalid JSON in successful response. Status: {status_code}"

    elif 400 <= status_code < 500:
        invoice_failed_shipments.append(shipment)
        return f"🚫 Client error ({status_code}): {invoice_response.text}"

    else:
        invoice_failed_shipments.append(shipment)
        return f"❗ Unexpected status code ({status_code}): {invoice_response.text}"

def process_label_for_order(order,
    print_labels,
    label_success_shipments,
    label_failed_shipments):
    request_body = {
        "shippingPackageCode": order.get('shipment')
    }

    label_response = make_unicommerce_request("/data/oms/shipment/provider/allocate", "POST", request_body)
    status_code = label_response.status_code
    shipment = order.get('shipment')

    if 200 <= status_code < 300:
        try:
            data = label_response.json()
            successful = data.get("successful", False)
            shipping_provider_code = data.get("shippingProviderCode")

            if successful is True or (successful is False and shipping_provider_code):
                print_labels.append(shipment)
                label_success_shipments.append(shipment)
                return f"Label successfully created with provider {shipping_provider_code} for package: {shipment}"
            else:
                label_failed_shipments.append(shipment)
                return f"API returned success status but no shipping_provider_code. Full response: {data}"

        except ValueError:
            return f"Invalid JSON in successful response. Status: {status_code}"

    elif 400 <= status_code < 500:
        label_failed_shipments.append(shipment)
        return f"🚫 Client error ({status_code}): {label_response.text}"

    else:
        label_failed_shipments.append(shipment)
        return f"❗ Unexpected status code ({status_code}): {label_response.text}"

def save_pdf_to_temp(response_content, tenant_code, user_id,type):

    time_str = datetime.now().strftime("%H%M%S")
    filename = f"{tenant_code}_{user_id}_{time_str}_{type}.pdf"
    file_path = f"/Users/virendersingh/Downloads/{filename}"

    with open(file_path, "wb") as f:
        f.write(response_content)

    return file_path

@app.get("/history")
async def get_history(user_id: str = Depends(get_user_id)) -> List[Dict]:
    """
    Endpoint to retrieve chat history for a user.
    """
    chat_history = fetch_chat_history(user_id)
    return chat_history


def extract_pure_json(response: str) -> dict:
    """Extracts JSON from a string that may have markdown markers."""
    # Trim whitespace and potential markdown markers
    stripped = response.strip().removeprefix('```json').removesuffix('```').strip()
    return json.loads(stripped)
