# models

LM interfaces. Each model class turns a list of messages into the next action, tracks token
cost, and formats observations back into messages. Selection happens in `__init__.py` via
`get_model_class(model_name, model_class)`; `model_class` (a shortcut name from the table below or
a full import path) wins over `model_name`.

## Model classes

`model_class` shortcut -> class. Set it in the agent config's `model:` block.

| `model_class`          | Class                    | Transport | Action format                          |
| ---------------------- | ------------------------ | --------- | -------------------------------------- |
| `litellm`              | `LitellmModel`           | litellm   | native tool calls (`BASH_TOOL`)        |
| `litellm_textbased`    | `LitellmTextbasedModel`  | litellm   | regex from text (```` ```mswea_bash_command ````) |
| `litellm_response`     | `LitellmResponseModel`   | litellm   | Responses API                          |
| `openrouter`           | `OpenRouterModel`        | OpenRouter| tool calls                             |
| `openrouter_textbased` | `OpenRouterTextbasedModel`| OpenRouter| regex from text                        |
| `openrouter_response`  | `OpenRouterResponseModel`| OpenRouter| Responses API                          |
| `portkey`              | `PortkeyModel`           | Portkey   | tool calls                             |
| `portkey_response`     | `PortkeyResponseAPIModel`| Portkey   | Responses API                          |
| `requesty`             | `RequestyModel`          | Requesty  | tool calls                             |
| `deterministic`        | `DeterministicModel`     | none      | test double (see `test_models.py`)     |

`LitellmModel` is the base for the litellm family; `*Config` classes subclass `LitellmModelConfig`,
so the config fields below apply to all litellm-based models (including `litellm_textbased`, which
our slack-clone-course Bedrock/OpenRouter configs use).

## Cost tracking

`_calculate_cost()` calls `litellm.cost_calculator.completion_cost()` and adds the result to
`GLOBAL_MODEL_STATS`. Prices normally come from litellm's built-in model price map, keyed on
`model_name`. Two escape hatches for models the map doesn't know:

- **`litellm_model_registry`** (path, or `LITELLM_MODEL_REGISTRY_PATH` env): a JSON file passed to
  `litellm.utils.register_model()` at init. Registers full model metadata in litellm's map.
- **`input_cost_per_token` / `output_cost_per_token`** (floats, USD/token): when both are set they
  are passed to `completion_cost(..., custom_cost_per_token=...)`. Use this for opaque names that
  aren't in the price map — e.g. a Bedrock `application-inference-profile` ARN
  (`bedrock/converse/arn:...`), which otherwise raises "model isn't mapped yet" and, under
  `cost_tracking: ignore_errors`, silently reports `cost_usd=0.0`.

`cost_tracking: ignore_errors` (or `MSWEA_COST_TRACKING=ignore_errors`) swallows cost errors and
records `0.0` instead of crashing the run. `completion_cost` also treats a `<= 0.0` result as an
error, so an unpriced model still trips `ignore_errors`.

## utils/

Shared helpers, not model classes: `actions_text.py` / `actions_toolcall*.py` (parse actions +
`finish_reason` for format-error templates), `retry.py`, `cache_control.py` (Anthropic prompt
caching), `anthropic_utils.py`, `openai_multimodal.py`, `content_string.py`.

## Conventions

- New model class -> add it to `_MODEL_CLASS_MAPPING` in `__init__.py`.
- `query()` must persist the response and cost on `FormatError` (see the note in `LitellmModel.query`).
- Follow the root style guide: minimal code, type annotations, no unnecessary exception catching.
