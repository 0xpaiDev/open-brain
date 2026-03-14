"""Extraction prompts for Open Brain.

Prompts guide Claude to extract structured information from raw memory text.
Three escalating prompt levels are provided for retry handling:
  - Attempt 0: Full extraction with all fields
  - Attempt 1: Stricter, explicitly JSON-only
  - Attempt 2: Minimal fallback (title + summary only)

All prompts wrap user input in <user_input>...</user_input> delimiters
for prompt injection defense.
"""

EXTRACTION_SYSTEM_PROMPT = """You are an AI assistant helping to extract and structure organizational memory.

Your task is to analyze the provided user input and extract:
1. A memory type (memory, decision, task, or context)
2. The core content
3. A brief summary
4. Named entities mentioned (persons, organizations, projects, concepts, tools, places)
5. Key decisions made
6. Actionable tasks
7. Base importance (0.0–1.0): how significant is this memory for future context?

You MUST respond with valid JSON only. Do not include any text before or after the JSON.

JSON schema:
{
  "type": "memory|decision|task|context",
  "content": "main text content",
  "summary": "brief one-sentence summary",
  "entities": [
    {
      "name": "Entity Name",
      "type": "person|org|project|concept|tool|place"
    }
  ],
  "decisions": [
    {
      "decision": "what was decided",
      "reasoning": "why this decision was made",
      "alternatives": ["alternative 1", "alternative 2"]
    }
  ],
  "tasks": [
    {
      "description": "what needs to be done",
      "owner": "who is responsible (optional)",
      "due_date": "ISO date string (optional)"
    }
  ],
  "base_importance": 0.5
}

Be concise. Extract only what is explicitly mentioned. If a field is not applicable, use empty arrays or null.
Do NOT invent entities, decisions, or tasks that aren't mentioned."""

EXTRACTION_RETRY_PROMPT_1 = """You are an AI assistant helping to extract and structure organizational memory.

Your task is to analyze the provided user input and extract structured information.

You MUST respond with VALID JSON ONLY. Do not include any text before or after the JSON.

JSON schema:
{
  "type": "memory|decision|task|context",
  "content": "main text content",
  "summary": "brief one-sentence summary",
  "entities": [{"name": "string", "type": "person|org|project|concept|tool|place"}],
  "decisions": [{"decision": "string", "reasoning": "string", "alternatives": []}],
  "tasks": [{"description": "string", "owner": null, "due_date": null}],
  "base_importance": 0.5
}

Extract only what is explicitly stated. Return empty arrays for missing fields. DO NOT INVENT DATA."""

EXTRACTION_RETRY_PROMPT_2 = """Extract key information from the user input.

Respond with ONLY this JSON (no other text):
{
  "type": "memory",
  "content": "the main text",
  "summary": "one sentence",
  "entities": [],
  "decisions": [],
  "tasks": [],
  "base_importance": 0.5
}"""


def build_extraction_user_message(text: str) -> str:
    """Wrap raw text in user_input delimiters for prompt injection defense.

    Args:
        text: The raw user input text

    Returns:
        Text wrapped in <user_input>...</user_input> tags
    """
    return f"<user_input>{text}</user_input>"


def get_extraction_prompt(attempt: int) -> str:
    """Return the system prompt for the given retry attempt.

    Args:
        attempt: Attempt number (0, 1, or 2)

    Returns:
        System prompt string for this attempt level

    Raises:
        ValueError: If attempt is not 0, 1, or 2
    """
    if attempt == 0:
        return EXTRACTION_SYSTEM_PROMPT
    elif attempt == 1:
        return EXTRACTION_RETRY_PROMPT_1
    elif attempt == 2:
        return EXTRACTION_RETRY_PROMPT_2
    else:
        raise ValueError(f"Invalid extraction attempt number: {attempt}. Must be 0, 1, or 2.")
