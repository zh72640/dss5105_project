"""Category 3 ask_user (inline) and Category 4 load_skill (Skill loader forward)."""
import re
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import Field

from app.agent import skills
from app.schemas.tool import ToolFailure


@tool
def ask_user(question: Annotated[str, Field(min_length=1)], config: RunnableConfig) -> dict:
    """
    Pause this turn with a concrete English question.

    The next user message resumes the same session and Skill snapshot.
    Runtime stops further tool calls after a successful ask_user.

    Args:
        question: English clarifying question for the user.
        config: Trusted runtime config (unused). Not model-supplied.

    Returns:
        dict: {"question": question} for Runtime to set pending_question.

    Errors:
        ENGLISH_REQUIRED when the question contains Chinese characters.
    """
    del config
    if re.search(r"[\u4e00-\u9fff]", question):
        raise ToolFailure("ENGLISH_REQUIRED", "Ask the question in English.")
    return {"question": question}


@tool
def load_skill(name: Annotated[str, Field(min_length=1)], config: RunnableConfig) -> dict:
    """
    Load one named application Skill content and metadata.

    Runtime enables the Skill's tools and stores the snapshot; this tool only loads.

    Args:
        name: Exact Skill directory / front-matter name.
        config: Trusted runtime config (optional skill_root). Not model-supplied.

    Returns:
        dict: name, description, tools, content, hash.

    Errors:
        SKILL_NOT_FOUND when no Skill has that name.
    """
    root = config["configurable"].get("skill_root", skills.SKILL_ROOT)
    try:
        return skills.load(name, root)
    except ValueError as error:
        raise ToolFailure("SKILL_NOT_FOUND", "No application Skill has that name.") from error
