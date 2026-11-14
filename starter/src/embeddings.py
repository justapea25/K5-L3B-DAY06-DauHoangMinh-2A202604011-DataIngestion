"""Real embedding model: intfloat/multilingual-e5-small, run locally (CPU)."""
from __future__ import annotations

from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class E5Embedder:
    """multilingual-e5 embeddings (384-d for -small), L2-normalized.

    E5 was trained with role prefixes: documents get "passage: ", queries get
    "query: ". Max 512 tokens; the longest strategy-B chunk is ~400 tokens, so
    nothing is truncated. Runs on CPU because torch MPS crashes on this macOS.
    Fails loudly if the model cannot load: no mock fallback.
    """

    QUERY_PREFIX = "query: "
    DOC_PREFIX = "passage: "

    def __init__(self, model_name: str = "intfloat/multilingual-e5-small",
                 batch_size: int = 32, device: str = "cpu") -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name, device=device)
        self.dimensions = self.model.get_sentence_embedding_dimension()

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, batch_size=self.batch_size,
                                    normalize_embeddings=True,
                                    show_progress_bar=len(texts) > 64,
                                    convert_to_numpy=True)
        return vectors.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self.DOC_PREFIX + t for t in texts]) if texts else []

    def embed_query(self, question: str) -> list[float]:
        return self._encode([self.QUERY_PREFIX + question])[0]

    def info(self) -> dict:
        import sentence_transformers
        import torch
        return {"provider": "local (sentence-transformers)", "model": self.model_name,
                "dimensions": self.dimensions, "normalize": True,
                "query_prefix": self.QUERY_PREFIX, "doc_prefix": self.DOC_PREFIX,
                "max_seq_length": self.model.max_seq_length, "device": self.device,
                "torch": torch.__version__,
                "sentence_transformers": sentence_transformers.__version__, "cost_usd": 0}
