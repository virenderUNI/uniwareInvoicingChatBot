import os

GOOGLE_API_KEY = "AIzaSyDaGjf4mghVgowHZQ93lGauI7cqq_kSDBw" #or define directly
if not GOOGLE_API_KEY:
    raise ValueError("Please set the GOOGLE_API_KEY environment variable")
MONGO_URI = "mongodb://mongo.appstaging-in.unicommerce.infra:27017" # or define directly
DATABASE_NAME = "uniwareChat"
COLLECTION_NAME = "chat_history"