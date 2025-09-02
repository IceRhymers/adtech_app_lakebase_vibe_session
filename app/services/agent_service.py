import os
import json
from typing import List

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

from databricks_utils import get_workspace_client


class AgentService:
    """
    Handles interaction with the Databricks chat agent serving endpoint.
    """

    def __init__(self, client: WorkspaceClient | None = None):
        self.client = client or get_workspace_client()

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

            payload = {
                "system": system_prompt,
                "messages": message_dicts,
                "custom_inputs": {
                    "filters": {
                        "user_name": current_user,
                    }
                },
            }

            payload_json = json.dumps(payload)

            response = self.client.api_client.do(
                method="POST",
                path=f"/serving-endpoints/{agent_endpoint}/invocations",
                headers={"Content-Type": "application/json"},
                data=payload_json,
            )

            # Normalize common response shapes
            if isinstance(response, list) and len(response) > 0:
                return response[0]
            if isinstance(response, dict) and "choices" in response:
                return response["choices"][0]["message"]["content"]
            return str(response)
        except Exception as e:
            return f"Error calling model serving endpoint: {str(e)}"


