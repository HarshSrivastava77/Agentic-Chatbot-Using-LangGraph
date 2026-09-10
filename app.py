import json
import tempfile
import uuid
from pathlib import Path

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agentic_hitl import (
    chatbot,
    get_all_threads,
    get_pending_approval,
    resume_with_approval,
)
from rag import ingest_rag_document


st.set_page_config(
    page_title="Agentic workspace",
    page_icon=":material/neurology:",
    layout="centered",
    initial_sidebar_state="auto",
)

st.html(
    """
    <style>
    :root {
        --workspace-glow: color-mix(in srgb, var(--st-primary-color) 8%, transparent);
    }

    [data-testid="stAppViewContainer"] {
        background-image:
            linear-gradient(135deg, var(--workspace-glow), transparent 28%),
            linear-gradient(315deg, color-mix(in srgb, var(--st-link-color) 5%, transparent), transparent 24%);
        background-attachment: fixed;
    }

    [data-testid="stMainBlockContainer"] {
        max-width: 860px;
        padding-top: 2.25rem;
        padding-bottom: 7.5rem;
    }

    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.55rem;
    }

    [data-testid="stSidebar"] button {
        text-align: left;
        justify-content: flex-start;
    }

    [data-testid="stChatMessage"] {
        animation: message-enter 220ms ease-out both;
        border-radius: 8px;
        padding: 1rem 1.1rem;
    }

    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        background: color-mix(in srgb, var(--st-secondary-background-color) 72%, transparent);
        border: 1px solid color-mix(in srgb, var(--st-border-color) 78%, transparent);
    }

    [data-testid="stChatInput"] {
        border-radius: 8px;
        box-shadow: 0 12px 32px color-mix(in srgb, var(--st-text-color) 10%, transparent);
    }

    .workspace-hero {
        min-height: 38vh;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
        padding: 2rem 0 1.25rem;
    }

    .workspace-mark {
        width: 42px;
        height: 42px;
        display: grid;
        place-items: center;
        margin-bottom: 1.1rem;
        border: 1px solid var(--st-border-color);
        border-radius: 8px;
        color: var(--st-primary-color);
        background: var(--st-secondary-background-color);
        box-shadow: 0 10px 28px var(--workspace-glow);
        font-size: 1.35rem;
        font-weight: 700;
    }

    .workspace-hero h1 {
        max-width: 660px;
        margin: 0 0 0.75rem;
        font-size: 3rem;
        line-height: 1.08;
        letter-spacing: 0;
    }

    .workspace-hero p {
        max-width: 610px;
        margin: 0;
        color: color-mix(in srgb, var(--st-text-color) 68%, transparent);
        font-size: 1.02rem;
        line-height: 1.7;
    }

    .st-key-approval_card {
        border-left: 3px solid var(--st-primary-color) !important;
        box-shadow: 0 12px 32px color-mix(in srgb, var(--st-text-color) 7%, transparent);
    }

    @keyframes message-enter {
        from { opacity: 0; transform: translateY(6px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @media (max-width: 640px) {
        [data-testid="stMainBlockContainer"] {
            padding-top: 1rem;
            padding-left: 1rem;
            padding-right: 1rem;
        }

        .st-key-main_header {
            padding-left: 2.5rem;
        }

        .st-key-main_header h1 {
            font-size: 1.5rem;
            line-height: 1.25;
        }

        [data-testid="stButtonGroup"] [role="radio"] {
            min-height: 44px;
        }

        .workspace-hero {
            min-height: 32vh;
            padding-top: 1rem;
        }

        .workspace-hero h1 {
            font-size: 2.2rem;
        }

        [data-testid="stChatMessage"] {
            padding: 0.8rem 0.75rem;
        }
    }

    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            scroll-behavior: auto !important;
            transition-duration: 0.01ms !important;
        }
    }
    </style>
    """
)


TOOL_PRESENTATION = {
    "search_tool": (":material/search:", "Web search"),
    "calculator": (":material/calculate:", "Calculator"),
    "get_stock_price": (":material/candlestick_chart:", "Market data"),
    "buy_stock": (":material/shopping_cart_checkout:", "Simulated stock purchase"),
    "get_current_weather": (":material/partly_cloudy_day:", "Weather"),
    "rag_tool": (":material/find_in_page:", "Document search"),
    "save_note": (":material/note_add:", "Save note"),
}

SUGGESTIONS = {
    ":material/travel_explore: Research a topic": "Search the web for the latest developments in agentic AI.",
    ":material/calculate: Solve a calculation": "Calculate sqrt(144) + 25 * 4 and explain the result.",
    ":material/cloud: Check the weather": "What is the current weather in Delhi?",
    ":material/description: Explore a PDF": "Summarize the PDF I uploaded and identify its key points.",
}


if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())


def get_config():
    return {"configurable": {"thread_id": st.session_state.thread_id}}


def new_chat():
    st.session_state.thread_id = str(uuid.uuid4())


def message_to_text(message):
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts)
    return str(content)


def get_messages():
    try:
        state = chatbot.get_state(get_config())
        return state.values.get("messages", []) if state else []
    except Exception:
        return []


def get_thread_title(thread_id):
    try:
        state = chatbot.get_state({"configurable": {"thread_id": thread_id}})
        for message in state.values.get("messages", []):
            if isinstance(message, HumanMessage):
                title = " ".join(message_to_text(message).split())
                if title:
                    return title if len(title) <= 38 else title[:35] + "..."
    except Exception:
        pass
    return "New conversation"


def render_tool_activity(tool_calls, tool_results):
    completed = sum(tool_call["id"] in tool_results for tool_call in tool_calls)
    label = (
        f"Agent activity · {completed}/{len(tool_calls)} complete"
        if completed < len(tool_calls)
        else f"Agent activity · {len(tool_calls)} tool{'s' if len(tool_calls) != 1 else ''} used"
    )

    with st.expander(label, icon=":material/automation:", type="compact"):
        for tool_call in tool_calls:
            icon, name = TOOL_PRESENTATION.get(
                tool_call["name"],
                (":material/build:", tool_call["name"].replace("_", " ").capitalize()),
            )
            result = tool_results.get(tool_call["id"])
            if result is None:
                state = ":orange-badge[Permission required]"
            elif "failed" in result.lower() or "denied" in result.lower():
                state = ":red-badge[Not completed]"
            else:
                state = ":green-badge[Completed]"
            st.markdown(f"{icon} **{name}** &nbsp; {state}")


def display_history(messages):
    tool_results = {
        message.tool_call_id: message_to_text(message)
        for message in messages
        if isinstance(message, ToolMessage)
    }
    pending_tool_calls = []

    for message in messages:
        if isinstance(message, HumanMessage):
            if pending_tool_calls:
                with st.chat_message("assistant", avatar=":material/neurology:"):
                    render_tool_activity(pending_tool_calls, tool_results)
                pending_tool_calls = []
            text = message_to_text(message)
            if text.strip():
                with st.chat_message("user"):
                    st.markdown(text)
        elif isinstance(message, AIMessage):
            text = message_to_text(message)
            tool_calls = getattr(message, "tool_calls", [])
            pending_tool_calls.extend(tool_calls)
            if text.strip():
                with st.chat_message("assistant", avatar=":material/neurology:"):
                    if pending_tool_calls:
                        render_tool_activity(pending_tool_calls, tool_results)
                        pending_tool_calls = []
                    st.markdown(text)

    if pending_tool_calls:
        with st.chat_message("assistant", avatar=":material/neurology:"):
            render_tool_activity(pending_tool_calls, tool_results)


def save_uploaded_pdf(uploaded_file):
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix != ".pdf":
        raise ValueError("Only PDF files are supported.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as file:
        file.write(uploaded_file.getbuffer())
        return file.name


def index_uploaded_pdf(uploaded_file):
    temp_path = save_uploaded_pdf(uploaded_file)
    try:
        return ingest_rag_document(temp_path)
    finally:
        Path(temp_path).unlink(missing_ok=True)


def ask_agent(user_text):
    result = chatbot.invoke(
        {"messages": [HumanMessage(content=user_text)]},
        config=get_config(),
    )
    if get_pending_approval(get_config()):
        return None
    return result


with st.sidebar:
    st.title("Agentic", icon=":material/neurology:")
    st.caption("A focused workspace for research and action")

    if st.button(
        "New conversation",
        icon=":material/add_comment:",
        type="primary",
        width="stretch",
    ):
        new_chat()
        st.rerun()

    st.subheader("Conversations")

    try:
        threads = get_all_threads()
        current_thread_id = st.session_state.thread_id
        if current_thread_id in threads:
            threads.remove(current_thread_id)
            threads.insert(0, current_thread_id)

        if threads:
            visible_threads = threads[:12]
            for index, thread_id in enumerate(visible_threads):
                if index == 0 and thread_id == current_thread_id:
                    st.caption("CURRENT")
                elif index == (1 if visible_threads[0] == current_thread_id else 0):
                    st.caption("RECENT")

                is_active = thread_id == current_thread_id
                if st.button(
                    get_thread_title(thread_id),
                    key=f"thread_{thread_id}",
                    icon=(
                        ":material/radio_button_checked:"
                        if is_active
                        else ":material/chat_bubble_outline:"
                    ),
                    type="primary" if is_active else "tertiary",
                    width="stretch",
                    help="Open conversation",
                ):
                    st.session_state.thread_id = thread_id
                    st.rerun()

            if len(threads) > len(visible_threads):
                st.caption(f"{len(threads) - len(visible_threads)} older conversations hidden")
        else:
            st.caption("Your conversations will appear here.")
    except Exception:
        st.caption("Conversation history is temporarily unavailable.")

    st.space("small")
    with st.expander("Workspace", icon=":material/tune:"):
        st.badge("Online", icon=":material/check_circle:", color="green")
        st.caption("Groq · GPT-OSS 120B")
        st.caption("Web, weather, markets, calculator, PDF and notes")


with st.container(horizontal=True, vertical_alignment="center", key="main_header"):
    st.title("Agentic workspace", icon=":material/neurology:")
    st.badge("Ready", icon=":material/bolt:", color="green")
st.caption("Groq reasoning · LangGraph orchestration · human-approved actions")

messages = get_messages()

suggested_prompt = None
if not messages:
    st.html(
        """
        <section class="workspace-hero">
            <div class="workspace-mark">A</div>
            <h1>What can we accomplish today?</h1>
            <p>
                Research live information, reason through complex questions,
                analyze documents, and complete approved actions in one workspace.
            </p>
        </section>
        """
    )
    suggestion = st.pills(
        "Start with a task",
        list(SUGGESTIONS),
        label_visibility="collapsed",
        key="welcome_suggestion",
    )
    if suggestion:
        suggested_prompt = SUGGESTIONS[suggestion]
else:
    display_history(messages)


pending_approval = get_pending_approval(get_config())
if pending_approval:
    with st.container(border=True, key="approval_card"):
        st.subheader("Permission required", icon=":material/shield_lock:")
        st.write("The agent paused before making a change. Review the action below.")

        with st.form("tool_approval"):
            for tool_call in pending_approval["tool_calls"]:
                _, tool_name = TOOL_PRESENTATION.get(
                    tool_call["name"],
                    (":material/build:", tool_call["name"].replace("_", " ").capitalize()),
                )
                st.markdown(f"**{tool_name}**")
                st.caption(tool_call["reason"])
                st.code(
                    json.dumps(tool_call["args"], indent=2, default=str),
                    language="json",
                )

            with st.container(horizontal=True, wrap=True):
                approve_all = st.form_submit_button(
                    "Approve and continue",
                    icon=":material/check_circle:",
                    type="primary",
                )
                deny_all = st.form_submit_button(
                    "Deny",
                    icon=":material/block:",
                )

        if approve_all or deny_all:
            approved_ids = (
                [tool_call["id"] for tool_call in pending_approval["tool_calls"]]
                if approve_all
                else []
            )
            with st.status(":shimmer[Applying your decision]", type="compact"):
                resume_with_approval(get_config(), approved_ids)
            st.rerun()
    st.stop()


prompt = st.chat_input(
    "Message Agentic or attach a PDF",
    accept_file=True,
    file_type=["pdf"],
    max_upload_size=20,
    submit_mode="disable",
)

if prompt or suggested_prompt:
    uploaded_files = prompt.files if prompt else []
    if uploaded_files:
        pdf_file = uploaded_files[0]
        try:
            with st.status(
                f":shimmer[Indexing {pdf_file.name}]",
                expanded=True,
            ) as upload_status:
                chunk_count = index_uploaded_pdf(pdf_file)
                upload_status.update(
                    label=f"{pdf_file.name} is ready",
                    state="complete",
                    expanded=False,
                )
            st.toast(f"Indexed {chunk_count} document chunks", icon=":material/check_circle:")
        except Exception:
            st.error(
                "The PDF could not be indexed. Check the file and try again.",
                icon=":material/error:",
            )

    user_text = suggested_prompt or prompt.text.strip()
    if user_text:
        with st.chat_message("user"):
            st.markdown(user_text)

        with st.chat_message("assistant", avatar=":material/neurology:"):
            try:
                with st.status(":shimmer[Agent working]", type="compact") as activity:
                    st.write("Understanding the request and selecting the right tools")
                    result = ask_agent(user_text)
                    activity.update(label="Task completed", state="complete")
                if result is None:
                    st.rerun()
                st.rerun()
            except Exception:
                st.error(
                    "The agent couldn't complete this request. Please try again.",
                    icon=":material/error:",
                )