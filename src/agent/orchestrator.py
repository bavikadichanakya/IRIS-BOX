import inspect
import json
import uuid
from typing import Dict, List, Optional, Type

import openai
from pydantic import BaseModel

from src.models.schemas import AgentExecutionResult, StreamChunkPayload
from src.tools.registry import BaseTool, ToolRegistry


class SessionMemory:
    """
    In‑memory session store that keeps a sliding window of recent turns.
    """
    def __init__(self, max_messages: int = 10):
        self.max_messages = max_messages
        self.sessions: Dict[str, List[Dict]] = {}

    def add_message(self, session_id: str, role: str, content: str, tool_calls: Optional[List[Dict]] = None):
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        msg = {"role": role, "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.sessions[session_id].append(msg)
        # sliding window
        if len(self.sessions[session_id]) > self.max_messages:
            self.sessions[session_id] = self.sessions[session_id][-self.max_messages:]

    def get_history(self, session_id: str) -> List[Dict]:
        return self.sessions.get(session_id, [])


class IRISOrchestrator:
    """
    Orchestrates LLM interactions with function and tool calling to execute actions.
    """
    def __init__(self, api_base: str, api_key: str, model: str = "dots-studio/dots-3-note-preview:free"):
        self.client = openai.OpenAI(base_url=api_base, api_key=api_key)
        self.model = model
        self.tool_registry = ToolRegistry
        self._tool_schemas: Optional[List[Dict]] = None
        self._payload_models: Dict[str, Type[BaseModel]] = {}
        self.session_memory = SessionMemory()

    def _get_tool_schemas(self) -> List[Dict]:
        """
        Convert registered tools into schemas that satisfy both top-level name access
        and OpenRouter/OpenAI tools calling format.
        """
        if self._tool_schemas is not None:
            return self._tool_schemas

        tools = []
        self._payload_models = {}
        for name, tool_class in self.tool_registry._tool_classes.items():
            sig = inspect.signature(tool_class.execute)
            params = list(sig.parameters.values())
            if len(params) < 2:
                continue
            payload_param = params[1]
            payload_type = payload_param.annotation
            if isinstance(payload_type, type) and issubclass(payload_type, BaseModel):
                schema = payload_type.model_json_schema()
                description = tool_class.__doc__ or f"Execute {name} action"
                
                # Hybrid dictionary: top-level keys for test suite, 'type' & 'function' for OpenAI tools API
                tool_def = {
                    "name": name,
                    "description": description.strip(),
                    "parameters": {
                        "type": "object",
                        "properties": schema.get("properties", {}),
                        "required": schema.get("required", []),
                    },
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description.strip(),
                        "parameters": {
                            "type": "object",
                            "properties": schema.get("properties", {}),
                            "required": schema.get("required", []),
                        }
                    }
                }
                tools.append(tool_def)
                self._payload_models[name] = payload_type
                
        self._tool_schemas = tools
        return tools

    def process_request(self, user_prompt: str, session_id: Optional[str] = None) -> AgentExecutionResult:
        """
        Process a user request by calling the LLM and executing the tool if returned.
        """
        tool_schemas = self._get_tool_schemas()

        # Build message list with optional history
        messages = [
            {
                "role": "system",
                "content": "You are IRIS, an AI smart speaker assistant. If a user asks for home automation, system tasks, or browser tasks, call the appropriate tool."
            }
        ]
        if session_id:
            messages.extend(self.session_memory.get_history(session_id))
        messages.append({"role": "user", "content": user_prompt})

        # Format as standard OpenAI/OpenRouter tools
        tools_param = [
            {
                "type": "function",
                "function": {
                    "name": s["name"],
                    "description": s["description"],
                    "parameters": s["parameters"],
                }
            }
            for s in tool_schemas
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools_param if tools_param else None,
                tool_choice="auto" if tools_param else None,
            )
        except Exception as e:
            return AgentExecutionResult(
                success=False,
                tool_name="",
                output_payload={},
                error=f"LLM API call failed: {e}"
            )

        message = response.choices[0].message
        
        # Store user and assistant messages in session memory
        if session_id:
            self.session_memory.add_message(session_id, "user", user_prompt)
            assistant_content = message.content or ""
            tool_calls = None
            if getattr(message, "tool_calls", None):
                # serialize tool calls for storage
                tool_calls = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments
                        }
                    }
                    for call in message.tool_calls
                ]
            self.session_memory.add_message(session_id, "assistant", assistant_content, tool_calls)

        # Check both modern tool_calls and legacy function_call
        tool_name = None
        raw_args = "{}"

        if getattr(message, "tool_calls", None) and len(message.tool_calls) > 0:
            call = message.tool_calls[0]
            tool_name = call.function.name
            raw_args = call.function.arguments
        elif getattr(message, "function_call", None) and message.function_call is not None:
            tool_name = message.function_call.name
            raw_args = message.function_call.arguments
        else:
            return AgentExecutionResult(
                success=False,
                tool_name="",
                output_payload={},
                error="LLM did not return a function call."
            )

        try:
            payload_model = self._payload_models.get(tool_name)
            if not payload_model:
                return AgentExecutionResult(
                    success=False,
                    tool_name=tool_name,
                    output_payload={},
                    error=f"Unknown tool: {tool_name}"
                )
            
            args_dict = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            payload = payload_model(**args_dict)
        except Exception as e:
            return AgentExecutionResult(
                success=False,
                tool_name=tool_name,
                output_payload={},
                error=f"Failed to parse function arguments: {e}"
            )

        try:
            tool = self.tool_registry.get_tool(tool_name)
            result = tool.execute(payload)
            return result
        except Exception as e:
            return AgentExecutionResult(
                success=False,
                tool_name=tool_name,
                output_payload={},
                error=f"Tool execution failed: {e}"
            )

    async def stream_request(self, user_prompt: str, session_id: Optional[str] = None):
        """
        Stream LLM response tokens or tool execution results.
        Yields StreamChunkPayload objects.
        """
        session_id = session_id or str(uuid.uuid4())
        tool_schemas = self._get_tool_schemas()

        # Build messages with optional history
        messages = [
            {
                "role": "system",
                "content": "You are IRIS, an AI smart speaker assistant. If a user asks for home automation, system tasks, or browser tasks, call the appropriate tool."
            }
        ]
        if session_id:
            messages.extend(self.session_memory.get_history(session_id))
        messages.append({"role": "user", "content": user_prompt})

        tools_param = [
            {
                "type": "function",
                "function": {
                    "name": s["name"],
                    "description": s["description"],
                    "parameters": s["parameters"],
                }
            }
            for s in tool_schemas
        ]

        async_client = openai.AsyncOpenAI(base_url=self.client.base_url, api_key=self.client.api_key)

        try:
            stream = await async_client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools_param if tools_param else None,
                tool_choice="auto" if tools_param else None,
                stream=True,
            )
        except Exception as e:
            yield StreamChunkPayload(
                chunk_type="complete",
                delta_text=f"Error: {e}",
                session_id=session_id
            )
            return

        tool_name = None
        raw_args = ""
        text_buffer = ""

        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                text_buffer += delta.content
                yield StreamChunkPayload(
                    chunk_type="text_delta",
                    delta_text=delta.content,
                    session_id=session_id
                )
            if delta.tool_calls:
                for call in delta.tool_calls:
                    if call.function.name:
                        tool_name = call.function.name
                    if call.function.arguments:
                        raw_args += call.function.arguments

        # Persist user and assistant messages
        self.session_memory.add_message(session_id, "user", user_prompt)
        assistant_content = text_buffer or ""
        tool_calls = None
        if tool_name:
            tool_calls = [
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": raw_args
                    }
                }
            ]
        self.session_memory.add_message(session_id, "assistant", assistant_content, tool_calls)

        if tool_name:
            try:
                payload_model = self._payload_models.get(tool_name)
                if not payload_model:
                    yield StreamChunkPayload(
                        chunk_type="complete",
                        delta_text=f"Unknown tool: {tool_name}",
                        session_id=session_id
                    )
                    return
                args_dict = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                payload = payload_model(**args_dict)
                tool = self.tool_registry.get_tool(tool_name)
                result = tool.execute(payload)
                # Encode result as JSON string in delta_text
                result_json = json.dumps({
                    "tool_name": tool_name,
                    "success": result.success,
                    "output_payload": result.output_payload,
                    "error": result.error
                })
                yield StreamChunkPayload(
                    chunk_type="tool_call",
                    delta_text=result_json,
                    session_id=session_id
                )
            except Exception as e:
                yield StreamChunkPayload(
                    chunk_type="complete",
                    delta_text=f"Error: {e}",
                    session_id=session_id
                )
        else:
            yield StreamChunkPayload(
                chunk_type="complete",
                delta_text=text_buffer,
                session_id=session_id
            )
