import os
import json
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from config import Config
from utils.logger import setup_logger
from typing import List, Dict, Any

logger = setup_logger("RetrievalAgent")

class RetrievalAgent:
    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.index_path = os.path.join(Config.VECTOR_DB_DIR, "index.faiss")
        self.meta_path = os.path.join(Config.VECTOR_DB_DIR, "metadata.json")
        
        # Load embedding model
        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        
        # Load FAISS index and metadata if they exist
        self.index = None
        self.metadata_store = {}
        
        if os.path.exists(self.index_path) and os.path.exists(self.meta_path):
            try:
                self.index = faiss.read_index(self.index_path)
                with open(self.meta_path, 'r') as f:
                    self.metadata_store = json.load(f)
            except Exception as e:
                logger.error(f"Error loading vector DB: {e}")

    def retrieve_context(self, query: str, n_results: int = 5) -> str:
        logger.info(f"Retrieving context for query: {query[:50]}...")
        
        if not self.index or self.index.ntotal == 0 or not self.metadata_store:
            logger.warning("Vector DB is empty or not loaded.")
            return ""
            
        # Generate query embedding
        query_embedding = self.embedding_model.encode([query])
        query_embedding = np.array(query_embedding).astype('float32')
        
        # Search FAISS
        distances, indices = self.index.search(query_embedding, n_results)
        
        documents = []
        for idx in indices[0]:
            if idx != -1:  # -1 means no result found
                str_idx = str(idx)
                if str_idx in self.metadata_store:
                    documents.append(self.metadata_store[str_idx]["text"])
                    
        if not documents:
            logger.warning("No relevant context found.")
            return ""
            
        context = "\n---\n".join(documents)
        return context
