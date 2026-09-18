from agent.prompts import POLICY_AGENT_PROMPT
from agent.tool_agent import build_tool_agent
from tools.policy_search import search_hr_policy


def create_policy_agent():
    return build_tool_agent(POLICY_AGENT_PROMPT, [search_hr_policy])
