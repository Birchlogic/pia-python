import chromadb
from chromadb.utils import embedding_functions
from config import Config
from utils.logger import setup_logger
from typing import List, Dict, Any

logger = setup_logger("KBBuilder")

class KBBuilder:
    def __init__(self):
        self.chroma_client = chromadb.PersistentClient(path=Config.VECTOR_DB_DIR)
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=Config.EMBEDDING_MODEL
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name="compliance_knowledge",
            embedding_function=self.embedding_fn
        )

    def add_transcript(self, transcript_id: str, content: str, metadata: Dict[str, Any]):
        logger.info(f"Adding transcript {transcript_id} to vector DB")
        
        # Simple chunking
        chunks = self._chunk_text(content)
        
        ids = [f"{transcript_id}_{i}" for i in range(len(chunks))]
        metadatas = [metadata] * len(chunks)
        
        self.collection.add(
            documents=chunks,
            ids=ids,
            metadatas=metadatas
        )

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
