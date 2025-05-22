import os

GOOGLE_API_KEY = "AIzaSyCXYYOnXpSJaL9_nYYQ-ljpV6_QVBlNmPA"  #or define directly
if not GOOGLE_API_KEY:
    raise ValueError("Please set the GOOGLE_API_KEY environment variable")
MONGO_URI = "mongodb://localhost:27017" # or define directly
DATABASE_NAME = "uniwareChat"
COLLECTION_NAME = "chat_history"