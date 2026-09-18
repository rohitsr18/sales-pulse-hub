import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import END, StateGraph

from agent.out_of_scope_agent import create_out_of_scope_agent
from agent.policy_agent import create_policy_agent
from agent.supervisor import create_supervisor
from agent.ticketing_agent import create_ticketing_agent
from auth.conversation_store import build_checkpointer
from auth.session_manager import Session


class MultiAgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    employee_no: str
    next_agent: str


_ROUTES = {
    "policy": "policy_agent",
    "ticketing": "ticketing_agent",
    "out_of_scope": "out_of_scope_agent",
    "end": END,
}


def build_agent(session: Session, checkpointer=None):
    graph = StateGraph(MultiAgentState)

    graph.add_node("supervisor", create_supervisor(session.employee_no))
    graph.add_node("policy_agent", create_policy_agent())
    graph.add_node("ticketing_agent", create_ticketing_agent())
    graph.add_node("out_of_scope_agent", create_out_of_scope_agent())

    graph.set_entry_point("supervisor")
    graph.add_conditional_edges("supervisor", lambda s: s["next_agent"], _ROUTES)

    for specialist in ("policy_agent", "ticketing_agent", "out_of_scope_agent"):
        graph.add_edge(specialist, "supervisor")

    return graph.compile(checkpointer=checkpointer or build_checkpointer())
