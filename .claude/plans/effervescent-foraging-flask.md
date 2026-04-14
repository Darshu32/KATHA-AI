# Add Free LLM API Support (Groq/Gemini/OpenRouter)

## Context
The chat engine uses the OpenAI Python SDK. We need to test the streaming chat without paying for OpenAI. Groq, Google Gemini, and OpenRouter all offer free tiers with OpenAI-compatible endpoints. The OpenAI SDK supports custom `base_url` natively — so we just need to make the base URL configurable.

## Plan

### 1. Add `openai_base_url` to backend config (`backend/app/config.py`)
- Add `openai_base_url: str = "https://api.openai.com/v1"` (defaults to OpenAI)
- For Groq: `https://api.groq.com/openai/v1`
- For OpenRouter: `https://openrouter.ai/api/v1`
- For Gemini: `https://generativelanguage.googleapis.com/v1beta/openai/`

### 2. Update `_get_client()` in both `chat_engine.py` and `ai_orchestrator.py`
- Pass `base_url=settings.openai_base_url` to `AsyncOpenAI()`

### 3. Update `openai_model` default for flexibility
- Groq uses `llama-3.3-70b-versatile`
- Gemini uses `gemini-2.5-flash`
- Keep default as `gpt-4o` but user sets via `.env`

### 4. Update `.env.example` with instructions

### Files to modify
- `backend/app/config.py` — add `openai_base_url`
- `backend/app/services/chat_engine.py` — pass `base_url` to client
- `backend/app/services/ai_orchestrator.py` — pass `base_url` to client

## Verification
1. Set Groq API key + base URL in `.env`
2. Start backend
3. Send a chat message from frontend
4. Verify streaming response appears token-by-token
