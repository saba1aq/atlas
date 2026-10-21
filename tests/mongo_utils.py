from __future__ import annotations

import os

import pytest

MONGO_URL = os.environ.get("ATLAS_TEST_MONGO_URL", "mongodb://127.0.0.1:27017")


def mongo_available() -> bool:
    try:
        from pymongo import MongoClient

        MongoClient(MONGO_URL, serverSelectionTimeoutMS=800).admin.command("ping")
        return True
    except Exception:
        return False


requires_mongo = pytest.mark.skipif(not mongo_available(), reason="MongoDB is not reachable")
