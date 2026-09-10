import os
import sqlite3
from pathlib import Path
from typing import Annotated, Any, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import tools_condition
from langgraph.types import Command, interrupt

from rag import rag_tool
from tools import (
	buy_stock,
	calculator,
	get_current_weather,
	get_stock_price,
	save_note,
	search_tool,
)


load_dotenv()


llm = ChatGroq(
	model="openai/gpt-oss-120b",
	temperature=0.7,
)

tools = [
	search_tool,
	calculator,
	get_stock_price,
	get_current_weather,
	rag_tool,
	save_note,
	buy_stock,
]
tools_by_name = {tool.name: tool for tool in tools}
llm_with_tools = llm.bind_tools(tools)


# Add only tools that can create an external side effect, spend money,
# expose private data, or make an irreversible change.
TOOLS_REQUIRING_APPROVAL: dict[str, str] = {
	save_note.name: "This action writes a file to the local notes directory.",
	buy_stock.name: "This action simulates placing a stock purchase order.",
}


class ChatState(TypedDict):
	messages: Annotated[list[BaseMessage], add_messages]


SYSTEM_PROMPT = """
You are an intelligent agentic AI assistant operating in a LangGraph
tool-calling workflow.

Use calculator for calculations, search_tool for current web information,
get_stock_price for stock prices, get_current_weather for current weather,
rag_tool for questions about the uploaded PDF, and save_note only when the
user explicitly asks to save text to a file. Use buy_stock only when the user
explicitly requests a purchase. Before proposing a purchase, retrieve the
current stock price if it is not already available in the conversation. Always
describe buy_stock results as a simulation, never as a real brokerage trade.

Choose tools yourself and use multiple tools when necessary. Tool approval is
enforced by the application, so do not ask for permission in normal chat and
do not claim that a tool ran unless you received its result. Never fabricate
retrieved PDF information. If the PDF lacks the requested information, say so.
"""

MAX_HISTORY_MESSAGES = 8


def _requests_note_save(message: BaseMessage) -> bool:
	if not isinstance(message, HumanMessage) or not isinstance(message.content, str):
		return False

	request = message.content.lower()
	has_write_action = any(word in request for word in ("save", "write", "create"))
	has_file_target = any(word in request for word in (".txt", " note", " file"))
	return has_write_action and has_file_target


def _requests_stock_purchase(message: BaseMessage) -> bool:
	if not isinstance(message, HumanMessage) or not isinstance(message.content, str):
		return False

	request = message.content.lower()
	return any(word in request for word in ("buy", "purchase")) and any(
		word in request for word in ("stock", "share", "aapl", "msft", "nvda")
	)


def chat_node(state: ChatState):
	recent_messages = state["messages"][-MAX_HISTORY_MESSAGES:]
	latest_message = recent_messages[-1]
	latest_human_message = next(
		(message for message in reversed(recent_messages) if isinstance(message, HumanMessage)),
		None,
	)
	has_recent_stock_price = any(
		isinstance(message, ToolMessage) and message.name == get_stock_price.name
		for message in recent_messages
	)
	if _requests_note_save(latest_message):
		model = llm.bind_tools(tools, tool_choice=save_note.name)
	elif _requests_stock_purchase(latest_message):
		tool_choice = buy_stock.name if has_recent_stock_price else get_stock_price.name
		model = llm.bind_tools(tools, tool_choice=tool_choice)
	elif (
		isinstance(latest_message, ToolMessage)
		and latest_message.name == get_stock_price.name
		and latest_human_message is not None
		and _requests_stock_purchase(latest_human_message)
	):
		model = llm.bind_tools(tools, tool_choice=buy_stock.name)
	else:
		model = llm_with_tools
	response = model.invoke(
		[SystemMessage(content=SYSTEM_PROMPT), *recent_messages]
	)
	return {"messages": [response]}


def _is_approved(response: Any, tool_call_id: str) -> bool:
	"""Interpret a resume response, defaulting to rejection."""
	if response is True:
		return True

	if not isinstance(response, dict):
		return False

	approved_ids = response.get("approved_tool_call_ids", [])
	return tool_call_id in approved_ids


def tool_node(state: ChatState):
	last_message = state["messages"][-1]
	tool_calls = getattr(last_message, "tool_calls", [])
	sensitive_calls = [
		tool_call
		for tool_call in tool_calls
		if tool_call["name"] in TOOLS_REQUIRING_APPROVAL
	]

	approval_response: Any = None
	if sensitive_calls:
		approval_response = interrupt(
			{
				"type": "tool_approval",
				"tool_calls": [
					{
						"id": tool_call["id"],
						"name": tool_call["name"],
						"args": tool_call.get("args", {}),
						"reason": TOOLS_REQUIRING_APPROVAL[tool_call["name"]],
					}
					for tool_call in sensitive_calls
				],
			}
		)

	results = []
	for tool_call in tool_calls:
		tool_name = tool_call["name"]
		tool_call_id = tool_call["id"]

		if (
			tool_name in TOOLS_REQUIRING_APPROVAL
			and not _is_approved(approval_response, tool_call_id)
		):
			denial_message = (
				"The simulated purchase was not executed because the owner "
				"denied permission."
				if tool_name == buy_stock.name
				else "The user denied permission to run this tool."
			)
			results.append(
				ToolMessage(
					content=denial_message,
					tool_call_id=tool_call_id,
					name=tool_name,
				)
			)
			continue

		tool = tools_by_name.get(tool_name)
		if tool is None:
			content = f"Unknown tool: {tool_name}"
		else:
			try:
				content = str(tool.invoke(tool_call.get("args", {})))
			except Exception as error:
				content = f"Tool execution failed: {error}"

		results.append(
			ToolMessage(
				content=content,
				tool_call_id=tool_call_id,
				name=tool_name,
			)
		)

	return {"messages": results}


DATA_DIR = Path(os.getenv("APP_DATA_DIR", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "chatbot.db"
connection = sqlite3.connect(DB_PATH, check_same_thread=False)
checkpoint = SqliteSaver(connection)

graph = StateGraph(ChatState)
graph.add_node("chat", chat_node)
graph.add_node("tools", tool_node)
graph.add_edge(START, "chat")
graph.add_conditional_edges("chat", tools_condition)
graph.add_edge("tools", "chat")

chatbot = graph.compile(checkpointer=checkpoint)


def get_pending_approval(config: dict) -> dict[str, Any] | None:
	"""Return the current approval request for a conversation, if any."""
	state = chatbot.get_state(config)

	for task in getattr(state, "tasks", ()):
		for pending_interrupt in getattr(task, "interrupts", ()):
			value = pending_interrupt.value
			if isinstance(value, dict) and value.get("type") == "tool_approval":
				return value

	return None


def resume_with_approval(
	config: dict,
	approved_tool_call_ids: list[str],
):
	"""Resume the paused graph with the user's explicit decisions."""
	return chatbot.invoke(
		Command(
			resume={
				"approved_tool_call_ids": approved_tool_call_ids,
			}
		),
		config=config,
	)


def get_all_threads():
	"""Return saved conversation thread IDs, most recently updated first."""
	latest_checkpoint_by_thread = {}

	try:
		for checkpoint_tuple in checkpoint.list(None):
			configurable = checkpoint_tuple.config.get("configurable", {})
			thread_id = configurable.get("thread_id")
			checkpoint_id = configurable.get("checkpoint_id", "")
			if (
				thread_id
				and checkpoint_id > latest_checkpoint_by_thread.get(thread_id, "")
			):
				latest_checkpoint_by_thread[thread_id] = checkpoint_id
	except Exception:
		pass

	return sorted(
		latest_checkpoint_by_thread,
		key=latest_checkpoint_by_thread.get,
		reverse=True,
	)
