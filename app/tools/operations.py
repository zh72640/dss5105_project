"""Bound LangChain tools for the existing business capabilities."""
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import ConfigDict, Field, create_model

from app.services.agent_operations import execute as service_execute
from app.tools.registry import TOOLS, validate_arguments


def _argument_schema(name):
    spec = TOOLS[name]["function"]["parameters"]
    fields = {}
    types = {"string": str, "integer": int, "boolean": bool, "array": list[str]}
    for key, rule in spec["properties"].items():
        declared = types.get(rule.get("type"), Any)
        required = key in spec["required"]
        fields[key] = (declared if required else declared | None,
                       Field(default=... if required else None,
                             description=key.replace("_", " ")))
    return create_model(name.title().replace("_", "") + "Arguments",
                        __config__=ConfigDict(extra="forbid"), **fields)


def bind(name, *, connection, session, as_of, user_message, plan=None):
    """Bind hidden execution context; only declared business arguments reach the model."""
    if name not in TOOLS or name == "record_production_event":
        raise ValueError("UNKNOWN_BUSINESS_TOOL")

    def invoke(**arguments):
        # LangChain fills omitted optional fields with None; preserve the prior sparse contract.
        arguments = {key: value for key, value in arguments.items() if value is not None}
        return service_execute(name, arguments, connection=connection, session=session,
                               as_of=as_of, user_message=user_message, plan=plan)

    return StructuredTool.from_function(
        func=invoke, name=name, description=TOOLS[name]["function"]["description"],
        args_schema=_argument_schema(name))


def execute(name, args, *, connection, session, as_of, user_message, plan=None):
    validate_arguments(name, args)
    return bind(name, connection=connection, session=session, as_of=as_of,
                user_message=user_message, plan=plan).invoke(args)
