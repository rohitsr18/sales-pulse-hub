import json
import os
import uuid

from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from pinecone import Pinecone, ServerlessSpec
from pinecone_text.sparse import BM25Encoder

from config.settings import (
    BM25_STATE_FILE,
    EMBED_BATCH_SIZE,
    EMBEDDING_MODEL,
    GEMINI_API_KEY,
    HASH_STORE_FILE,
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
)

_EMBEDDING_DIMENSION = 768


def _load_hashes() -> dict:
    if os.path.exists(HASH_STORE_FILE):
        with open(HASH_STORE_FILE) as f:
            return json.load(f)
    return {}


def _save_hashes(hashes: dict) -> None:
    with open(HASH_STORE_FILE, "w") as f:
        json.dump(hashes, f, indent=2)


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        google_api_key=GEMINI_API_KEY,
    )


def get_index():
    pc = Pinecone(api_key=PINECONE_API_KEY)
    if PINECONE_INDEX_NAME not in [i.name for i in pc.list_indexes()]:
        # dotproduct is required for Pinecone hybrid (dense + sparse) queries.
        pc.create_index(
            name=PINECONE_INDEX_NAME,
            dimension=_EMBEDDING_DIMENSION,
            metric="dotproduct",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
    return pc.Index(PINECONE_INDEX_NAME)


def load_bm25() -> BM25Encoder:
    bm25 = BM25Encoder()
    bm25.load(BM25_STATE_FILE)
    return bm25


def _fit_bm25(chunks: list[Document]) -> BM25Encoder:
    bm25 = BM25Encoder()
    bm25.fit([c.page_content for c in chunks])
    bm25.dump(BM25_STATE_FILE)
    return bm25


def load_to_pinecone(chunks: list[Document]) -> None:
    index = get_index()
    embeddings = get_embeddings()

    by_url: dict[str, list[Document]] = {}
    for chunk in chunks:
        by_url.setdefault(chunk.metadata["source"], []).append(chunk)

    stored = _load_hashes()
    updated = dict(stored)
    changed_urls = [
        url
        for url, url_chunks in by_url.items()
        if stored.get(url) != url_chunks[0].metadata["hash"]
    ]

    if not changed_urls:
        print("No changes detected. Pinecone is up to date.")
        if not os.path.exists(BM25_STATE_FILE):
            print("BM25 state missing. Refitting...")
            _fit_bm25(chunks)
        return

    print(f"{len(changed_urls)} page(s) changed.")

    changed_chunks: list[Document] = []
    for url in changed_urls:
        print(f"  Replacing vectors for: {url}")
        index.delete(filter={"source": url})
        changed_chunks.extend(by_url[url])
        updated[url] = by_url[url][0].metadata["hash"]

    # Refit on the full corpus so the BM25 vocabulary stays complete.
    print("Fitting BM25 on full corpus...")
    bm25 = _fit_bm25(chunks)

    texts = [c.page_content for c in changed_chunks]
    dense = embeddings.embed_documents(texts)
    sparse = bm25.encode_documents(texts)

    total = len(changed_chunks)
    for start in range(0, total, EMBED_BATCH_SIZE):
        end = start + EMBED_BATCH_SIZE
        vectors = [
            {
                "id": str(uuid.uuid4()),
                "values": dense[i],
                "sparse_values": sparse[i],
                "metadata": {
                    "source": changed_chunks[i].metadata["source"],
                    "text": changed_chunks[i].page_content,
                },
            }
            for i in range(start, min(end, total))
        ]
        index.upsert(vectors=vectors)
        print(f"  Uploaded {min(end, total)}/{total} chunks")

    # Saved last so a failed upload is retried on the next run.
    _save_hashes(updated)
    print(f"Done. {len(changed_urls)} updated, {len(by_url) - len(changed_urls)} skipped.")
