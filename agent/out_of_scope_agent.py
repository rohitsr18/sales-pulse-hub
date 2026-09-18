from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from agent.prompts import OUT_OF_SCOPE_PROMPT
from config.settings import GEMINI_API_KEY, LLM_MODEL


def create_out_of_scope_agent():
    llm = ChatGoogleGenerativeAI(
        model=LLM_MODEL,
        google_api_key=GEMINI_API_KEY,
        temperature=0.1,
        max_output_tokens=256,
    )
    system = SystemMessage(content=OUT_OF_SCOPE_PROMPT)

    def node(state: dict) -> dict:
        return {"messages": [llm.invoke([system] + state["messages"])]}

    return node
