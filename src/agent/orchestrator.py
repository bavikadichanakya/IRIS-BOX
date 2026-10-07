import inspect
import json
from typing import Dict, List, Optional, Type

import openai
from pydantic import BaseModel

from src.models.schemas import AgentExecutionResult
from src.tools.registry import BaseTool, ToolRegistry


class IRISOrchestrator:
    """
    Orchestrates LLM interactions with function calling to execute tools.
    """
    def __init__(self, api_base: str, api_key: str, model: str = "gpt-3.5-turbo-16k"):
        self.client = openai.OpenAI(base_url=api_base, api_key=api_key)
        self.model = model
        self.tool_registry = ToolRegistry
        self._tool_schemas: Optional[List[Dict]] = None
        self._payload_models: Dict[str, Type[BaseModel]] = {}

    def _get_tool_schemas(self) -> List[Dict]:
        """
        Convert registered tools into OpenAI function calling schemas.
        """
        if self._tool_schemas is not None:
            return self._tool_schemas

        functions = []
        self._payload_models = {}
        for name, tool_class in self.tool_registry._tool_classes.items():
            # Get the payload model from the execute method's first parameter type hint
            sig = inspect.signature(tool_class.execute)
            params = list(sig.parameters.values())
            if len(params) < 2:
                continue  # Skip if no payload parameter
            payload_param = params[1]  # First is self, second is payload
            payload_type = payload_param.annotation
            if isinstance(payload_type, type) and issubclass(payload_type, BaseModel):
                schema = payload_type.model_json_schema()
                description = tool_class.__doc__ or ""
                function_def = {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": schema.get("properties", {}),
                        "required": schema.get("required", []),
                    }
                }
                functions.append(function_def)
                self._payload_models[name] = payload_type
        self._tool_schemas = functions
        return functions

    def process_request(self, user_prompt: str) -> AgentExecutionResult:
        """
        Process a user request by calling the LLM and executing the tool if required.
        """
        # Get the function schemas
        functions = self._get_tool_schemas()

        # Call the LLM
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": user_prompt}],
                functions=functions,
                function_call="auto",
            )
        except Exception as e:
            return AgentExecutionResult(
                success=False,
                tool_name="",
                output_payload={},
                error=f"LLM API call failed: {e}"
            )

        # Check if the response contains a function call
        message = response.choices[0].message
        if not hasattr(message, 'function_call') or message.function_call is None:
            return AgentExecutionResult(
                success=False,
                tool_name="",
                output_payload={},
                error="LLM did not return a function call."
            )

        func_call = message.function_call
        tool_name = func_call.name
        try:
            # Validate the arguments by parsing into the Pydantic model
            payload_model = self._payload_models.get(tool_name)
            if not payload_model:
                return AgentExecutionResult(
                    success=False,
                    tool_name=tool_name,
                    output_payload={},
                    error=f"Unknown tool: {tool_name}"
                )
            # The arguments are in JSON format, we need to parse them
            args_dict = json.loads(func_call.arguments)
            payload = payload_model(**args_dict)
        except Exception as e:
            return AgentExecutionResult(
                success=False,
                tool_name=tool_name,
                output_payload={},
                error=f"Failed to parse function arguments: {e}"
            )

        # Execute the tool
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
