from pymongo import MongoClient
from config import MONGO_URI, DATABASE_NAME, COLLECTION_NAME
from typing import List, Dict, Optional
import datetime
import uuid

def get_mongo_client() -> MongoClient:
    """Returns a MongoClient instance."""
    return MongoClient(MONGO_URI)

def get_database(client: MongoClient):
    """Returns the MongoDB database."""
    return client[DATABASE_NAME]

def get_collection(database):
    """Returns the MongoDB collection for chat history."""
    return database[COLLECTION_NAME]

def fetch_chat_history(user_id: str) -> Dict:
    """
    Fetches the chat history from MongoDB for a given user.
    ... (rest of your fetch_chat_history function)
    """
    client = get_mongo_client()
    db = get_database(client)
    collection = get_collection(db)
    history = collection.find_one({"user_id": user_id})
    client.close()
    return history

def store_user_context(user_id: str, message: str, role: str, metadata: Optional[dict] = None):


    client = get_mongo_client()
    db = get_database(client)
    collection = db["user_chat_context"]

    message_data = {
        "role": role,
        "message": message,
        "timestamp": datetime.datetime.utcnow(),
        "metadata": metadata,
    }

    # Upsert the document and push the new message to the messages array
    collection.update_one(
        {"user_id": user_id},
        {
            "$push": {"messages": message_data},
            "$setOnInsert": {"user_id": user_id}
        },
        upsert=True
    )

    client.close()

def store_message_metadata(user_id: str, message: str, role: str, metadata: Optional[dict] = None):


    client = get_mongo_client()
    db = get_database(client)
    collection = get_collection(db)

    message_data = {
        "role": role,
        "message": message,
        "timestamp": datetime.datetime.utcnow(),
        "metadata": metadata,
    }

    # Upsert the document and push the new message to the messages array
    collection.update_one(
        {"user_id": user_id},
        {
            "$push": {"messages_metadata": message_data},
            "$setOnInsert": {"user_id": user_id}
        },
        upsert=True
    )

    client.close()


def store_message(user_id: str, message: str, role: str, metadata: Optional[dict] = None):

    client = get_mongo_client()
    db = get_database(client)
    collection = get_collection(db)

    message_data = {
        "role": role,
        "message": message,
        "timestamp": datetime.datetime.utcnow(),
        "metadata": metadata,
    }

    # Upsert the document and push the new message to the messages array
    collection.update_one(
        {"user_id": user_id},
        {
            "$push": {"messages": message_data},
            "$setOnInsert": {"user_id": user_id}
        },
        upsert=True
    )

    client.close()


def update_user_order_mappings(
        user_id: str,
        new_orders: List[Dict],
) -> None:

    client = get_mongo_client()
    db = get_database(client)
    collection = get_collection(db)

    if not new_orders:
        return

    update_data = {
        "$set": {"process_orders_data": new_orders}
    }

    collection.update_one(
        {"user_id": user_id},
        update_data,
    )
    client.close()


def archive_processed_orders_data(user_id: str):
    client = get_mongo_client()
    db = get_database(client)

    source_collection = db["chat_history"]
    archive_collection = db["archived_chat_history"]

    # Fetch current user document
    document = source_collection.find_one({"user_id": user_id})
    if not document:
        client.close()
        return

    orders_to_archive = document.get("process_orders_data", [])

    # Build push update
    archive_update = {}

    if orders_to_archive:
        archive_update.setdefault("$push", {})["process_orders_data"] = {"$each": orders_to_archive}

    if archive_update:
        archive_collection.update_one(
            {"user_id": user_id},
            archive_update,
            upsert=True
        )

    source_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "process_orders_data": [],
            }
        }
    )

    client.close()

def archive_user_data(user_id: str,is_initialisation: bool):
    client = get_mongo_client()
    db = get_database(client)

    source_collection = db["chat_history"]
    archive_collection = db["archived_chat_history"]

    # Fetch current user document
    document = source_collection.find_one({"user_id": user_id})
    if not document:
        client.close()
        return

    all_messages = document.get("messages", [])
    orders_to_archive = document.get("process_orders_data", [])
    messages_metadata = document.get("messages_metadata", [])

    if is_initialisation is True:
        messages_to_archive = all_messages
        messages_to_keep = []

    else:
        if len(all_messages) > 10:
            messages_to_archive = all_messages[:-10]
            messages_to_keep = all_messages[-10:]
        else:
            messages_to_archive = []
            messages_to_keep = all_messages

    # Build push update
    archive_update = {}
    if messages_to_archive:
        archive_update.setdefault("$push", {})["messages"] = {"$each": messages_to_archive}
    if orders_to_archive and is_initialisation is True:
        archive_update.setdefault("$push", {})["process_orders_data"] = {"$each": orders_to_archive}
    if messages_metadata:
        archive_update.setdefault("$set", {})["message_metadata"] = messages_metadata

    if archive_update:
        archive_collection.update_one(
            {"user_id": user_id},
            archive_update,
            upsert=True
        )

    if is_initialisation is True:
        messages_metadata = []
        orders_to_archive = []

    source_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "messages": messages_to_keep,
                "process_orders_data": orders_to_archive,
                "messages_metadata" : messages_metadata
            }
        }
    )

    client.close()



def get_shipments_by_user(
        user_id: str,
) -> List[Dict]:

    client = get_mongo_client()
    db = get_database(client)
    collection = get_collection(db)
    # Query MongoDB
    existing_chat = collection.find_one(
        {"user_id": user_id}
    )

    user_order_data = existing_chat.get("process_orders_data")
    if not user_order_data:
        return []

    return user_order_data
