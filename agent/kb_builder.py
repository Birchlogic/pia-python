import os
import json
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from config import Config
from utils.logger import setup_logger
from typing import List, Dict, Any

logger = setup_logger("KBBuilder")

class KBBuilder:
    def __init__(self):
        self.index_path = os.path.join(Config.VECTOR_DB_DIR, "index.faiss")
        self.meta_path = os.path.join(Config.VECTOR_DB_DIR, "metadata.json")
        
        # Ensure directory exists
        os.makedirs(Config.VECTOR_DB_DIR, exist_ok=True)
        
        # Load embedding model
        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        self.dimension = self.embedding_model.get_sentence_embedding_dimension()
        
        # Load or create FAISS index
        if os.path.exists(self.index_path):
            self.index = faiss.read_index(self.index_path)
        else:
            self.index = faiss.IndexFlatL2(self.dimension)
            
        # Load or create metadata store
        if os.path.exists(self.meta_path):
            with open(self.meta_path, 'r') as f:
                self.metadata_store = json.load(f)
        else:
            self.metadata_store = {}

    def _save(self):
        faiss.write_index(self.index, self.index_path)
        with open(self.meta_path, 'w') as f:
            json.dump(self.metadata_store, f)

    def add_transcript(self, transcript_id: str, content: str, metadata: Dict[str, Any]):
        logger.info(f"Adding transcript {transcript_id} to vector DB")
        
        # Simple chunking
        chunks = self._chunk_text(content)
        if not chunks:
            return
            
        # Generate embeddings
        embeddings = self.embedding_model.encode(chunks)
        embeddings = np.array(embeddings).astype('float32')
        
        # Get start index for new items
        start_idx = self.index.ntotal
        
        # Add to FAISS
        self.index.add(embeddings)
        
        # Add to metadata store
        for i, chunk in enumerate(chunks):
            idx = str(start_idx + i)
            doc_id = f"{transcript_id}_{i}"
            self.metadata_store[idx] = {
                "id": doc_id,
                "text": chunk,
                "metadata": metadata
            }
            
        self._save()

    def _chunk_text(self, text: str) -> List[str]:
        # Basic sliding window chunking
        words = text.split()
        chunks = []
        for i in range(0, len(words), Config.CHUNK_SIZE - Config.CHUNK_OVERLAP):
            chunk = " ".join(words[i:i + Config.CHUNK_SIZE])
            chunks.append(chunk)
            if i + Config.CHUNK_SIZE >= len(words):
                break
        return chunks

    def add_generated_report(self, report_id: str, content: str, metadata: Dict[str, Any]):
        logger.info(f"Adding generated report {report_id} to vector DB for learning")
        metadata["type"] = "generated_report"
        self.add_transcript(report_id, content, metadata)
