import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

class Config:
    DATABASE_URL = os.getenv("DATABASE_URL")
    PAYLOAD_TOKEN = os.getenv("PAYLOAD_TOKEN")
    
    # Path settings
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    VECTOR_DB_DIR = os.path.join(DATA_DIR, "vectors")
    REPORTS_DIR = os.path.join(DATA_DIR, "reports")
    EXAMPLE_INPUT_DIR = os.path.join(BASE_DIR, "example_input")
    
    # RAG settings
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 200
    
    @classmethod
    def ensure_dirs(cls):
        """Ensure required directories exist."""
        os.makedirs(cls.VECTOR_DB_DIR, exist_ok=True)
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
