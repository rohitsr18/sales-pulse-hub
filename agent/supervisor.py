from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from agent.prompts import SUPERVISOR_PROMPT
from config.settings import GEMINI_API_KEY, LLM_MODEL


class RouteDecision(BaseModel):
    next_agent: Literal["policy", "ticketing", "out_of_scope", "end"] = Field(
        description="The single destination that should handle this request."
    )


def create_supervisor(employee_no: str):
    # temperature=0 keeps routing deterministic.
    llm = ChatGoogleGenerativeAI(
        model=LLM_MODEL,
        google_api_key=GEMINI_API_KEY,
        temperature=0,
    )
    router = llm.with_structured_output(RouteDecision)
    system = SystemMessage(content=SUPERVISOR_PROMPT.format(employee_no=employee_no))

    def supervisor_node(state: dict) -> dict:
        try:
            decision = router.invoke([system] + state["messages"])
            next_agent = decision.next_agent
        except Exception:
            next_agent = "end"
        return {"next_agent": next_agent}

    return supervisor_node
