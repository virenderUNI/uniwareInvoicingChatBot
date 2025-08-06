import base64

from fastapi import FastAPI, HTTPException, Depends
from starlette.middleware import Middleware
from mangum import Mangum
from Constants import Gemini_System_Instruction, Gemini_Model_Name, sampleBase64Pdf, Play_Mode
from database import fetch_chat_history, store_message, update_user_order_mappings, get_shipments_by_user, \
    store_message_metadata, archive_user_data, archive_processed_orders_data, clear_message_metadata, \
    create_chat_session_auth
from gemini_service import send_message_gemini
from models import ChatHistory, ChatResponse, LoginRequest, ChatSessionRequest
from typing import List, Dict, Any, Union
import json
from datetime import datetime, timedelta
from starlette.middleware.cors import CORSMiddleware
import io
from PyPDF2 import PdfMerger
from fastapi import HTTPException, status, Response, Request
import requests
from RequestContext import RequestContext
from urllib.parse import urlencode
import hashlib
from fastapi.responses import JSONResponse

from uniwareService import make_unicommerce_request, simplify_channels, simplify_warehouses
import logging, traceback

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["http://chatbot-uibucket.s3-website.ap-south-1.amazonaws.com",
                       "https://chatbot.unicommerce.com"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = FastAPI(middleware=middleware)

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def generate_session_id(user_id: str) -> str:
    """Generates a SHA-256 hash of userId and timestamp."""
    timestamp = int(datetime.now().timestamp() * 1000)
    return hashlib.sha256(f"{user_id}{timestamp}".encode()).hexdigest()


# Middleware to enforce authentication
@app.middleware("http")
async def authenticate_request(request: Request, call_next):
    """
    Middleware to check authentication for every request.
    Skips authentication for public endpoints like /login.
    """

    if request.method == "OPTIONS":
        return await call_next(request)

    public_paths = [
        "/login",
        "/bot/session/create"
    ]
    # Initialize RequestContext
    context = RequestContext()
    RequestContext.set_current(context)

    # Skip authentication for public endpoints
    if request.url.path in public_paths:
        return await call_next(request)

    tenant_code = request.headers.get("x-tenant-code")
    session_id = request.headers.get("x-chat-session-id")
    user_id = request.headers.get("x-user-id")

    logger.info(f"tenantCode is :{tenant_code}")
    logger.info(f"session Id is :{session_id}")

    if not tenant_code:
        return JSONResponse(
            content=json.dumps({"detail": "Tenant code is required"}),
            status_code=status.HTTP_400_BAD_REQUEST,
            media_type="application/json"
        )

    if not session_id:
        return JSONResponse(
            content=json.dumps({"detail": "Session missing, Not logged in"}),
            status_code=status.HTTP_401_UNAUTHORIZED,
            media_type="application/json"
        )
    try:
        # validate_response = requests.get(
        #     f"https://{tenant_code}.unicommerce.com/data/user/facilities",
        #     headers={"Authorization": f"Bearer {access_token}"}
        # )
        # if validate_response.status_code != 200:
        #     return JSONResponse(
        #         content=json.dumps({"detail": "Invalid or expired token"}),
        #         status_code=status.HTTP_401_UNAUTHORIZED,
        #         media_type="application/json"
        #     )

        # Store data in RequestContext
        context.set("tenant_code", tenant_code)
        context.set("user_id", user_id)
        context.set("session_id", session_id)

        # Proceed with the request
        response = await call_next(request)
        return response
    except requests.RequestException:
        return JSONResponse(
            content=json.dumps({"detail": "Invalid or expired token"}),
            status_code=status.HTTP_401_UNAUTHORIZED,
            media_type="application/json"
        )
    finally:
        # Clear context after request
        RequestContext.set_current(None)


@app.post("/chat")
async def chat(
        request: Request,
        history: ChatHistory,
        model_name: str = Gemini_Model_Name,
        system_instruction: str = Gemini_System_Instruction,
):
    """
    Handles chat interaction with Gemini model, supports function calling.
    """
    context = RequestContext.current()
    tenant_code = context.get("tenant_code")
    session_id = context.get("session_id")
    user_id = context.get("user_id")

    # Prepare full conversation history
    formatted_history = []

    db_history = fetch_chat_history(user_id, session_id)
    messages_metadata = db_history.get("messages_metadata", [])
    messages = db_history.get("messages", [])

    for meta in messages_metadata:
        formatted_history.append({
            "role": "user",
            "parts": [meta["message"]]
        })

    for message in messages:
        formatted_history.append({
            "role": message["role"],
            "parts": [message["message"]]
        })

    formatted_history.extend(history.messages)
    user_message_text = history.messages[-1]["parts"][0]

    # Save user message
    store_message(user_id, session_id, user_message_text, "user")

    # Call Gemini
    response = send_message_gemini(model_name, formatted_history, system_instruction)

    # CASE 1: Tool call
    if isinstance(response, dict) and "tool_call" in response:
        tool_name = response["tool_call"]["name"]
        args = response["tool_call"]["args"]

        if tool_name == "fetch_order":
            result = fetch_order(args)
            store_message(user_id, session_id, result, "user")

            followup_history = formatted_history + [{
                "role": "user",
                "parts": [result]
            }]
            final_response = send_message_gemini(model_name, followup_history, system_instruction)
            store_message(user_id, session_id, final_response["text_response"], "model")
            return ChatResponse(response=final_response["text_response"], type="text")

        elif tool_name == "process_order":
            result, pdf_base64 = process_order(args)
            store_message(user_id, session_id, result, "user")

            followup_history = formatted_history + [{
                "role": "user",
                "parts": [result]
            }]
            final_response = send_message_gemini(model_name, followup_history, system_instruction)
            logger.info(f"final response is {final_response}")
            store_message(user_id, session_id, final_response["text_response"], "user")

            if pdf_base64:
                return ChatResponse(response=pdf_base64, type="pdf")
            return ChatResponse(response=final_response["text_response"], type="text")

        elif tool_name == "switch_facility":
            result = switch_facility_uniware(args)
            store_message(user_id, session_id, result, "user")

            followup_history = formatted_history + [{
                "role": "user",
                "parts": [result]
            }]
            final_response = send_message_gemini(model_name, followup_history, system_instruction)
            store_message(user_id, session_id, final_response["text_response"], "user")

            return ChatResponse(response=final_response["text_response"], type="text")

        return ChatResponse(response="Unknown tool call", type="text")

    store_message(user_id, session_id, response["text_response"], "model")
    return ChatResponse(response=response["text_response"], type="text")


@app.post("/chat/initiate")
async def chat():
    """
    Endpoint for chatting with the Gemini model.
    """
    context = RequestContext.current()

    tenant_code = context.get("tenant_code")
    session_id = context.get("session_id")
    user_id = context.get("user_id")

    clear_message_metadata(user_id, session_id)
    archive_user_data(user_id, session_id, True)
    channels_response = make_unicommerce_request(tenant_code, "/data/channel/getChannels", "POST", session_id, {})
    facility_response = make_unicommerce_request(tenant_code, "/data/user/facilities", "GET", session_id, {})
    warehouse_display_name = get_current_warehouse_display_name(facility_response.json())
    pending_orders = fetch_pending_orders_shipment()

    if len(pending_orders) > 0:
        update_user_order_mappings(
            user_id=user_id,
            session_id=session_id,
            new_orders=pending_orders
        )

    store_message(user_id, session_id, "Hi, I'm your Uniware assistant. I'll help analyze your data.", "model")

    # Get current date in correct format
    current_date = datetime.now().strftime("%d-%m-%Y")

    store_message_metadata(user_id, session_id,
                           f"[System Feed] CHANNELS: {simplify_channels(channels_response.json())}", "user")
    store_message_metadata(user_id, session_id,
                           f"[System Feed] CURRENT WAREHOUSE DISPLAY NAME: {warehouse_display_name}", "user")
    store_message_metadata(user_id, session_id,
                           f"[System Feed] ALL WAREHOUSES USER HAS ACCESS TO: {simplify_warehouses(facility_response.json())}",
                           "user")
    store_message_metadata(user_id, session_id,
                           f"[System Feed] Today's Date is : {current_date} , calculate relative dates like tomorrow , today , next week , taking this as reference",
                           "user")
    store_message_metadata(user_id, session_id,
                           f"[System Feed] summary of Pending/Created orders for user for the warehouse :{warehouse_display_name} pending orders  : {pending_orders}",
                           "user")

    return {"message": "Hi, How can I assist you today", "session_id": session_id}


def build_filter(filter_id, selected_values):
    return {
        "id": filter_id,
        "selectedValues": selected_values
    }


def build_request_body(columns, filters, name="DATATABLE SHIPMENTS TAB", no_of_results=5000, start=0,
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
            transformed_filters.append({
                "id": "statusFilter",
                "selectedValues": value if isinstance(value, list) else [value]
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

    entity = input_json.get("entity")
    filter_options = input_json.get("filterOptions", [])

    if entity not in ["Picklist", "SaleOrder"]:
        raise ValueError("Invalid entity. Must be Picklist, SaleOrder")

    # Transform filters only for VALIDATE action
    if entity in "SaleOrder":
        transformed_filters = transform_filter_options(filter_options)
        return transformed_filters

    else:
        # For PROCESS/SWITCH, return as-is (or add additional processing if needed)
        return input_json.get("filterOptions")


def fetch_pending_orders_shipment() -> list:
    # Usage
    extracted_data = []
    result = ""
    context = RequestContext.current()

    tenant_code = context.get("tenant_code")
    user_id = context.get("user_id")
    session_id = context.get("session_id")

    shipment_columns = ["saleOrderNum", "channel", "picklist", "fulfillmentTat", "shipment", "channelName", "channelId"]
    orders_columns = ["saleOrderNum", "shipment", "channel", "channelName", "channelId"]
    shipment_filters = [{
        "id": "statusFilter",
        "selectedValues": ["CREATED"]
    }]
    shipment_request_body = build_request_body(shipment_columns, shipment_filters)
    orders_response = make_unicommerce_request(tenant_code, "/data/tasks/export/data", "POST", session_id,
                                               shipment_request_body)
    extracted_data = extract_orders_response(orders_response.json(), shipment_columns, orders_columns)

    return extracted_data


def fetch_order(validation_request: dict) -> str:
    """
    Simulates validating an order with an external system.
    Replace this with your actual order validation logic.
    """
    # Usage
    extracted_data = []
    result = ""
    context = RequestContext.current()

    tenant_code = context.get("tenant_code")
    access_token = context.get("access_token")
    headers = {"Authorization": f"Bearer {access_token}"}
    user_id = context.get("user_id")
    session_id = context.get("session_id")

    if validation_request.get("entity", "").upper() == "SALEORDER":

        shipment_columns = ["saleOrderNum", "channel", "picklist", "fulfillmentTat", "shipment"]
        orders_columns = ["saleOrderNum", "shipment", "channel", "channelName", "channelId"]
        shipment_filters = process_validation_request_filters(validation_request)
        if len(shipment_filters) == 1 and shipment_filters[0].get("id") in "saleOrderCodes":
            saleOrdersCodes = shipment_filters[0].get("saleOrderCodes")
            for saleOrder in saleOrdersCodes:
                sale_order_details_request = {
                    "saleOrderCode": saleOrder
                }

                orders_response = make_unicommerce_request(tenant_code, "/data/tasks/export/data", "POST", session_id,
                                                           shipment_request_body)
                if order_response.status_code == 200:
                    order_response_json = order_response.json()
                    if order_response_json.get("successful") is True:
                        shipping_packages = order_response_json.get("shippingPackages", [])
                        for shipping_package in shipping_packages:
                            extracted_data.extend([
                                {"saleOrderNum": saleOrder, "shipment": shipping_package.get("code")}
                            ])
                    else:
                        result = f"\n{result} - No ShippingPackage found for saleOrderCode {saleOrder}"
                else:
                    result = f"\n{result} - Invalid SaleOrderCode {saleOrder}"
        else:
            shipment_request_body = build_request_body(shipment_columns, shipment_filters)
            orders_response = make_unicommerce_request(tenant_code, "/data/tasks/export/data", "POST",
                                                       shipment_request_body, headers)
            extracted_data = extract_orders_response(orders_response.json(), shipment_columns, orders_columns)

    elif validation_request.get("entity", "").upper() == "PICKLIST":

        picklist_codes = fetch_picklist_codes_from_filter(validation_request.get("filterOptions"))
        for picklist in picklist_codes:
            packlist_request_body = {
                "picklistCode": picklist
            }
            packlist_response = make_unicommerce_request(tenant_code, "/data/oms/packer/packlist/fetch", "POST",
                                                         packlist_request_body, headers)
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
            user_id=user_id,
            session_id=session_id,
            new_orders=extracted_data
        )
        result = f" Found {len(extracted_data)} orders that can be processed based on criteria."
    else:
        result = "Failure. No orders found to be process based on given criteria"

    return result


def extract_orders_response(response_data, column_names, extract_fields) -> list:
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


def process_order(order_details: dict) -> tuple[str, str]:
    """
    Simulates validating an order with an external system.
    Replace this with your actual order validation logic.
    """

    logger.info("processing order")

    if Play_Mode:
        logger.info("play mode returning sample order")
        return "[System feed] Invoices has been generated successfully, Please provide appropriate response for the user.", sampleBase64Pdf

    context = RequestContext.current()
    tenant_code = context.get("tenant_code")
    user_id = context.get("user_id")
    session_id = context.get("session_id")

    process_order_response = ""
    combined_returned_pdf = ""
    # orders = get_shipments_by_user(user_id,session_id)
    orders = order_details.get("orders");
    invoice_success_shipments = []
    invoice_failed_shipments = []
    label_failed_shipments = []
    label_success_shipments = []
    print_invoices = []
    print_invoices_labels = []
    print_labels = []

    for order in orders:
        process_order_response = process_invoice_for_order(order, print_invoices_labels, print_invoices,
                                                           invoice_success_shipments, invoice_failed_shipments)
        print(process_order_response)

    if print_invoices_labels:
        print_invoice_label_request = {
            "shippingPackageCodes": print_invoices_labels
        }
        print_invoices_labels_response = make_unicommerce_request(tenant_code,
                                                                  "/data/oms/shipment/printInvoiceAndLabel/bulk",
                                                                  "POST", session_id, print_invoice_label_request)

        if print_invoices_labels_response.status_code == 200 and "application/pdf" in print_invoices_labels_response.headers.get(
                "Content-Type"):
            # file_path = save_pdf_to_temp(print_invoices_labels_response.content,tenant_code,user_id,"invoice_label")
            combined_returned_pdf = base64.b64encode(print_invoices_labels_response.content).decode('utf-8')
            process_order_response = f"Invoices have been Successfully generated. "

    if print_invoices:
        print_invoice_request = {
            "invoiceCodes": print_invoices
        }
        print_invoice_response = make_unicommerce_request(tenant_code, "/data/oms/invoice/show/bulk", "POST",
                                                          session_id, print_invoice_request)
        if print_invoice_response.status_code == 200 and "application/pdf" in print_invoice_response.headers.get(
                "Content-Type"):
            # invoice_file_path = save_pdf_to_temp(print_invoice_response.content,tenant_code,user_id,"invoice")
            invoice_encoded = base64.b64encode(print_invoice_response.content).decode('utf-8')
            process_order_response = f"Invoices have been Successfully generated. "

            for order in orders:
                process_label_for_order_response = process_label_for_order(order, print_labels, label_success_shipments,
                                                                           label_failed_shipments)
            print_label_request = {
                "shippingPackageCodes": print_labels
            }
            print_labels_response = make_unicommerce_request(tenant_code, "/data/oms/shipment/show/bulk", "POST",
                                                             session_id, print_label_request)
            if print_labels_response.status_code == 200 and "application/pdf" in print_labels_response.headers.get(
                    "Content-Type"):
                label_encoded = base64.b64encode(print_labels_response.content).decode('utf-8')
                # label_file_path = save_pdf_to_temp(print_labels_response.content, tenant_code, user_id,"label")
                combined_returned_pdf = merge_pdfs_base64(invoice_encoded, label_encoded)
                process_order_response = f"{process_order_response} ,Successfully generated label "
            else:
                combined_returned_pdf = invoice_encoded
                process_order_response = f"{process_order_response}, But label generation failure , thus not label file but invoice only"
        else:
            process_order_response = f"Unable to process orders at the time due to internal error"

    return process_order_response, combined_returned_pdf


def merge_pdfs_base64(encoded_invoice: str, encoded_label: str) -> str:
    # Decode base64 strings to binary PDF content
    invoice_pdf = base64.b64decode(encoded_invoice)
    label_pdf = base64.b64decode(encoded_label)

    # Use BytesIO to handle in-memory binary streams
    merger = PdfMerger()
    merger.append(io.BytesIO(invoice_pdf))
    merger.append(io.BytesIO(label_pdf))

    output = io.BytesIO()
    merger.write(output)
    merger.close()

    # Encode merged PDF to base64
    merged_base64 = base64.b64encode(output.getvalue()).decode('utf-8')
    return merged_base64


def process_invoice_for_order(order, print_invoices_labels,
                              print_invoices,
                              invoice_success_shipments,
                              invoice_failed_shipments):
    user_id = context.get("user_id")
    session_id = context.get("session_id")
    access_token = context.get("access_token")
    headers = {"Authorization": f"Bearer {access_token}"}

    request_body = {
        "shippingPackageCode": order.get('shipment')
    }

    context = RequestContext.current()
    tenant_code = context.get("tenant_code")

    invoice_response = make_unicommerce_request(tenant_code, "/data/oms/invoice/create", "POST", session_id,
                                                request_body)
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
    context = RequestContext.current()
    tenant_code = context.get("tenant_code")

    user_id = context.get("user_id")
    session_id = context.get("session_id")
    access_token = context.get("access_token")
    headers = {"Authorization": f"Bearer {access_token}"}

    request_body = {
        "shippingPackageCode": order.get('shipment')
    }

    label_response = make_unicommerce_request(tenant_code, "/data/oms/shipment/provider/allocate", "POST", session_id,
                                              request_body)
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


def save_pdf_to_temp(response_content, tenant_code, user_id, type):
    time_str = datetime.now().strftime("%H%M%S")
    filename = f"{tenant_code}_{user_id}_{time_str}_{type}.pdf"
    file_path = f"/Users/virendersingh/Downloads/{filename}"

    with open(file_path, "wb") as f:
        f.write(response_content)

    return file_path


def get_current_warehouse_display_name(response: dict) -> str:
    """
    Returns displayName for currentFacilityCode, or the first facility if currentFacilityCode is null.
    """
    context = RequestContext.current()
    tenant_code = context.get("tenant_code")
    user_id = context.get("user_id")
    session_id = context.get("session_id")
    facilities = response.get("facilityDTOList", [])
    current_code = response.get("currentFacilityCode")

    if current_code:
        for facility in facilities:
            if facility.get("code") == current_code:
                return facility.get("displayName", "Unknown")

    # Fallback: return displayName of the first facility
    if facilities:
        headers = {"Authorization": f"Bearer {access_token}"}
        switch_facility_request_body = {
            "facilityCode": facilities[0].get("code")
        }
        make_unicommerce_request(tenant_code, "/data/user/switchfacility", "POST", session_id,
                                 switch_facility_request_body)
        return facilities[0].get("displayName", "Unknown")
    return "Unknown"


def switch_facility_uniware(switch_facility_request) -> str:
    context = RequestContext.current()
    tenant_code = context.get("tenant_code")
    user_id = context.get("user_id")
    session_id = context.get("session_id")

    switch_facility_response = make_unicommerce_request(tenant_code, "/data/user/switchfacility", "POST", session_id,
                                                        switch_facility_request)
    if switch_facility_response.status_code != 200:
        return "Unable to switch facility due to internal error"

    pending_orders = fetch_pending_orders_shipment()

    if len(pending_orders) > 0:
        update_user_order_mappings(
            user_id=user_id,
            session_id=session_id,
            new_orders=pending_orders
        )

    return f"Successfully switched facility. Here are the PENDING/CREATED orders for the user : {pending_orders}"


@app.post("/login")
async def authenticate_user(
        login_data: LoginRequest,
        response: Response):
    """
    Authenticates user and sets access_token in an HttpOnly cookie.
    """
    # Call OAuth API to get access_token

    tenantCode = login_data.tenantCode.lower()
    username = login_data.username
    password = login_data.password

    base_url = f"https://{tenantCode}.unicommerce.com/oauth/token"
    params = {
        "grant_type": "password",
        "client_id": "uniware-internal-client",
        "username": username,
        "password": password
    }
    try:
        oauth_response = requests.get(base_url, params=urlencode(params))
        oauth_data = oauth_response.json()

        if oauth_response.status_code != 200 or "access_token" not in oauth_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=oauth_data.get("error_description", "Invalid credentials")
            )

        access_token = oauth_data["access_token"]

        user_response = requests.get(
            f"https://{tenantCode.lower()}.unicommerce.com/data/user/facilities",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        if user_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to fetch facility information for the user"
            )

        userId = f"{username}_{tenantCode}"

        # Use RequestContext.current()
        context = RequestContext.current()
        context.set("tenant_code", tenantCode)
        context.set("user_id", userId)

        session_id = generate_session_id(userId)
        create_chat_session_auth(session_id, username, tenantCode, False, access_token)

        return {"message": "Login successful", "userId": userId, "sessionId": session_id}

    except requests.RequestException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect to OAuth server: {str(e)}"
        )


@app.post("/session/verify")
async def authenticate_user():
    """
    Authenticates user and sets access_token in an HttpOnly cookie.
    """
    # Call OAuth API to get access_token
    context = RequestContext.current()
    tenant_code = context.get("tenant_code")
    session_id = context.get("session_id")

    user_response = make_unicommerce_request(tenant_code, "/data/user/facilities", "GET", session_id, {})

    if user_response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to fetch user info"
        )

    return {"message": "Login successful"}


@app.get("/bot/session/create")
async def create_uniware_internal_chat_session_user(request: Request):
    """
    Authenticates user and sets access_token in an HttpOnly cookie.
    """
    # Call OAuth API to get access_token
    context = RequestContext.current()
    domain = request.headers.get("host")
    tenantCode = domain.split(".")[0] if domain else None
    JSessionId = request.cookies.get("JSESSIONID")
    logger.info("creating session")

    user_response = requests.get(
        f"https://{tenantCode.lower()}.unicommerce.com/data/meta",
        headers={"Cookie": f"JSESSIONID={JSessionId}"}
    )
    if user_response.status_code != 200:
        return {"successful": False, "sessionId": None}
    user_response_json = user_response.json()
    username = user_response_json.get('user').get('email')
    user_id = f"{username}_{tenantCode}"

    logger.info(f"user_id is :{user_id}")
    session_id = generate_session_id(user_id)
    try:
        create_chat_session_auth(session_id, username, tenantCode, True, JSessionId)
    except Exception as e:
        return {"successful": False, "sessionId": None}
    return {"successful": True, "sessionId": session_id, "userId": user_id, "tenantCode": tenantCode}


def extract_pure_json(response: str) -> dict:
    """
    Extracts JSON from a markdown-style code block like ```json ... ```.
    """
    if "```json" in response:
        response = response.split("```json", 1)[1]
    if "```" in response:
        response = response.split("```", 1)[0]
    return json.loads(response.strip())


handler = Mangum(app)