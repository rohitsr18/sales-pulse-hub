import sys
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage

from agent.hr_agent import build_agent
from auth.conversation_store import (
    ChatRegistry,
    build_checkpointer,
    connect_conversation_db,
)
from auth.session_manager import login, require_session
from ingestion.chunker import chunk_documents
from ingestion.pii_scrubber import scrub_documents
from ingestion.pinecone_loader import load_to_pinecone
from ingestion.scraper import scrape_hr_website

HR_POLICY_URLS = [
    "https://yourcompany.com/hr/leave-policy",
    "https://yourcompany.com/hr/benefits",
]


def ingest_policies() -> None:
    print(f"Scraping {len(HR_POLICY_URLS)} pages...")
    docs = scrape_hr_website(HR_POLICY_URLS)
    if not docs:
        print("No pages were scraped. Check HR_POLICY_URLS and network access.")
        return

    print(f"Scraped {len(docs)} pages. Masking PII...")
    docs = scrub_documents(docs)

    chunks = chunk_documents(docs)
    print(f"{len(chunks)} chunks ready. Checking for changes...")
    load_to_pinecone(chunks)


def _last_reply(messages: list) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content:
            return message.content
    return "No response generated."


def _new_chat_config(chat_id: str) -> dict:
    return {"configurable": {"thread_id": chat_id}}


def _print_chats(chats: list) -> None:
    if not chats:
        print("\n  No saved chats yet.\n")
        return
    print("\n  Saved chats:")
    for i, chat in enumerate(chats, 1):
        when = datetime.fromtimestamp(chat.updated_at).strftime("%d %b %H:%M")
        print(f"    [{i}] {chat.title}  ({when})")
    print()


def _print_help() -> None:
    print("\n  Commands:")
    print("    /new            start a new chat")
    print("    /chats          list your saved chats")
    print("    /open <n>       resume saved chat number n")
    print("    /delete <n>     permanently delete saved chat number n")
    print("    /help           show this list")
    print("    exit            quit\n")


def run_agent() -> None:
    session = login()

    conn = connect_conversation_db()
    checkpointer = build_checkpointer(conn)
    registry = ChatRegistry(conn)
    agent = build_agent(session, checkpointer=checkpointer)

    chat_id = registry.create(session.employee_no)
    config = _new_chat_config(chat_id)
    is_first_message = True

    print("HR Agent ready. Type /help for commands.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        lowered = user_input.lower()

        if lowered in ("exit", "quit"):
            break

        if lowered in ("/help", "help"):
            _print_help()
            continue

        if lowered in ("/new", "new"):
            chat_id = registry.create(session.employee_no)
            config = _new_chat_config(chat_id)
            is_first_message = True
            print("\n  Started a new chat.\n")
            continue

        if lowered in ("/chats", "chats"):
            _print_chats(registry.list(session.employee_no))
            continue

        if lowered.startswith(("/open", "/delete")):
            command, _, arg = user_input.partition(" ")
            chats = registry.list(session.employee_no)
            try:
                target = chats[int(arg.strip()) - 1]
            except (ValueError, IndexError):
                print(f"\n  Usage: {command} <number from /chats>\n")
                continue

            if command.lower() == "/open":
                chat_id = target.chat_id
                config = _new_chat_config(chat_id)
                is_first_message = False
                print(f"\n  Resumed: {target.title}\n")
            else:
                confirm = input(f"  Permanently delete '{target.title}'? (yes/no): ")
                if confirm.strip().lower() not in ("yes", "y"):
                    print("\n  Cancelled.\n")
                    continue
                registry.delete(target.chat_id, session.employee_no, checkpointer)
                print("\n  Chat deleted.\n")
                if target.chat_id == chat_id:
                    chat_id = registry.create(session.employee_no)
                    config = _new_chat_config(chat_id)
                    is_first_message = True
                    print("  Started a new chat.\n")
            continue

        session = require_session()
        result = agent.invoke(
            {
                "messages": [HumanMessage(content=user_input)],
                "employee_no": session.employee_no,
                "next_agent": "",
            },
            config=config,
        )
        registry.touch(chat_id, user_input if is_first_message else None)
        is_first_message = False
        print(f"\nHR Agent: {_last_reply(result['messages'])}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "ingest":
        ingest_policies()
    else:
        run_agent()
