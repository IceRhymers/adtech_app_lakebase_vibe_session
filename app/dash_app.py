import os
import uuid
from typing import Any, Dict, List, Optional
import logging
import logging

from databricks.sdk import WorkspaceClient
from dash import Dash, Input, Output, State, dcc, html, no_update, ALL, ctx
import dash_bootstrap_components as dbc

from lakebase import get_engine
from databricks_utils import get_workspace_client
from models import MessageType
from services.chat_service import ChatService
from services.agent_service import AgentService
from services.task_queue import (
    create_message_id,
    submit_generation,
    submit_save,
    get_generation_buffer,
    get_save_status,
    pop_save_status,
    submit_history_load,
    pop_history_result,
)


# Configure application logging from environment without hardcoding
_log_level_name = (os.getenv("LOG_LEVEL") or os.getenv("PYTHON_LOG_LEVEL") or "INFO").upper()
_log_level = getattr(logging, _log_level_name, logging.INFO)
logging.basicConfig(level=_log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def build_app() -> Dash:
    client: WorkspaceClient = get_workspace_client()
    logger = logging.getLogger(__name__)

    db_name = os.getenv("LAKEBASE_DB_NAME", "vibe-session-db")
    engine = get_engine(client, db_name)
    # In Dash/Flask, use the default Databricks auth chain or configured profile
    current_user = get_workspace_client().current_user.me().user_name

    chat_service = ChatService(engine, current_user)
    agent_service = AgentService()

    app = Dash(
        __name__,
        external_stylesheets=[dbc.themes.BOOTSTRAP],
        suppress_callback_exceptions=True,
        title="AI Chatbot",
    )

    app.layout = dbc.Container(
        [
            dcc.Store(id="sessions-store"),
            dcc.Store(id="chat-store"),
            dcc.Store(id="errors-store", data=[]),
            dcc.Store(id="delete-target"),
             dcc.Store(id="scroll-trigger"),
            dcc.Interval(id="tick", interval=int(os.getenv("TICK_SLOW_MS", "2000")), n_intervals=0),
            dcc.Interval(id="sessions-tick", interval=int(os.getenv("SESSIONS_TICK_MS", "10000")), n_intervals=0),

            dbc.Navbar(
                dbc.Container(
                    [
                        dbc.NavbarBrand("Vibe Session Chat", className="fw-semibold"),
                        dbc.Badge(f"{current_user}", color="primary", className="ms-auto"),
                    ],
                    fluid=True,
                ),
                color="light",
                className="rounded-3 shadow-sm my-3",
            ),

            # Global delete confirmation modal
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle(id="delete-modal-title")),
                    dbc.ModalBody(id="delete-modal-body"),
                    dbc.ModalFooter([
                        dbc.Button("Cancel", id="cancel-delete", className="ms-auto", outline=True),
                        dbc.Button("Delete", id="confirm-delete", color="danger"),
                    ]),
                ],
                id="delete-confirm-modal",
                is_open=False,
                backdrop=True,
            ),

            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        html.Div(
                                            [
                                                html.Span("Chat Sessions", className="fw-semibold"),
                                                dbc.Button("New", id="new-chat", color="primary", size="sm", className="ms-auto"),
                                            ],
                                            className="d-flex align-items-center gap-2",
                                        )
                                    ),
                                    dbc.CardBody(
                                        [
                                            html.Div(id="sessions-list"),
                                        ]
                                    ),
                                ],
                                className="shadow-sm",
                            ),
                        ],
                        width=3,
                    ),
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        html.Div(
                                            [
                                                html.Div(
                                                    [
                                                        html.Span("AI Chatbot", className="h5 mb-0"),
                                                    ],
                                                    className="d-flex align-items-center gap-2",
                                                ),
                                            ],
                                            className="d-flex align-items-center justify-content-between",
                                        )
                                    ),
                                    dbc.CardBody(
                                        [
                                            html.Div(id="chat-transcript", className="chat-transcript"),
                                        ]
                                    ),
                                    dbc.CardFooter(
                                        dbc.InputGroup(
                                            [
                                                dcc.Input(
                                                    id="chat-input",
                                                    placeholder="Type your message...",
                                                    type="text",
                                                    className="form-control",
                                                ),
                                                dbc.Button("Send", id="send", color="primary"),
                                            ],
                                            className="chat-input-group",
                                        )
                                    ),
                                ],
                                className="shadow-sm",
                            ),
                            html.Div(id="toasts"),
                        ],
                        width=9,
                    ),
                ],
                className="g-3",
            ),
        ],
        fluid=True,
        className="py-2",
    )

    # Load sessions on startup
    @app.callback(
        Output("sessions-store", "data"),
        Input("sessions-tick", "n_intervals"),
        State("sessions-store", "data"),
        prevent_initial_call=False,
    )
    def refresh_sessions(_: int, existing: Optional[List[Dict[str, Any]]]):
        # Periodically refresh sessions in the background so new chats appear without page reload
        def _load_sessions() -> List[Dict[str, Any]]:
            raw = chat_service.get_user_chats()
            return [{"id": s.id, "title": s.title or "Untitled"} for s in raw]

        submit_history_load("__sessions__", _load_sessions)
        logger.debug("refresh_sessions: queued background sessions load (had_existing=%s)", bool(existing))
        # Never overwrite the store with None; let the tick callback set data when ready
        return no_update

    @app.callback(
        Output("sessions-list", "children"),
        Input("sessions-store", "data"),
        Input("chat-store", "data"),
    )
    def render_sessions(sessions: Optional[List[Dict[str, Any]]], chat_state: Optional[Dict[str, Any]]):
        current_chat_id = (chat_state or {}).get("currentChatId") if chat_state else None
        # Do not show a spinner if the store hasn't been explicitly cleared to None
        # We only render spinner when store has no data object yet AND no previous data
        if sessions is None:
            return dbc.Spinner(size="sm", children=" Loading chats...")
        if not sessions:
            return html.Div("No chats yet")
        rows = []
        for s in sessions:
            color = "secondary" if s["id"] != current_chat_id else "primary"
            rows.append(
                html.Div(
                    [
                        dbc.Button(
                            s.get("title") or "Untitled",
                            id={"type": "chat-select", "id": s["id"]},
                            color=color,
                            className="flex-grow-1",
                        ),
                        dbc.Button(
                            "🗑️",
                            id={"type": "chat-delete", "id": s["id"]},
                            color="danger",
                            outline=True,
                            size="sm",
                            className="ms-2",
                        ),
                    ],
                    className="d-flex mb-2",
                )
            )
        return rows

    # Create new chat
    @app.callback(
        Output("chat-store", "data", allow_duplicate=True),
        Output("sessions-store", "data", allow_duplicate=True),
        Input("new-chat", "n_clicks"),
        State("sessions-store", "data"),
        prevent_initial_call=True,
    )
    def new_chat(_: int, sessions_data: Optional[List[Dict[str, Any]]]):
        new_id = str(uuid.uuid4())
        chat_service.create_new_chat_session(new_id)
        # Optimistically add the new chat to the sessions list so it shows immediately
        existing_sessions = sessions_data or []
        optimistic_sessions = [{"id": new_id, "title": "Untitled"}] + existing_sessions
        return {"currentChatId": new_id, "messages": []}, optimistic_sessions

    # Select chat
    @app.callback(
        Output("chat-store", "data", allow_duplicate=True),
        Input({"type": "chat-select", "id": ALL}, "n_clicks"),
        State("sessions-store", "data"),
        prevent_initial_call=True,
    )
    def select_chat(_: List[Optional[int]], sessions_data: List[Dict[str, Any]]):
        # Fire only on a real button click (n_clicks > 0). Pattern-matching inputs
        # can trigger when components are created; guard against that.
        trigger = ctx.triggered_id
        if not trigger or not ctx.triggered or not isinstance(ctx.triggered, list):
            return no_update
        try:
            triggered_value = ctx.triggered[0].get("value", 0)
        except Exception:
            triggered_value = 0
        if not triggered_value:
            return no_update
        selected_id = trigger.get("id")
        if not selected_id:
            return no_update

        # Kick off background load for history to keep UI responsive
        def _load() -> List[Dict[str, Any]]:
            history = chat_service.load_chat_history(selected_id)
            msgs: List[Dict[str, Any]] = []
            for m in history:
                msgs.append({
                    "id": str(uuid.uuid4()),
                    "role": "user" if m.message_type == MessageType.USER else "assistant",
                    "content": m.message_content,
                    "order": m.message_order,
                    "saved": True,
                    "error": None,
                })
            msgs.sort(key=lambda x: x.get("order", 0))
            return msgs

        submit_history_load(selected_id, _load)
        logger.debug("select_chat: selected_id=%s queued load", selected_id)

        # Immediate optimistic state with loading indicator
        return {"currentChatId": selected_id, "messages": [], "isLoading": True}

    # Render transcript
    @app.callback(
        Output("chat-transcript", "children"),
        Input("chat-store", "data"),
    )
    def render_transcript(chat_state: Optional[Dict[str, Any]]):
        if chat_state and chat_state.get("isLoading") and not chat_state.get("messages"):
            return dbc.Spinner(size="sm", children=" Loading chat history...")
        if not chat_state or not chat_state.get("messages"):
            return html.Div("Welcome! Start a new chat or select an existing one.", className="text-muted")
        elements = []
        for m in sorted(chat_state["messages"], key=lambda x: x.get("order", 0)):
            is_user = m["role"] == "user"
            meta_bits = []
            if not m.get("saved", True):
                meta_bits.append("unsaved")
            if m.get("error"):
                meta_bits.append(f"error: {m['error']}")
            meta = f" {' • '.join(meta_bits)}" if meta_bits else ""
            elements.append(
                html.Div(
                    [
                        html.Div("You" if is_user else "Assistant", className="message-meta small text-muted"),
                        html.Div(m["content"], className=f"chat-bubble {'user' if is_user else 'assistant'}"),
                        html.Div(meta, className="message-status small text-muted"),
                    ],
                    className=f"message-row {'from-user' if is_user else 'from-assistant'}",
                )
            )
        # Sentinel div used by clientside callback to scroll to bottom
        elements.append(html.Div(id="scroll-anchor"))
        return elements

    # Send message
    @app.callback(
        Output("chat-store", "data", allow_duplicate=True),
        Output("errors-store", "data", allow_duplicate=True),
        Output("chat-input", "value"),
        Input("send", "n_clicks"),
        Input("chat-input", "n_submit"),
        State("chat-input", "value"),
        State("chat-store", "data"),
        prevent_initial_call=True,
    )
    def send_message(_: Optional[int], __: Optional[int], text: Optional[str], chat_state: Optional[Dict[str, Any]]):
        if not text:
            return no_update, no_update, no_update
        if not chat_state or not chat_state.get("currentChatId"):
            return no_update, no_update, no_update

        chat_id = chat_state["currentChatId"]
        messages = chat_state.get("messages", []).copy()

        # Determine next order locally for snappier UX
        next_order = (max((m.get("order", -1) for m in messages), default=-1) + 1)

        # Create user message
        user_message_id = create_message_id()
        user_message = {
            "id": user_message_id,
            "role": "user",
            "content": text,
            "order": next_order,
            "saved": False,
            "saving": True,
            "error": None,
        }
        messages.append(user_message)

        # Placeholder assistant message
        assistant_message_id = create_message_id()
        assistant_message = {
            "id": assistant_message_id,
            "role": "assistant",
            "content": "",
            "order": next_order + 1,
            "saved": False,
            "error": None,
        }
        messages.append(assistant_message)

        # Background save for user message
        def save_user():
            chat_service.save_message_with_embedding(chat_id, MessageType.USER, text, next_order)

        submit_save(user_message_id, save_user)
        logger.debug("send_message: queued save user_message_id=%s order=%s", user_message_id, next_order)

        # Background generation
        def generate():
            # Build agent input from transcript including the new user msg
            from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
            history_msgs = []
            for m in sorted(messages, key=lambda x: x["order"]):
                role = ChatMessageRole.USER if m["role"] == "user" else ChatMessageRole.ASSISTANT
                history_msgs.append(ChatMessage(role=role, content=m["content"]))
            return agent_service.generate_bot_response(current_user, history_msgs)

        # Databricks endpoint returns the full response; disable simulated streaming
        submit_generation(assistant_message_id, generate, simulate_stream=False)
        logger.debug("send_message: queued generation assistant_message_id=%s", assistant_message_id)

        new_state = {"currentChatId": chat_id, "messages": messages}
        return new_state, no_update, ""

    # Open delete confirmation modal
    @app.callback(
        Output("delete-target", "data"),
        Output("delete-modal-title", "children"),
        Output("delete-modal-body", "children"),
        Output("delete-confirm-modal", "is_open"),
        Input({"type": "chat-delete", "id": ALL}, "n_clicks"),
        State("sessions-store", "data"),
        prevent_initial_call=True,
    )
    def open_delete_modal(_: List[Optional[int]], sessions: Optional[List[Dict[str, Any]]]):
        trigger = ctx.triggered_id
        # Only respond to actual clicks (>0). Avoid firing on initial render or list refreshes.
        if not trigger or not ctx.triggered or not isinstance(ctx.triggered, list):
            return no_update, no_update, no_update, no_update
        try:
            triggered_value = ctx.triggered[0].get("value", 0)
        except Exception:
            triggered_value = 0
        if not triggered_value:
            return no_update, no_update, no_update, no_update
        target_id = trigger.get("id")
        if not target_id:
            return no_update, no_update, no_update, no_update
        title = None
        for s in sessions or []:
            if s.get("id") == target_id:
                title = s.get("title") or "this chat"
                break
        modal_title = f"Delete '{title}'?" if title else "Delete this chat?"
        modal_body = "This will permanently delete the conversation."
        return target_id, modal_title, modal_body, True

    # Confirm delete
    @app.callback(
        Output("sessions-store", "data", allow_duplicate=True),
        Output("chat-store", "data", allow_duplicate=True),
        Output("delete-confirm-modal", "is_open", allow_duplicate=True),
        Output("delete-target", "data", allow_duplicate=True),
        Input("confirm-delete", "n_clicks"),
        State("delete-target", "data"),
        State("sessions-store", "data"),
        State("chat-store", "data"),
        prevent_initial_call=True,
    )
    def confirm_delete(_: Optional[int], target_id: Optional[str], sessions: Optional[List[Dict[str, Any]]], chat_state: Optional[Dict[str, Any]]):
        if not target_id:
            return no_update, no_update, False, None
        try:
            chat_service.delete_chat_session(target_id)
        except Exception as e:
            logging.getLogger(__name__).warning("Failed to delete chat %s: %s", target_id, e)
        # Update sessions list locally
        new_sessions = [s for s in (sessions or []) if s.get("id") != target_id]
        # Reset current chat if it was deleted
        if chat_state and chat_state.get("currentChatId") == target_id:
            new_chat_state = {"currentChatId": None, "messages": []}
        else:
            new_chat_state = no_update
        return new_sessions, new_chat_state, False, None

    # Cancel delete
    @app.callback(
        Output("delete-confirm-modal", "is_open", allow_duplicate=True),
        Output("delete-target", "data", allow_duplicate=True),
        Input("cancel-delete", "n_clicks"),
        prevent_initial_call=True,
    )
    def cancel_delete(_: Optional[int]):
        return False, None

    # Provide immediate visual feedback while deletion is in-flight
    @app.callback(
        Output("confirm-delete", "children"),
        Output("confirm-delete", "disabled"),
        Output("cancel-delete", "disabled"),
        Input("confirm-delete", "n_clicks"),
        Input("delete-confirm-modal", "is_open"),
        prevent_initial_call=False,
    )
    def toggle_delete_loading(n_clicks: Optional[int], is_open: bool):
        # When modal is open and user has clicked delete at least once, show loading state
        if is_open and (n_clicks or 0) > 0:
            return "Deleting...", True, True
        # Default state
        return "Delete", False, False

    # Tick: integrate stream/progress and save results
    @app.callback(
        Output("chat-store", "data", allow_duplicate=True),
        Output("errors-store", "data", allow_duplicate=True),
        Output("sessions-store", "data", allow_duplicate=True),
        Output("tick", "interval"),
        Input("tick", "n_intervals"),
        State("chat-store", "data"),
        State("errors-store", "data"),
        State("sessions-store", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def tick(_: int, chat_state: Optional[Dict[str, Any]], errors_state: Optional[List[Dict[str, Any]]], sessions_data: Optional[List[Dict[str, Any]]]):
        fast_ms = int(os.getenv("TICK_FAST_MS", "150"))
        slow_ms = int(os.getenv("TICK_SLOW_MS", "2000"))
        next_interval_ms = slow_ms
        if not chat_state:
            # Still allow sessions update via background fetch
            loaded_sessions = pop_history_result("__sessions__")
            if loaded_sessions is not None:
                logger.debug("tick: loaded sessions=%d", len(loaded_sessions))
                return no_update, no_update, loaded_sessions, next_interval_ms
            return no_update, no_update, no_update, next_interval_ms

        # Integrate background history load completion
        loaded_history = None
        current_chat_id = chat_state.get("currentChatId") if chat_state else None
        if current_chat_id:
            loaded_history = pop_history_result(current_chat_id)

        # Integrate background sessions load completion
        loaded_sessions = pop_history_result("__sessions__")

        messages = chat_state.get("messages", []).copy()
        errors_list = (errors_state or []).copy()

        changed = False
        has_active_generation = False
        has_pending_save = False

        if loaded_history is not None:
            messages = loaded_history
            changed = True
            # Clear loading flag explicitly in the next state we return
            if chat_state.get("isLoading"):
                chat_state = {**chat_state, "isLoading": False}
            logger.debug("tick: merged history messages=%d for chat_id=%s", len(messages), current_chat_id)

        # Process streaming updates and completion
        for m in messages:
            if m["role"] != "assistant":
                continue
            buf = get_generation_buffer(m["id"])
            if buf is None:
                continue
            if not buf.is_done:
                has_active_generation = True

            # Update content
            full_text = buf.read_all()
            if full_text != m["content"]:
                m["content"] = full_text
                changed = True

            if buf.is_done:
                if buf.error and not m.get("error"):
                    m["error"] = buf.error
                    changed = True
                # When done and no error, trigger background save if not already saved
                if not m.get("error") and not m.get("saved") and m.get("content") and not m.get("saving", False):
                    order_val = m.get("order", 0)

                    def save_assistant(chat_id=chat_state["currentChatId"], content=m["content"], order_val=order_val):
                        chat_service.save_message_with_embedding(chat_id, MessageType.ASSISTANT, content, order_val)

                    submit_save(m["id"], save_assistant)
                    logger.debug("tick: queued save assistant_message_id=%s", m["id"])
                    m["saving"] = True
                    changed = True

        # Process save statuses
        for m in messages:
            status = pop_save_status(m["id"])  # read-once
            if not status:
                if m.get("saving") and not m.get("saved"):
                    has_pending_save = True
                continue
            if status.ok:
                m["saved"] = True
                m["saving"] = False
                m["error"] = None
                logger.debug("tick: save success message_id=%s", m["id"])
                changed = True
            else:
                # Surface non-blocking error
                m["saved"] = False
                m["saving"] = False
                m["error"] = status.error or "Failed to save"
                errors_list.append({"messageId": m["id"], "stage": "save", "error": m["error"]})
                logger.debug("tick: save error message_id=%s error=%s", m["id"], m["error"])
                changed = True

        if has_active_generation or has_pending_save or chat_state.get("isLoading"):
            next_interval_ms = fast_ms
        else:
            next_interval_ms = slow_ms

        if not changed and loaded_sessions is None:
            return no_update, no_update, no_update, next_interval_ms

        # Only update sessions-store when we actually fetched new sessions
        sessions_out = no_update
        if loaded_sessions is not None:
            sessions_out = loaded_sessions

        next_chat_state = {"currentChatId": current_chat_id, "messages": messages}
        # Preserve explicit isLoading=False once we have loaded history
        if chat_state.get("isLoading") and loaded_history is not None:
            next_chat_state["isLoading"] = False

        logger.debug("tick: state updated messages=%d errors=%d sessions_updated=%s", len(messages), len(errors_list), sessions_out is not no_update)
        return next_chat_state, errors_list, sessions_out, next_interval_ms

    # Render errors as toasts
    @app.callback(
        Output("toasts", "children"),
        Input("errors-store", "data"),
    )
    def render_toasts(errors_data: Optional[List[Dict[str, Any]]]):
        if not errors_data:
            return []
        items = []
        for e in errors_data[-3:]:  # show last few
            items.append(
                dbc.Toast(
                    [html.Div(f"Latest message failed to commit to history: {e.get('error','unknown error')}")],
                    header="Save Error",
                    icon="danger",
                    dismissable=True,
                    is_open=True,
                    duration=4000,
                    style={"position": "relative", "minWidth": "300px", "marginTop": "0.5rem"},
                )
            )
        return items

    # Auto-scroll transcript to bottom whenever transcript content changes
    app.clientside_callback(
        """
        function(children){
            try {
                var anchor = document.getElementById('scroll-anchor');
                if (anchor && anchor.scrollIntoView) {
                    anchor.scrollIntoView({behavior: 'auto', block: 'end'});
                } else {
                    var el = document.getElementById('chat-transcript');
                    if (el) el.scrollTop = el.scrollHeight;
                }
            } catch (e) {}
            return 0;
        }
        """,
        Output("scroll-trigger", "data"),
        Input("chat-transcript", "children"),
    )

    return app


app = build_app()
server = app.server


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8050"))
    app.run_server(host="0.0.0.0", port=port, debug=True)


