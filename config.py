import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    DATABASE_URL = os.getenv("DATABASE_URL")
    PAYLOAD_TOKEN = os.getenv("PAYLOAD_TOKEN")
    
    # Path settings
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    VECTOR_DB_DIR = os.path.join(DATA_DIR, "vectors")
    REPORTS_DIR = os.path.join(DATA_DIR, "reports")
    EXAMPLE_INPUT_DIR = os.path.join(BASE_DIR, "example_input")
    
    # Model settings
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"
    CLAUDE_MODEL = "claude-3-5-sonnet-20240620"
    
    # RAG settings
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 200
    
    @classmethod
    def validate(cls):
        if not cls.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not found in environment variables.")
        
        # Ensure directories exist
        os.makedirs(cls.VECTOR_DB_DIR, exist_ok=True)
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
