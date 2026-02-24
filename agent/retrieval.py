from config import Config
from utils.logger import setup_logger
import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict, Any

logger = setup_logger("RetrievalAgent")

class RetrievalAgent:
    def __init__(self):
        self.chroma_client = chromadb.PersistentClient(path=Config.VECTOR_DB_DIR)
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=Config.EMBEDDING_MODEL
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name="compliance_knowledge",
            embedding_function=self.embedding_fn
        )

    def retrieve_context(self, query: str, n_results: int = 5) -> str:
        logger.info(f"Retrieving context for query: {query[:50]}...")
        
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        if not results['documents'] or not results['documents'][0]:
            logger.warning("No relevant context found.")
            return ""
            
        context = "\n---\n".join(results['documents'][0])
        return context
