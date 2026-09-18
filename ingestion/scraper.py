import asyncio
import hashlib

import aiohttp
from bs4 import BeautifulSoup
from langchain_core.documents import Document

_NOISE_TAGS = ["nav", "footer", "header", "script", "style", "aside", "form"]


async def fetch_page(session: aiohttp.ClientSession, url: str) -> Document | None:
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with session.get(url, timeout=timeout) as resp:
            if resp.status != 200:
                print(f"  Skipped {url} (HTTP {resp.status})")
                return None
            html = await resp.text()
    except Exception as exc:
        print(f"  Failed {url}: {exc}")
        return None

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    if not text:
        return None

    content_hash = hashlib.sha256(text.encode()).hexdigest()
    return Document(
        page_content=text,
        metadata={"source": url, "hash": content_hash},
    )


async def _scrape_all(urls: list[str]) -> list[Document]:
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[fetch_page(session, url) for url in urls])
    return [doc for doc in results if doc is not None]


def scrape_hr_website(urls: list[str]) -> list[Document]:
    return asyncio.run(_scrape_all(urls))
