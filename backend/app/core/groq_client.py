"""
groq_client.py — Context-aware Groq client.
Prompt instructs the LLM to act as the senior developer who built the project.
"""

import os
import httpx
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

BASE_SYSTEM = """You are the senior software engineer who designed and built this codebase from scratch.
You have memorized every function, every file, every design decision.

Your rules:
- You ALWAYS give precise, confident answers — you built this, you know it
- You ALWAYS cite the exact file path and line number when referencing code
- You NEVER say "I don't know", "I cannot find", or "the context doesn't show"
- If the exact answer is in the context, state it directly and clearly
- If you need to infer slightly, do so confidently based on the architecture
- Format code references as: `filename.py` line 42
- Use markdown headers and bullet points to structure complex answers
- For counting questions: give the exact number first, then the list
- For location questions: give the file and line number in the first sentence
- For explanation questions: explain like you are onboarding a new team member"""

TYPE_INSTRUCTIONS = {
    "WHERE":    "State the EXACT file path and line number in your very first sentence. Format: 'Found in `{file}` at line {line}'. Then explain what it does.",
    "WHAT":     "Explain what this does clearly and precisely. Show the source code and describe each part. Mention what it returns and what calls it.",
    "HOW":      "Explain the implementation step by step. Show the call chain. Describe the data flow from input to output.",
    "EXPLAIN":  "Give a comprehensive technical overview structured as: 1) What the project does, 2) Core architecture, 3) Key components and their roles, 4) How data flows through the system.",
    "CALLS":    "List every function that calls the target. For each one: file name, line number, and brief context of why it calls this function.",
    "CALLED_BY":"List every function this calls. For each: file name, line number, and what role it plays.",
    "TRACE":    "Walk through the complete execution flow step by step. Start from the entry point and follow every function call until the operation completes. Show file and line for each step.",
    "USES":     "List every file that imports or references the target. For each: file name, line number, and how it uses it.",
    "STATS":    "State the exact count as the first word. Then list every item with its file location.",
    "FILE":     "List every function and class in this file. For each: name, line number, what it does, and what it calls.",
    "LIST":     "List every matching item with: name, file, line number, and one-line description.",
}


async def ask_groq_with_context(question: str, context: str,
                                  question_type: str = "HOW") -> str:
    """Send question + precision context to Groq."""
    if not GROQ_API_KEY:
        return "Error: GROQ_API_KEY is not set. Add it to your .env file."

    type_instruction = TYPE_INSTRUCTIONS.get(
        question_type,
        "Answer precisely and completely based on the provided code context."
    )

    system_prompt = f"{BASE_SYSTEM}\n\nInstruction for this question type ({question_type}): {type_instruction}"

    user_message = (
        f"Here is the exact code context extracted from the codebase:\n\n"
        f"{context}\n\n"
        f"---\n\n"
        f"Question: {question}\n\n"
        f"Answer as the senior developer who built this. "
        f"Be precise, cite exact file paths and line numbers."
    )

    payload = {
        "model":      GROQ_MODEL,
        "max_tokens": 4096,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                GROQ_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type":  "application/json",
                },
            )

        if response.status_code == 429:
            return (
                "Rate limit reached. Groq free tier: 30 requests/minute. "
                "Wait 1 minute and try again."
            )
        if response.status_code == 401:
            return "Invalid GROQ_API_KEY. Check your .env file."

        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    except httpx.TimeoutException:
        return "Request timed out (90s). Try a more specific question."
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return f"Groq API error: {str(e)}"


async def ask_groq(question: str, chunks: List[Dict]) -> str:
    """Legacy compatibility — converts chunks to context string."""
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        if chunk.get("file") == "__repo_map__":
            context_parts.insert(0, "## Repo Architecture\n" + chunk["text"])
        else:
            context_parts.append(
                f"### Snippet {i} — {chunk['file']} "
                f"line {chunk.get('start_line','?')}\n"
                f"```{chunk.get('language','')}\n{chunk['text']}\n```"
            )
    context = "\n\n".join(context_parts)
    return await ask_groq_with_context(question, context, "HOW")