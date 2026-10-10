import asyncio
import concurrent.futures
import inspect
import json
import logging
import time
import uuid
from typing import Dict, List, Optional, Type, Union

logger = logging.getLogger("iris.orchestrator")

import openai
from pydantic import BaseModel

from src.models.schemas import AgentExecutionResult, StreamChunkPayload
from src.tools.registry import BaseTool, ToolRegistry
from src.tools.manager import ToolManager
from src.tools.capability import ToolResult, ExecutionStatus
from src.observability.event_bus import EventBus
from src.storage.db import Database
from src.agent.recovery import ResilientLLMProvider, CircuitState, ProviderUnavailableError
from src.agent.react_loop import ReActLoop


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(coro)).result()
    else:
        return asyncio.run(coro)


import os
from urllib.parse import urlparse

class SecurityError(RuntimeError):
    """Raised when security policy contracts are violated."""
    pass


def validate_offline_endpoint(api_base: str):
    """
    Validates that the LLM endpoint URL hostname resolves strictly to loopback (localhost / 127.0.0.1 / ::1 / 0.0.0.0),
    unless explicit flag IRIS_ALLOW_CLOUD=1 is configured.
    """
    allow_cloud = os.getenv("IRIS_ALLOW_CLOUD", "").lower() in ("1", "true")
    if allow_cloud:
        return
    parsed = urlparse(api_base)
    hostname = (parsed.hostname or "").lower()

    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "mock", "testserver") or "mock" in hostname:
        return

    try:
        import socket
        resolved_ip = socket.gethostbyname(hostname)
        if resolved_ip in ("127.0.0.1", "0.0.0.0"):
            return
    except Exception:
        pass

    raise SecurityError(f"Strict offline policy violation: remote LLM endpoint '{api_base}' rejected.")


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
    Uses ToolManager for policy enforcement, timeout management, and safe execution.
    Persists sessions, turns, tool execution outcomes, and audit logs to Database.
    Integrated with ResilientLLMProvider for exponential backoff, circuit breaking, and generation tracking.
    """
    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str = "dots-studio/dots-3-note-preview:free",
        tool_registry: Optional[Union[Type[ToolRegistry], ToolRegistry]] = None,
        event_bus: Optional[EventBus] = None,
        tool_manager: Optional[ToolManager] = None,
        database: Optional[Database] = None,
        resilient_provider: Optional[ResilientLLMProvider] = None,
        max_steps: int = 5,
    ):
        validate_offline_endpoint(api_base)
        self.api_base = api_base
        self.api_key = api_key
        self.client = openai.OpenAI(base_url=api_base, api_key=api_key)
        self.model = model
        self.tool_registry = tool_registry or ToolRegistry
        self.event_bus = event_bus or EventBus()
        self.tool_manager = tool_manager or ToolManager(
            registry=self.tool_registry,
            event_bus=self.event_bus
        )
        self.database = database
        self.resilient_provider = resilient_provider or ResilientLLMProvider(event_bus=self.event_bus)
        self.react_loop = ReActLoop(tool_manager=self.tool_manager, max_iterations=max_steps)
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
        tool_classes = getattr(self.tool_registry, "_tool_classes", {})
        for name, tool_class in tool_classes.items():
            sig = inspect.signature(tool_class.execute)
            params = list(sig.parameters.values())
            if len(params) < 2:
                continue
            payload_param = params[1]
            payload_type = payload_param.annotation
            if isinstance(payload_type, type) and issubclass(payload_type, BaseModel):
                schema = payload_type.model_json_schema()
                description = tool_class.__doc__ or f"Execute {name} action"

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

    def _format_tool_result(self, tool_name: str, tool_result: ToolResult) -> AgentExecutionResult:
        if tool_result.status == ExecutionStatus.SUCCEEDED:
            if isinstance(tool_result.output, AgentExecutionResult):
                return tool_result.output
            output_dict = tool_result.output if isinstance(tool_result.output, dict) else {"result": tool_result.output}
            return AgentExecutionResult(
                success=True,
                tool_name=tool_name,
                output_payload=output_dict,
                error=None
            )
        elif tool_result.status in (ExecutionStatus.DENIED, ExecutionStatus.UNAVAILABLE):
            return AgentExecutionResult(
                success=False,
                tool_name=tool_name,
                output_payload={},
                error=tool_result.error or f"Tool '{tool_name}' execution was {tool_result.status.value.lower()}.",
                confirmation_token=tool_result.confirmation_token,
                pending_action=tool_result.pending_action
            )
        elif tool_result.status == ExecutionStatus.TIMEOUT:
            return AgentExecutionResult(
                success=False,
                tool_name=tool_name,
                output_payload={},
                error=tool_result.error or f"Tool '{tool_name}' execution timed out."
            )
        else:
            return AgentExecutionResult(
                success=False,
                tool_name=tool_name,
                output_payload={},
                error=tool_result.error or f"Tool '{tool_name}' execution failed."
            )

    def process_request(
        self,
        user_prompt: str,
        session_id: Optional[str] = None,
        device_id: str = "unknown",
        device_type: str = "pod",
        request_id: str = "",
        trace_id: str = "",
        confirmed: bool = False,
        confirmation_token: Optional[str] = None,
    ) -> AgentExecutionResult:
        """
        Process a user request by calling the LLM and executing the tool via ToolManager.
        Persists turn and tool execution details to database if bound.
        """
        session_id = session_id or str(uuid.uuid4())
        start_time = time.perf_counter()
        tool_schemas = self._get_tool_schemas()

        # Build message list with optional history
        messages = [
            {
                "role": "system",
                "content": "You are IRIS, an AI smart speaker assistant. If a user asks for home automation, system tasks, or browser tasks, call the appropriate tool."
            }
        ]
        if session_id:
            if self.database:
                try:
                    db_turns = _run_async(self.database.get_recent_turns(session_id, limit=10))
                    for turn in db_turns:
                        messages.append({"role": "user", "content": turn["user_input"]})
                        asst_msg = {"role": "assistant", "content": turn["assistant_response"]}
                        if turn.get("metadata") and turn["metadata"].get("tool_calls"):
                            asst_msg["tool_calls"] = turn["metadata"]["tool_calls"]
                        messages.append(asst_msg)
                except Exception:
                    messages.extend(self.session_memory.get_history(session_id))
            else:
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

        def _call_completion():
            return self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools_param if tools_param else None,
                tool_choice="auto" if tools_param else None,
            )

        try:
            response = self.resilient_provider.execute_with_recovery_sync(
                _call_completion,
                request_id=request_id or session_id or "",
                trace_id=trace_id or "",
                device_id=device_id or ""
            )
        except Exception as e:
            res = AgentExecutionResult(
                success=False,
                tool_name="",
                output_payload={},
                error=f"LLM API call failed: {e}"
            )
            if self.database:
                try:
                    _run_async(self.database.save_turn(
                        session_id=session_id,
                        user_prompt=user_prompt,
                        assistant_response=res.error,
                        trace_ids=[trace_id] if trace_id else [],
                        duration_ms=(time.perf_counter() - start_time) * 1000.0,
                        device_id=device_id
                    ))
                except Exception:
                    pass
            return res

        message = response.choices[0].message
        assistant_content = message.content or ""
        tool_calls = None
        if getattr(message, "tool_calls", None):
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

        # Store in session memory
        if session_id:
            self.session_memory.add_message(session_id, "user", user_prompt)
            self.session_memory.add_message(session_id, "assistant", assistant_content, tool_calls)

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
            text_response = assistant_content.strip() or "No response generated"
            res = AgentExecutionResult(
                success=True,
                tool_name="",
                output_payload={"response": text_response},
                error=None
            )
            total_duration_ms = (time.perf_counter() - start_time) * 1000.0
            if self.database:
                try:
                    _run_async(self.database.save_turn(
                        session_id=session_id,
                        user_prompt=user_prompt,
                        assistant_response=text_response,
                        trace_ids=[trace_id] if trace_id else [],
                        duration_ms=total_duration_ms,
                        device_id=device_id
                    ))
                    _run_async(self.database.record_audit_event(
                        event_type="orchestrator.request_processed",
                        payload={"request_id": request_id, "text": text_response, "duration_ms": total_duration_ms},
                        correlation_id=trace_id or request_id or session_id,
                        device_id=device_id
                    ))
                except Exception:
                    pass
            return res

        try:
            payload_model = self._payload_models.get(tool_name)
            if not payload_model:
                res = AgentExecutionResult(
                    success=False,
                    tool_name=tool_name,
                    output_payload={},
                    error=f"Unknown tool: {tool_name}"
                )
                if self.database:
                    try:
                        _run_async(self.database.save_turn(
                            session_id=session_id,
                            user_prompt=user_prompt,
                            assistant_response=res.error,
                            trace_ids=[trace_id] if trace_id else [],
                            duration_ms=(time.perf_counter() - start_time) * 1000.0,
                            device_id=device_id
                        ))
                    except Exception:
                        pass
                return res

            args_dict = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            payload = payload_model(**args_dict)
        except Exception as e:
            res = AgentExecutionResult(
                success=False,
                tool_name=tool_name,
                output_payload={},
                error=f"Failed to parse function arguments: {e}"
            )
            if self.database:
                try:
                    _run_async(self.database.save_turn(
                        session_id=session_id,
                        user_prompt=user_prompt,
                        assistant_response=res.error,
                        trace_ids=[trace_id] if trace_id else [],
                        duration_ms=(time.perf_counter() - start_time) * 1000.0,
                        device_id=device_id
                    ))
                except Exception:
                    pass
            return res

        context = {
            "device_id": device_id,
            "device_type": device_type,
            "confirmation_token": confirmation_token,
            "action_payload": args_dict,
            "session_id": session_id,
        }

        try:
            tool_start = time.perf_counter()
            from src.observability.tracing import TraceContext
            trace_ctx = TraceContext(trace_id=trace_id or "", request_id=request_id or "", device_id=device_id or "")
            tool_result: ToolResult = _run_async(
                self.react_loop.execute_step(
                    tool_name=tool_name,
                    arguments=args_dict,
                    trace_context=trace_ctx,
                    context=context
                )
            )
            tool_duration_ms = (time.perf_counter() - tool_start) * 1000.0
            final_res = self._format_tool_result(tool_name, tool_result)
            total_duration_ms = (time.perf_counter() - start_time) * 1000.0

            if self.database:
                try:
                    turn_id = _run_async(
                        self.database.save_turn(
                            session_id=session_id,
                            user_prompt=user_prompt,
                            assistant_response=assistant_content or f"Executed tool {tool_name}",
                            tool_calls=tool_calls,
                            trace_ids=[trace_id] if trace_id else [],
                            duration_ms=total_duration_ms,
                            metadata={"device_id": device_id, "request_id": request_id, "confirmed": confirmed},
                            device_id=device_id
                        )
                    )
                    output_dict = tool_result.output if isinstance(tool_result.output, dict) else {"result": tool_result.output}
                    _run_async(
                        self.database.record_tool_execution(
                            session_id=session_id,
                            tool_name=tool_name,
                            status=tool_result.status.value,
                            duration_ms=tool_duration_ms,
                            turn_id=turn_id,
                            arguments=args_dict,
                            result=output_dict,
                            error=tool_result.error,
                            trace_id=trace_id
                        )
                    )
                    _run_async(
                        self.database.record_audit_event(
                            event_type="orchestrator.request_processed",
                            payload={
                                "request_id": request_id,
                                "tool_name": tool_name,
                                "success": final_res.success,
                                "duration_ms": total_duration_ms,
                            },
                            correlation_id=trace_id or request_id or session_id,
                            device_id=device_id
                        )
                    )
                except Exception:
                    pass

            return final_res
        except Exception as e:
            res = AgentExecutionResult(
                success=False,
                tool_name=tool_name,
                output_payload={},
                error=f"Tool execution failed: {e}"
            )
            if self.database:
                try:
                    _run_async(self.database.save_turn(
                        session_id=session_id,
                        user_prompt=user_prompt,
                        assistant_response=res.error,
                        trace_ids=[trace_id] if trace_id else [],
                        duration_ms=(time.perf_counter() - start_time) * 1000.0,
                        device_id=device_id
                    ))
                except Exception:
                    pass
            return res

    async def stream_request(
        self,
        user_prompt: str,
        session_id: Optional[str] = None,
        device_id: str = "unknown",
        device_type: str = "pod",
        request_id: str = "",
        trace_id: str = "",
        confirmed: bool = False,
    ):
        """
        Stream LLM response tokens or tool execution results via ToolManager.
        Yields StreamChunkPayload objects. Persists turn and tool execution details to database if bound.
        """
        session_id = session_id or str(uuid.uuid4())
        start_time = time.perf_counter()
        tool_schemas = self._get_tool_schemas()

        # Build messages with optional history
        messages = [
            {
                "role": "system",
                "content": "You are IRIS, an AI smart speaker assistant. If a user asks for home automation, system tasks, or browser tasks, call the appropriate tool."
            }
        ]
        if session_id:
            if self.database:
                try:
                    db_turns = await self.database.get_recent_turns(session_id, limit=10)
                    for turn in db_turns:
                        messages.append({"role": "user", "content": turn["user_input"]})
                        asst_msg = {"role": "assistant", "content": turn["assistant_response"]}
                        if turn.get("metadata") and turn["metadata"].get("tool_calls"):
                            asst_msg["tool_calls"] = turn["metadata"]["tool_calls"]
                        messages.append(asst_msg)
                except Exception:
                    messages.extend(self.session_memory.get_history(session_id))
            else:
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

        step_count = 0
        max_steps = getattr(self.react_loop, "max_iterations", 5)
        accumulated_text = ""
        last_tool_name = None

        while step_count < max_steps:
            step_count += 1
            tool_name = None
            raw_args = ""
            text_buffer = ""
            call_id = f"call_{step_count}_{uuid.uuid4().hex[:6]}"

            async def _create_stream():
                return await async_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools_param if tools_param else None,
                    tool_choice="auto" if tools_param else None,
                    stream=True,
                )

            try:
                stream = self.resilient_provider.stream_with_recovery(
                    _create_stream,
                    request_id=request_id or session_id or "",
                    trace_id=trace_id or "",
                    device_id=device_id or ""
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        text_buffer += delta.content
                        accumulated_text += delta.content
                        yield StreamChunkPayload(
                            chunk_type="text_delta",
                            delta_text=delta.content,
                            session_id=session_id
                        )
                    if delta.tool_calls:
                        for call in delta.tool_calls:
                            if hasattr(call, "id") and call.id:
                                call_id = call.id
                            if call.function.name:
                                tool_name = call.function.name
                            if call.function.arguments:
                                raw_args += call.function.arguments
            except Exception as e:
                logger.error(f"Error during LLM streaming step {step_count}: {e}")
                if self.database:
                    try:
                        await self.database.save_turn(
                            session_id=session_id,
                            user_prompt=user_prompt,
                            assistant_response=f"Error: {e}",
                            trace_ids=[trace_id] if trace_id else [],
                            duration_ms=(time.perf_counter() - start_time) * 1000.0,
                            device_id=device_id
                        )
                    except Exception:
                        pass
                yield StreamChunkPayload(
                    chunk_type="complete",
                    delta_text=f"Error: {e}",
                    session_id=session_id
                )
                return

            if tool_name:
                last_tool_name = tool_name
                result_json = json.dumps({"name": tool_name, "arguments": raw_args})
                yield StreamChunkPayload(
                    chunk_type="tool_call",
                    delta_text=result_json,
                    session_id=session_id,
                    tool_name=tool_name
                )

                try:
                    payload_model = self._payload_models.get(tool_name)
                    args_dict = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    if payload_model:
                        _ = payload_model(**args_dict)

                    context = {
                        "device_id": device_id,
                        "device_type": device_type,
                        "confirmed": confirmed,
                    }
                    tool_start = time.perf_counter()
                    tool_result: ToolResult = await self.tool_manager.execute_tool(
                        name=tool_name,
                        arguments=args_dict,
                        request_id=request_id,
                        trace_id=trace_id,
                        context=context
                    )
                    tool_duration_ms = (time.perf_counter() - tool_start) * 1000.0
                    res = self._format_tool_result(tool_name, tool_result)

                    yield StreamChunkPayload(
                        chunk_type="tool_result",
                        delta_text=json.dumps(res.output_payload),
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_output=res.output_payload
                    )

                    messages.append({
                        "role": "assistant",
                        "content": text_buffer or None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": raw_args
                                }
                            }
                        ]
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(res.output_payload)
                    })

                    if self.database:
                        try:
                            turn_id = await self.database.save_turn(
                                session_id=session_id,
                                user_prompt=user_prompt,
                                assistant_response=text_buffer or f"Executed tool {tool_name}",
                                tool_calls=[{"type": "function", "function": {"name": tool_name, "arguments": raw_args}}],
                                trace_ids=[trace_id] if trace_id else [],
                                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                                metadata={"device_id": device_id, "request_id": request_id},
                                device_id=device_id
                            )
                            output_dict = tool_result.output if isinstance(tool_result.output, dict) else {"result": tool_result.output}
                            await self.database.record_tool_execution(
                                session_id=session_id,
                                tool_name=tool_name,
                                status=tool_result.status.value,
                                duration_ms=tool_duration_ms,
                                turn_id=turn_id,
                                arguments=args_dict,
                                result=output_dict,
                                error=tool_result.error,
                                trace_id=trace_id
                            )
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"Tool execution streaming error: {e}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps({"error": str(e)})
                    })
            else:
                break

        # Save final turn and yield completion chunk
        total_duration_ms = (time.perf_counter() - start_time) * 1000.0
        final_text = accumulated_text.strip()
        self.session_memory.add_message(session_id, "user", user_prompt)
        self.session_memory.add_message(session_id, "assistant", final_text)

        if self.database:
            try:
                await self.database.save_turn(
                    session_id=session_id,
                    user_prompt=user_prompt,
                    assistant_response=final_text,
                    trace_ids=[trace_id] if trace_id else [],
                    duration_ms=total_duration_ms,
                    device_id=device_id
                )
                await self.database.record_audit_event(
                    event_type="orchestrator.request_streamed",
                    payload={"request_id": request_id, "text": final_text, "duration_ms": total_duration_ms},
                    correlation_id=trace_id or request_id or session_id,
                    device_id=device_id
                )
            except Exception:
                pass

        yield StreamChunkPayload(
            chunk_type="complete",
            delta_text=final_text,
            session_id=session_id
        )


AgentOrchestrator = IRISOrchestrator

