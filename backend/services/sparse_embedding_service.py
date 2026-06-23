import logging
from typing import Dict, List, Any
from fastembed import SparseTextEmbedding
from qdrant_client import models

logger = logging.getLogger("airag.sparse_embedding")

class SparseEmbeddingService:
    _model = None

    @classmethod
    def get_model(cls) -> SparseTextEmbedding:
        if cls._model is None:
            logger.info("Initializing fastembed SparseTextEmbedding model...")
            # Loads SPLADE-PP-en-v1 by default, which is very fast and efficient
            cls._model = SparseTextEmbedding()
            logger.info("fastembed SparseTextEmbedding model initialized successfully.")
        return cls._model

    @classmethod
    def get_sparse_vector(cls, text: str) -> models.SparseVector:
        """
        為單一文字生成稀疏向量。
        """
        try:
            model = cls.get_model()
            embeddings = list(model.embed([text]))
            sparse_emb = embeddings[0]
            
            return models.SparseVector(
                indices=sparse_emb.indices.tolist(),
                values=sparse_emb.values.tolist()
            )
        except Exception as e:
            logger.error(f"Failed to generate sparse embedding: {e}")
            # 回傳空向量做為安全降級防線
            return models.SparseVector(indices=[], values=[])

    @classmethod
    def get_sparse_vectors_batch(cls, texts: List[str]) -> List[models.SparseVector]:
        """
        為批次文字生成稀疏向量。
        """
        try:
            model = cls.get_model()
            embeddings = list(model.embed(texts))
            
            return [
                models.SparseVector(
                    indices=emb.indices.tolist(),
                    values=emb.values.tolist()
                )
                for emb in embeddings
            ]
        except Exception as e:
            logger.error(f"Failed to generate batch sparse embeddings: {e}")
            return [models.SparseVector(indices=[], values=[]) for _ in texts]
