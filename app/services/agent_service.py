import os
import json
import logging
from typing import Any, Dict, List, Optional, Generator

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

from databricks_utils import get_workspace_client

logger = logging.getLogger(__name__)

class AgentService:
    """
    Handles interaction with the Databricks chat agent serving endpoint.
    """

    def __init__(self, client: WorkspaceClient | None = None):
        self.client = client or get_workspace_client()

    def _normalize_response_to_text(self, response: Any) -> str:
        """
        Normalize various Databricks Serving response shapes (Claude/chat, LangGraph, raw strings)
        into a single plain text string suitable for display and persistence.

        Known shapes handled:
        - str -> returned as-is
        - { choices: [{ message: { content } } ] } -> extract content
        - { output_text | text } -> extract as content
        - { messages: [ { role, content, ... } ] } -> join assistant contents
        - [ { messages: [...] }, ... ] -> join assistant contents across items
        - [ str | {text}|{output_text}|{choices}] -> join extracted with double newlines
        Fallback: JSON stringify.
        """
        try:
            # 1) Simple string
            if isinstance(response, str):
                return response

            # 2) choices shape
            if isinstance(response, dict):
                if "choices" in response and isinstance(response["choices"], list) and response["choices"]:
                    choice0 = response["choices"][0]
                    try:
                        return str(choice0["message"]["content"])  # type: ignore[index]
                    except Exception:
                        pass
                # explicit text fields
                if isinstance(response.get("output_text"), str):
                    return str(response["output_text"])  # type: ignore[index]
                if isinstance(response.get("text"), str):
                    return str(response["text"])  # type: ignore[index]
                # messages array
                msgs = response.get("messages")
                if isinstance(msgs, list) and msgs:
                    assistant_texts: List[str] = []
                    for m in msgs:
                        if not isinstance(m, dict):
                            continue
                        role = m.get("role")
                        content = m.get("content")
                        if role == "assistant" and isinstance(content, str) and content.strip():
                            assistant_texts.append(content)
                    if assistant_texts:
                        return "\n\n".join(assistant_texts)

            # 3) top-level list (e.g., LangGraph batches)
            if isinstance(response, list) and response:
                collected: List[str] = []
                for item in response:
                    if isinstance(item, str):
                        if item.strip():
                            collected.append(item)
                        continue
                    if isinstance(item, dict):
                        # nested messages
                        msgs = item.get("messages")
                        if isinstance(msgs, list):
                            assistant_texts: List[str] = []
                            for m in msgs:
                                if not isinstance(m, dict):
                                    continue
                                role = m.get("role")
                                content = m.get("content")
                                if role == "assistant" and isinstance(content, str) and content.strip():
                                    assistant_texts.append(content)
                            if assistant_texts:
                                collected.append("\n\n".join(assistant_texts))
                                continue
                        # explicit fields
                        if isinstance(item.get("output_text"), str) and item["output_text"].strip():
                            collected.append(item["output_text"])  # type: ignore[index]
                            continue
                        if isinstance(item.get("text"), str) and item["text"].strip():
                            collected.append(item["text"])  # type: ignore[index]
                            continue
                        if "choices" in item and isinstance(item["choices"], list) and item["choices"]:
                            try:
                                collected.append(str(item["choices"][0]["message"]["content"]))  # type: ignore[index]
                                continue
                            except Exception:
                                pass
                if collected:
                    return "\n\n".join(collected)

            # 4) last resort: stringify
            return json.dumps(response)
        except Exception:
            try:
                return json.dumps(response)
            except Exception:
                return ""

    def generate_bot_response(self, current_user: str, messages: List[ChatMessage]) -> str:
        try:
            agent_endpoint = os.getenv("AGENT_ENDPOINT")
            if not agent_endpoint:
                return "Error: AGENT_ENDPOINT environment variable not configured."

            max_context_messages_str = os.getenv("CHAT_CONTEXT_LIMIT", "5")
            try:
                max_context_messages = int(max_context_messages_str)
            except ValueError:
                max_context_messages = 5
            if max_context_messages <= 0:
                max_context_messages = 5

            system_prompt = (
                """
        You are a helpful assistant that can answer questions and help with tasks, you are also able to search the chat history for relevant information.
        If the user asks a question that is not related to the chat history, you shouldn't mention you couldn't find anything related to the question.
        """
            ).strip()

            limited_messages = messages[-max_context_messages:] if messages else []

            # Build messages list compatible with Databricks Claude chat API: only user/assistant in messages, system provided separately.
            message_dicts = []
            for msg in limited_messages:
                # Skip any empty messages to satisfy API requirement
                if not msg.content or not str(msg.content).strip():
                    continue
                role_value = "user" if msg.role == ChatMessageRole.USER else "assistant"
                message_dicts.append({
                    "role": role_value,
                    "content": msg.content,
                })

            # Get configurable k value for chat history retrieval
            agent_chat_k_str = os.getenv("AGENT_CHAT_K", "5")
            try:
                agent_chat_k = int(agent_chat_k_str)
            except ValueError:
                agent_chat_k = 5
            if agent_chat_k <= 0:
                agent_chat_k = 5

            # Agent endpoint expects the request data directly (not wrapped in "inputs")
            payload = {
                "messages": message_dicts,
                "custom_inputs": {
                    "filters": {
                        "user_name": current_user,
                    },
                    "k": agent_chat_k,
                },
            }

            payload_json = json.dumps(payload)
            logger.debug(f"Payload: {payload_json}")

            response = self.client.api_client.do(
                method="POST",
                path=f"/serving-endpoints/{agent_endpoint}/invocations",
                headers={"Content-Type": "application/json"},
                data=payload_json,
            )

            # Normalize to text across all variants (Claude/chat, LangGraph, etc.)
            return self._normalize_response_to_text(response)
        except Exception as e:
            return f"Error calling model serving endpoint: {str(e)}"

    def generate_bot_response_stream(self, current_user: str, messages: List[ChatMessage]) -> Generator[str, None, None]:
        """
        Generate bot response using our agent's predict_stream method via direct API call.
        Yields chunks of text as they arrive from the model.
        """
        try:
            agent_endpoint = os.getenv("AGENT_ENDPOINT")
            if not agent_endpoint:
                yield "Error: AGENT_ENDPOINT environment variable not configured."
                return

            max_context_messages_str = os.getenv("CHAT_CONTEXT_LIMIT", "5")
            try:
                max_context_messages = int(max_context_messages_str)
            except ValueError:
                max_context_messages = 5
            if max_context_messages <= 0:
                max_context_messages = 5

            limited_messages = messages[-max_context_messages:] if messages else []

            # Build messages list compatible with OpenAI chat API (include system prompt)
            system_prompt = (
                """
        You are a helpful assistant that can answer questions and help with tasks, you are also able to search the chat history for relevant information.
        If the user asks a question that is not related to the chat history, you shouldn't mention you couldn't find anything related to the question.
        """
            ).strip()

            chat_messages: List[Dict[str, str]] = []
            chat_messages.append({"role": "system", "content": system_prompt})
            for msg in limited_messages:
                if not msg.content or not str(msg.content).strip():
                    continue
                role_value = "user" if msg.role == ChatMessageRole.USER else "assistant"
                chat_messages.append({
                    "role": role_value,
                    "content": msg.content,
                })

            # Get configurable k value for chat history retrieval
            agent_chat_k_str = os.getenv("AGENT_CHAT_K", "5")
            try:
                agent_chat_k = int(agent_chat_k_str)
            except ValueError:
                agent_chat_k = 5
            if agent_chat_k <= 0:
                agent_chat_k = 5

            # Use Databricks-configured OpenAI client for true streaming
            oai_client = self.client.serving_endpoints.get_open_ai_client()

            stream = oai_client.chat.completions.create(
                model=agent_endpoint,
                messages=chat_messages,
                stream=True,
                extra_body={
                    "custom_inputs": {
                        "filters": {"user_name": current_user},
                        "k": agent_chat_k,
                    }
                },
            )

            for event in stream:
                chunk = None
                # Standard OpenAI shape
                try:
                    if getattr(event, "choices", None):
                        choice0 = event.choices[0]
                        # dataclasses from openai lib expose .delta.content
                        delta_obj = getattr(choice0, "delta", None)
                        if delta_obj is not None:
                            chunk = getattr(delta_obj, "content", None)
                except Exception:
                    pass

                # Databricks variant: top-level delta dict with content
                if chunk is None:
                    try:
                        delta_top = getattr(event, "delta", None)
                        if isinstance(delta_top, dict):
                            maybe = delta_top.get("content")
                            if isinstance(maybe, str) and maybe:
                                chunk = maybe
                    except Exception:
                        pass

                if chunk:
                    yield chunk
                    
        except Exception as e:
            logger.exception("Error in streaming bot response")
            yield f"Error calling model serving endpoint: {str(e)}"


