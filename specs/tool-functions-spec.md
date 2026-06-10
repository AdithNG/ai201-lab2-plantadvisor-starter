# Spec: Tool Functions

**File:** `tools.py`
**Status:** `get_seasonal_conditions` — Pre-implemented, read through. `lookup_plant` — complete spec fields before implementing.

---

## Purpose

These two functions are the tools the agent can call. They retrieve structured data from the local plant database and seasonal data files and return it to the agent loop, which passes it to the LLM as context for generating a response.

---

## Function 1: `lookup_plant()`

### Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `plant_name` | `str` | The plant name as entered by the user or chosen by the LLM — may be any casing, common name, scientific name, or alias |

**Output:** `dict`

When the plant is **found**, return:
```python
{"found": True, "plant": <the full plant dict from _plant_db>}
```

When the plant is **not found**, return:
```python
{"found": False, "name": <normalized input>, "message": <helpful string>}
```

---

### Design Decisions

*Complete the two blank fields below before writing code. The others are pre-filled for you.*

---

#### Input normalization

Strip leading/trailing whitespace and convert to lowercase before any comparison.

```python
normalized = plant_name.strip().lower()
```

---

#### Search order

Search in this order: direct key → display name → aliases. Keys are the fastest
lookup (O(1) dict access), so check those first. Display names are the next most
likely match for clean user input. Aliases are the broadest net, so they go last.

```
1. Direct key match: normalized in _plant_db
2. Display name match: plant["display_name"].lower() == normalized
3. Alias match: normalized in [alias.lower() for alias in plant["aliases"]]
```

---

#### Alias matching approach

*Aliases are stored as a list of strings. How will you check if the normalized input matches any alias in the list? Write your approach in pseudocode or plain English.*

```
Case-insensitive linear scan over _plant_db, in the order slug -> display name
-> aliases. For each plant, lowercase every alias and test membership:

    normalized in [alias.lower() for alias in plant["aliases"]]

At 15 plants this is trivially fast. If the database grew to thousands of
plants, the scan would be wasteful — I'd build a reverse-index dict ONCE at
module load mapping every lowercased name (slug + display_name + each alias)
to its slug, turning every lookup into a single O(1) dict hit.
```

---

#### Not-found message

*When a plant isn't found, the agent will read your message and use it to decide what to tell the user. Write the exact string you'll return — make it useful to the agent, not just to a human reading logs.*

```
f"'{plant_name}' is not in the plant care database. Do not invent specific
care details for it. Acknowledge that it isn't in the database, then offer
general guidance based on the plant type the user described and suggest a
reliable source."

This message does two jobs: it names the gap AND instructs the LLM not to
hallucinate care figures — which is the layer that drives the Milestone 3
graceful-degradation behavior.
```

---

#### Implementation Notes

*Fill this in after implementing and running the app.*

**Test: does `"devil's ivy"` return the pothos entry?**
```
Yes. Matched via the alias list -> returns {"found": True, "plant": {"display_name": "Pothos", ...}}.
```

**Test: does `"SNAKE PLANT"` return the snake plant entry?**
```
Yes — even as "  SNAKE PLANT  " with surrounding whitespace. strip().lower()
normalizes it to "snake plant", which matches the display name.
```

**One edge case you discovered while implementing:**
```
Aliases contain apostrophes ("devil's ivy", "mother-in-law's tongue"). These
work fine through strip().lower() since only casing/whitespace are normalized,
but they're the reason "devil's ivy" is the canonical correctness check.
```

---

## Function 2: `get_seasonal_conditions()`

### Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `season` | `str \| None` | One of `"spring"`, `"summer"`, `"fall"`, `"winter"`, or `None` to auto-detect |

**Output:** `dict`

The full season dict from `_season_data`, plus one additional field:

| Added field | Type | Value |
|-------------|------|-------|
| `"detected_season"` | `bool` | `True` if auto-detected from the month; `False` if season was passed as an argument |

---

### Design Decisions

*This function is pre-implemented — read through these fields and the code before working on `lookup_plant`.*

---

#### Auto-detection logic

When `season` is `None`, get the current calendar month with `datetime.now().month`
and look it up in the `_MONTH_TO_SEASON` dict, which maps month numbers to season strings.

```python
current_month = datetime.now().month
season_key = _MONTH_TO_SEASON[current_month]
```

---

#### Season validation

If the caller passes an invalid season string (e.g., `"monsoon"`), the function
falls back to auto-detection — same as if `None` were passed. The `VALID_SEASONS`
set acts as the gate:

```python
VALID_SEASONS = {"spring", "summer", "fall", "winter"}
if season and season.lower() in VALID_SEASONS:
    ...  # use provided season
else:
    ...  # auto-detect
```

---

#### Return structure

The full season dict from `_season_data`, plus a `detected_season` boolean. Example for spring:

```python
{
    "season": "spring",
    "watering": "Increase watering frequency as plants break dormancy ...",
    "fertilizing": "Resume feeding with a balanced fertilizer ...",
    "light": "Days are lengthening — move plants closer to windows ...",
    "pests": "Watch for spider mites and aphids as temperatures rise ...",
    "detected_season": True   # True = auto-detected; False = caller specified
}
```

---

#### Implementation Notes

*Fill this in after testing.*

**Test: does calling with `season=None` return the correct season for the current month?**
```
Current month: June (6)
Expected season: Summer
Returned season: Summer (detected_season: True)
```

**Test: does calling with `season="winter"` return winter data regardless of the current month?**
```
Yes — returns Winter with detected_season: False (caller-specified, not auto-detected).
```

---

## Function 3: `get_plant_list()` — Optional Challenge

### Input / Output Contract

**Inputs:** none.

**Output:** `dict`
```python
{"count": <int>, "plants": [{"name": <display_name>, "difficulty": <level>}, ...]}
```

### Design Decisions

- **Why no arguments:** this tool answers "what do you know?" / "recommend by difficulty"
  questions, which don't depend on user input. The tool definition's `properties` is `{}`.
- **Why only name + difficulty (not the full plant dict):** the LLM only needs enough to
  list options or pick by difficulty. Returning every field would bloat the context for no
  benefit — `lookup_plant` is the tool for full detail on one plant.
- **Tool description disambiguation:** the description explicitly says to use `lookup_plant`
  (not this) for a single named plant, so the LLM routes "tell me about my pothos" to the
  right tool and "what plants do you know?" here.

### Implementation Notes
```
"What plants do you know about?" -> calls get_plant_list({}) -> lists all 15.
"What's a good beginner plant?"  -> calls get_plant_list({}) -> recommends Pothos (easy).
Both route correctly; neither triggers lookup_plant. Confirmed in the terminal trace.
```
