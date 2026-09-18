from agent.prompts import TICKETING_AGENT_PROMPT
from agent.tool_agent import build_tool_agent
from tools.servicenow import raise_servicenow_incident


def create_ticketing_agent():
    return build_tool_agent(TICKETING_AGENT_PROMPT, [raise_servicenow_incident])
