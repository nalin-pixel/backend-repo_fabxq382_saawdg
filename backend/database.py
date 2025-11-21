import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from pymongo import MongoClient
from pymongo.collection import Collection

MONGO_URL = os.getenv("DATABASE_URL", "mongodb://localhost:27017")
MONGO_DB = os.getenv("DATABASE_NAME", "eternal_flame")

client = MongoClient(MONGO_URL)
db = client[MONGO_DB]


def collection(name: str) -> Collection:
    return db[name]


def create_document(collection_name: str, data: Dict[str, Any]) -> str:
    now = datetime.utcnow()
    data["created_at"] = data.get("created_at", now)
    data["updated_at"] = now
    res = collection(collection_name).insert_one(data)
    return str(res.inserted_id)


def get_document(collection_name: str, filt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return collection(collection_name).find_one(filt)


def get_documents(collection_name: str, filt: Dict[str, Any], limit: int = 100) -> List[Dict[str, Any]]:
    return list(collection(collection_name).find(filt).limit(limit))


def update_document(collection_name: str, filt: Dict[str, Any], update: Dict[str, Any]) -> None:
    update["updated_at"] = datetime.utcnow()
    collection(collection_name).update_one(filt, {"$set": update})
