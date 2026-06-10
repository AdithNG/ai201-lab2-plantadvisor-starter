import json
from groq import Groq, BadRequestError
from config import GROQ_API_KEY, LLM_MODEL, MAX_TOOL_ROUNDS
from tools import lookup_plant, get_seasonal_conditions

_client = Groq(api_key=GROQ_API_KEY)

# llama-3.3 on Groq occasionally emits a malformed tool call that the server
# can't parse (BadRequestError, code 'tool_use_failed'). It's transient, so we
# retry the same request a few times before giving up.
_MAX_API_RETRIES = 3


def _create_completion(messages: list, use_tools: bool):
    """Call the Groq API, retrying the transient 'tool_use_failed' 400 error."""
    last_error = None
    for _ in range(_MAX_API_RETRIES):
        try:
            if use_tools:
                return _client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                )
            return _client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                tool_choice="none",
            )
        except BadRequestError as error:
            if "tool_use_failed" in str(error):
                last_error = error
                continue  # transient — retry
            raise
    raise last_error

# ──────────────────────────────────────────────
# Tool definitions
#
# These are the schemas that tell the LLM what tools are available and how to
# call them. The LLM reads these descriptions and decides when (and how) to use
# each tool. They're already complete — your job is to implement the tool
# functions in tools.py and the agent loop below.
# ──────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_plant",
            "description": (
                "Look up care information for a specific houseplant by name. "
                "Returns detailed watering, light, humidity, and temperature requirements. "
                "Use this whenever the user asks about a specific plant."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plant_name": {
                        "type": "string",
                        "description": "The plant name to look up. Can be a common name, scientific name, or nickname (e.g., 'pothos', 'devil's ivy', 'Monstera deliciosa').",
                    }
                },
                "required": ["plant_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_seasonal_conditions",
            "description": (
                "Get seasonal care adjustments for houseplants. "
                "Returns guidance on watering, fertilizing, light, and pests for the current or specified season. "
                "Use this when a user asks a season-specific question, or to complement plant care advice with seasonal context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "season": {
                        "type": "string",
                        "description": "The season to get care conditions for. If omitted, the current season is detected automatically.",
                        "enum": ["spring", "summer", "fall", "winter"],
                    }
                },
                "required": [],
            },
        },
    },
]

# ──────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a knowledgeable and friendly plant care advisor. "
    "Help users care for their houseplants by looking up specific plant information "
    "and current seasonal conditions using your available tools.\n\n"
    "Always use your tools to look up plant-specific information before answering — "
    "don't rely on your general knowledge alone. If a plant isn't in your database, "
    "say so clearly and offer general guidance based on what the user describes.\n\n"
    "Keep your advice practical and specific. Cite the source of your information "
    "when you have it (e.g., 'According to the care data for your monstera...')."
)

# ──────────────────────────────────────────────
# Tool dispatch
#
# This is already complete. It routes tool calls from the LLM to the actual
# Python functions in tools.py, and returns results as JSON strings (which is
# what the Groq API expects for tool results).
# ──────────────────────────────────────────────

def dispatch_tool(tool_name: str, tool_args: dict) -> str:
    """Route a tool call to the correct function and return the result as a JSON string."""
    print(f"  → Tool call: {tool_name}({tool_args})")
    if tool_name == "lookup_plant":
        result = lookup_plant(tool_args["plant_name"])
    elif tool_name == "get_seasonal_conditions":
        result = get_seasonal_conditions(tool_args.get("season"))
    else:
        result = {"error": f"Unknown tool: {tool_name}"}
    print(f"  ← Result: {json.dumps(result)[:120]}{'...' if len(json.dumps(result)) > 120 else ''}")
    return json.dumps(result)


# ──────────────────────────────────────────────
# Agent loop
# ──────────────────────────────────────────────

def run_agent(user_message: str, history: list) -> str:
    """
    Run the plant care agent for one user turn and return its response.

    TODO — Milestone 2:

    The agent loop follows a specific pattern that you'll implement here. Read
    specs/agent-loop-spec.md carefully before writing any code — understand the
    full loop before implementing any part of it.

    The loop works like this:
      1. Build a messages list: system prompt + conversation history + new user message
      2. Call the LLM with messages and TOOL_DEFINITIONS
      3. If the response contains tool_calls:
           a. Append the assistant message (with tool_calls) to messages
           b. For each tool call: execute via dispatch_tool(), append the result
           c. Call the LLM again with the updated messages
           d. Repeat until no more tool_calls (or MAX_TOOL_ROUNDS is reached)
      4. Return the final text response

    Key details to get right:
      - The assistant message must be appended BEFORE tool results
      - Tool result messages use role="tool" with a tool_call_id field
      - Append the assistant's message object directly (not just its content)
      - The history format from Gradio: list of [user_message, assistant_message] pairs

    Before writing code, complete specs/agent-loop-spec.md.
    """
    # 1. Build the messages list: system prompt + replayed history + new message.
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Gradio's ChatInterface(type="messages") passes history as a list of
    # {"role", "content"} dicts; the older API passes [user, assistant] pairs.
    # Handle both so the agent works regardless of how it's wired up.
    for item in history:
        if isinstance(item, dict):
            if item.get("role") in ("user", "assistant") and item.get("content"):
                messages.append({"role": item["role"], "content": item["content"]})
        else:
            user_msg, assistant_msg = item
            messages.append({"role": "user", "content": user_msg})
            if assistant_msg:
                messages.append({"role": "assistant", "content": assistant_msg})

    messages.append({"role": "user", "content": user_message})

    try:
        # 2. Tool-calling loop, capped by MAX_TOOL_ROUNDS to prevent runaway loops.
        for _ in range(MAX_TOOL_ROUNDS):
            response = _create_completion(messages, use_tools=True)
            assistant_message = response.choices[0].message

            # Exit condition (a): no tool calls means the LLM has a final answer.
            if not assistant_message.tool_calls:
                return assistant_message.content or (
                    "Sorry, I wasn't able to put together a response. "
                    "Could you rephrase your plant question?"
                )

            # Assistant message (with tool_calls) MUST be appended before results,
            # so each tool result's tool_call_id can be matched to its request.
            messages.append(assistant_message)

            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                # Arguments arrive as a JSON string. For a no-arg call the model
                # may send "", "null", or "{}" — normalize all of these to an
                # empty dict so dispatch_tool always receives a dict to .get() from.
                raw_args = tool_call.function.arguments
                tool_args = json.loads(raw_args) if raw_args else {}
                if not isinstance(tool_args, dict):
                    tool_args = {}
                tool_result = dispatch_tool(tool_name, tool_args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                })

        # Exit condition (b): hit MAX_TOOL_ROUNDS. Ask the model once more for a
        # final answer with the context gathered, forbidding further tool calls.
        final = _create_completion(messages, use_tools=False)
        return final.choices[0].message.content or (
            "I gathered some information but couldn't finish forming an answer. "
            "Please try asking your question again."
        )
    except Exception as error:
        # Output contract: never return empty. Surface a friendly message and
        # log the real error to the terminal for debugging.
        print(f"  ! Agent error: {error}")
        return (
            "Sorry — I ran into a problem while answering that. "
            "Please try asking again in a moment."
        )
