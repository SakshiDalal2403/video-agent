import os
import time
import uuid
import requests
from langchain_pinecone import PineconeVectorStore
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "video-agent")
EMBEDDING_MODEL  = "mistral-embed"
MISTRAL_EMBEDDINGS_URL = "https://api.mistral.ai/v1/embeddings"
EMBEDDING_BATCH_SIZE = 64

def log_vector(message: str):
    print(f"[vector_store] {message}", flush=True)

class MistralAPIEmbeddings(Embeddings):
    def __init__(self):
        self.api_key = os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            raise RuntimeError("MISTRAL_API_KEY is not set in environment / .env")

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = requests.post(
            MISTRAL_EMBEDDINGS_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={"model": EMBEDDING_MODEL, "input": texts},
            timeout=120,
        )
        response.raise_for_status()
        return [item["embedding"] for item in response.json()["data"]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            embeddings.extend(self._embed_batch(texts[start:start + EMBEDDING_BATCH_SIZE]))
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

def get_embeddings():
    log_vector(f"Using Mistral embedding API model: {EMBEDDING_MODEL}")
    return MistralAPIEmbeddings()
 
def build_vector_store(transcript : str, run_id: str | None = None) -> PineconeVectorStore:
    started_at = time.time()
    log_vector(f"Building vector store for transcript length: {len(transcript)} characters")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size = 500,
        chunk_overlap = 50
    )
    chunks = splitter.split_text(transcript)
    log_vector(f"Split transcript into {len(chunks)} vector chunk(s)")

    docs = [
        Document(page_content=chunk, metadata = {'chunk_index' : i})
        for i,chunk in enumerate(chunks)
    ]
    log_vector(f"Created {len(docs)} document(s)")

    embeddings = get_embeddings()
    namespace = run_id or uuid.uuid4().hex
    log_vector(f"Starting PineconeVectorStore.from_documents() with namespace {namespace}")
    vector_store = PineconeVectorStore.from_documents(
        documents=docs,
        embedding=embeddings,
        index_name=PINECONE_INDEX_NAME,
        namespace=namespace
    )
    log_vector(f"Pinecone vector store built in {time.time() - started_at:.2f}s")

    return vector_store

def load_vector_store(run_id: str) -> PineconeVectorStore:
    log_vector(f"Loading Pinecone vector store from namespace: {run_id}")
    embeddings = get_embeddings()
    vector_store = PineconeVectorStore(
        index_name=PINECONE_INDEX_NAME,
        embedding=embeddings,
        namespace=run_id
    )

    return vector_store

def get_retriever(vector_store : PineconeVectorStore, k :int = 4):
    log_vector(f"Creating retriever with top_k={k}")
    return vector_store.as_retriever(
        search_type = 'similarity',
        search_kwargs = {"k":k}
    )
