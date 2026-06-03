import os
import time
import uuid
from langchain_chroma import Chroma 
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

CHROMA_DIR = "vector_db"
COLLECTION_NAME = "meeting_transcript"
EMBEDDING_MODEL  = "all-MiniLM-L6-v2"

def log_vector(message: str):
    print(f"[vector_store] {message}", flush=True)

def _new_run_chroma_dir(run_id: str | None = None) -> str:
    run_dir = os.path.join(CHROMA_DIR, "runs", run_id or uuid.uuid4().hex)
    os.makedirs(run_dir, exist_ok=True)
    log_vector(f"Using Chroma persist directory: {run_dir}")
    return run_dir

def get_embeddings():
    log_vector(f"Loading embedding model: {EMBEDDING_MODEL}")
    return HuggingFaceEmbeddings(
        model_name = EMBEDDING_MODEL,
        model_kwargs = {"device" : 'cpu'}
    )
 
def build_vector_store(transcript : str, run_id: str | None = None)->Chroma:
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
    log_vector(f"Created {len(docs)} Chroma document(s)")

    embeddings = get_embeddings()
    persist_directory = _new_run_chroma_dir(run_id)
    log_vector("Starting Chroma.from_documents() embedding + persist step")
    vector_store = Chroma.from_documents(
        documents= docs,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=persist_directory
    )
    log_vector(f"Chroma vector store built in {time.time() - started_at:.2f}s")

    return vector_store



def load_vector_store(persist_directory: str = CHROMA_DIR) ->Chroma:
    log_vector(f"Loading vector store from: {persist_directory}")
    embeddings = get_embeddings()
    vector_store = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function= embeddings,
        persist_directory=persist_directory
    )

    return vector_store

def get_retriever(vector_store : Chroma, k :int = 4):
    log_vector(f"Creating retriever with top_k={k}")
    return vector_store.as_retriever(
        search_type = 'similarity',
        search_kwargs = {"k":k}
    )
