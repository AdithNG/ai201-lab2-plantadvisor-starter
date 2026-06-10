# Spec: `run_agent()`

**File:** `agent.py`
**Status:** Partially pre-filled — complete the two blank fields before implementing

---

## Purpose

Orchestrate a single conversational turn for the Plant Advisor agent. Given a user message and the conversation history, call the LLM with available tools, execute any tool calls the LLM requests, and return the final text response.

This is the core of what makes Plant Advisor an *agent* rather than a simple chatbot: the ability to decide which tools to call, use their results to inform its response, and loop until it has everything it needs.

---

## Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_message` | `str` | The user's current message |
| `history` | `list` | Gradio conversation history — list of `[user_msg, assistant_msg]` pairs |

**Output:** `str`

The agent's final text response for this turn. Should never be empty — if something goes wrong, return a user-readable fallback message.

---

## Design Decisions

*Read `specs/system-design.md` (especially the "How the Groq Tool Calling API Works" section) before reviewing these. Complete the two blank fields before writing any code.*

---

### Messages list structure

The messages list must start with the system prompt, then replay the conversation
history, then add the new user message. Gradio history is a list of `[user, assistant]`
pairs — convert each pair to two API-format dicts:

```python
messages = [{"role": "system", "content": SYSTEM_PROMPT}]

for user_msg, assistant_msg in history:
    messages.append({"role": "user", "content": user_msg})
    if assistant_msg:
        messages.append({"role": "assistant", "content": assistant_msg})

messages.append({"role": "user", "content": user_message})
```

---

### Initial LLM call

Pass the model, the messages list, the tool definitions, and `tool_choice="auto"`
so the LLM can decide whether to call a tool or respond directly:

```python
response = client.chat.completions.create(
    model=LLM_MODEL,
    messages=messages,
    tools=TOOL_DEFINITIONS,
    tool_choice="auto",
)
```

---

### Detecting tool calls in the response

The response object has a `choices` list. Index 0 gives the assistant message.
Check its `tool_calls` attribute — if it's truthy, the LLM wants to call tools:

```python
assistant_message = response.choices[0].message

if not assistant_message.tool_calls:
    # No tool calls — LLM has a final answer
    ...
```

---

### Appending the assistant message

When there are tool calls, append the full assistant message object to `messages`
**before** appending any tool results. The API requires this ordering — a tool
result message must immediately follow the assistant message that requested it:

```python
messages.append(assistant_message)  # must come first
```

---

### Executing and appending tool results

For each tool call, extract the name and arguments, call `dispatch_tool()`, and
append the result as a `"tool"` role message. The `tool_call_id` links this result
back to the specific tool call that requested it:

```python
for tool_call in assistant_message.tool_calls:
    tool_name = tool_call.function.name
    tool_args = json.loads(tool_call.function.arguments)
    tool_result = dispatch_tool(tool_name, tool_args)

    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": tool_result,
    })
```

---

### Loop termination conditions

*The loop should stop when: (a) the LLM returns a response with no tool calls, OR (b) the MAX_TOOL_ROUNDS limit is reached. Describe how you will detect each condition and what you will return in each case.*

```
The loop is a `for _ in range(MAX_TOOL_ROUNDS):` — the range cap is the safety
valve, so the loop can never spin forever even if a tool keeps returning empty
results.

(a) No tool calls: each iteration checks `assistant_message.tool_calls`. If it's
    falsy, the LLM is done — return `assistant_message.content`. Guard against a
    None/empty content by returning a friendly fallback string instead of "".

(b) MAX_TOOL_ROUNDS reached: if the for-loop runs to completion (the LLM was
    still requesting tools on the last allowed round), make ONE final call with
    tool_choice="none" to force a text answer from the context gathered so far,
    and return that. This degrades gracefully instead of crashing or returning
    a half-finished tool-call message. Also guarded with a fallback string.
```

---

### Extracting the final text response

*Once the loop exits because there are no more tool calls, how do you extract the text content from the response object? What field holds the string you should return?*

```
The text is at: response.choices[0].message.content

choices is a list (the API can return multiple completions); index 0 is the one
we want. Its .message is the assistant message object, and .content is the final
answer string. NOT .tool_calls and NOT the raw message object — returning either
of those is the classic "empty string / wrong content" bug.
```

---

## Implementation Notes

*Fill this in after implementing and testing.*

**Trace of a working agent turn (what tools were called and in what order):**

```
Query: "How should I water my monstera this time of year?"
Round 1 tool call: lookup_plant({'plant_name': 'monstera'})  -> found: True
Round 1 tool call: get_seasonal_conditions({})               -> Summer, detected_season: True
Round 2: no tool calls -> LLM returns final answer
Final response: Cites the monstera's "water when top 2 inches dry" guidance and
connects it to summer (water more frequently, watch for root rot, keep humidity
high). Both tools fired in one round; the second round produced the text answer.
```

**What happens when you ask about a plant that isn't in the database?**

```
Query: "How do I care for my string of pearls?"
lookup_plant returns found: False with the not-found message. The LLM reads that
message and degrades gracefully: it acknowledges the plant isn't in the database,
offers general succulent care guidance, and points to a reliable source — without
inventing specific watering/light figures. get_seasonal_conditions is not called.
```

**One thing about the tool call API that surprised you:**

```
Two things the happy-path spec didn't anticipate, both found by running it:

1. For a no-argument tool call, the model doesn't always send "{}" — it sent the
   JSON string "null", which json.loads() turns into None, breaking dispatch_tool
   (which expects a dict). The loop normalizes empty/null/non-dict args to {}.

2. llama-3.3-70b on Groq INTERMITTENTLY emits a malformed tool call (e.g.
   "<function=lookup_plant({...})</function>") that the server rejects with a 400
   'tool_use_failed'. Same query, same input — works most times, fails some. The
   fix is to retry the request (it's transient), wrapped in _create_completion().

Also: Gradio's ChatInterface(type="messages") passes history as {"role","content"}
dicts, NOT the [user, assistant] pairs the spec assumed — the replay handles both.
And the dispatch_tool "→" arrow crashes Windows cp1252 stdout, so the entry point
reconfigures stdout to UTF-8. The whole loop is wrapped in try/except returning a
friendly fallback, honoring the "never return empty" output contract.
```
