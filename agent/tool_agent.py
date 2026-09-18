from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_google_genai import ChatGoogleGenerativeAI

from config.settings import GEMINI_API_KEY, LLM_MODEL

MAX_TOOL_ITERATIONS = 5


def build_tool_agent(system_prompt: str, tools: list[BaseTool]):
    """Returns a LangGraph node that runs its own reason/act loop over the given tools."""
    llm = ChatGoogleGenerativeAI(
        model=LLM_MODEL,
        google_api_key=GEMINI_API_KEY,
        temperature=0.1,
        max_output_tokens=1024,
    ).bind_tools(tools)

    tools_by_name = {t.name: t for t in tools}
    system = SystemMessage(content=system_prompt)

    def node(state: dict) -> dict:
        history: list[BaseMessage] = list(state["messages"])
        produced: list[BaseMessage] = []

        for _ in range(MAX_TOOL_ITERATIONS):
            response = llm.invoke([system] + history)
            history.append(response)
            produced.append(response)

            if not response.tool_calls:
                return {"messages": produced}

            for call in response.tool_calls:
                tool = tools_by_name[call["name"]]
                try:
                    result = tool.invoke(call["args"])
                except Exception as exc:
                    result = f"Tool failed: {exc}"
                message = ToolMessage(content=str(result), tool_call_id=call["id"])
                history.append(message)
                produced.append(message)

        return {"messages": produced}

    return node
