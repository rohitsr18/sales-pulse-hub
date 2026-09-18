import cohere
from langchain_core.tools import tool

from config.settings import (
    COHERE_API_KEY,
    HYBRID_ALPHA,
    RERANK_MODEL,
    RERANK_TOP_N,
    RETRIEVER_TOP_K,
)
from ingestion.pinecone_loader import get_embeddings, get_index, load_bm25


def _hybrid_search_and_rerank(query: str) -> list[dict]:
    dense = get_embeddings().embed_query(query)
    sparse = load_bm25().encode_queries(query)

    response = get_index().query(
        vector=dense,
        sparse_vector=sparse,
        alpha=HYBRID_ALPHA,
        top_k=RETRIEVER_TOP_K,
        include_metadata=True,
    )
    matches = response.get("matches", [])
    if not matches:
        return []

    documents = [m["metadata"]["text"] for m in matches]
    reranked = cohere.Client(COHERE_API_KEY).rerank(
        query=query,
        documents=documents,
        model=RERANK_MODEL,
        top_n=min(RERANK_TOP_N, len(documents)),
    )

    return [
        {
            "text": documents[r.index],
            "source": matches[r.index]["metadata"].get("source", "unknown"),
            "score": r.relevance_score,
        }
        for r in reranked.results
    ]


@tool
def search_hr_policy(query: str) -> str:
    """Search the company HR policy knowledge base to answer an employee's question."""
    try:
        results = _hybrid_search_and_rerank(query)
    except Exception as exc:
        return f"Policy search is unavailable right now: {exc}"

    if not results:
        return "No relevant HR policy found."

    return "\n\n---\n\n".join(
        f"Source: {r['source']}\nRelevance: {r['score']:.3f}\n\n{r['text']}"
        for r in results
    )
