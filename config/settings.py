from dotenv import load_dotenv
import os

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "hr-policies")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")

EMPLOYEE_API_BASE_URL = os.getenv("EMPLOYEE_API_BASE_URL")
EMPLOYEE_API_KEY = os.getenv("EMPLOYEE_API_KEY")

SN_INSTANCE = os.getenv("SERVICENOW_INSTANCE")
SN_USER = os.getenv("SERVICENOW_USER")
SN_PASS = os.getenv("SERVICENOW_PASS")

SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))

CONVERSATION_ENCRYPTION_KEY = os.getenv("CONVERSATION_ENCRYPTION_KEY")
CONVERSATION_DB_FILE = os.getenv("CONVERSATION_DB_FILE", "conversations.db")

LLM_MODEL = "gemini-2.5-flash"
EMBEDDING_MODEL = "models/text-embedding-004"
RERANK_MODEL = "rerank-english-v3.0"

EMBED_BATCH_SIZE = 100
RETRIEVER_TOP_K = 10
RERANK_TOP_N = 3

# 1.0 = pure semantic, 0.0 = pure keyword
HYBRID_ALPHA = 0.7

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

HASH_STORE_FILE = "ingestion/hash_store.json"
BM25_STATE_FILE = "ingestion/bm25_state.json"
