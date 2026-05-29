import os
import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "openrouter/free")

_knowledge_cache = None


def load_knowledge():
    global _knowledge_cache
    try:
        with open("knowledge.txt", "r", encoding="utf-8") as f:
            _knowledge_cache = f.read()
            print(f"Knowledge loaded: {len(_knowledge_cache)} chars")
    except FileNotFoundError:
        print("knowledge.txt not found — AI will have no context")
        _knowledge_cache = ""
    except Exception as e:
        print(f"Failed to load knowledge: {e}")
        _knowledge_cache = ""
    return _knowledge_cache


def reload_knowledge():
    global _knowledge_cache
    _knowledge_cache = None
    return load_knowledge()


def get_knowledge():
    global _knowledge_cache
    if _knowledge_cache is None:
        load_knowledge()
    return _knowledge_cache


def get_relevant_knowledge(msg: str) -> str:
    knowledge = get_knowledge()
    if not knowledge:
        return ""
    words = msg.lower().split()
    lines = knowledge.split("\n")
    matched = []
    for line in lines:
        for word in words:
            if word in line.lower():
                matched.append(line)
                break
    return "\n".join(matched)[:800]


def ask_ai(user_message: str) -> str:
    if not OPENROUTER_API_KEY:
        return "AI service is not configured. Please contact support."

    try:
        context = get_relevant_knowledge(user_message)
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        system_prompt = f"""You are a WhatsApp business assistant.
RULES:
- Reply in 1-2 short sentences
- Friendly and natural tone
- Clear and direct
- No long paragraphs
- If asked something outside the knowledge base, say you don't know

KNOWLEDGE:
{context}"""

        payload = {
            "model": AI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }

        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=15,
        )
        data = res.json()

        if "choices" in data:
            return data["choices"][0]["message"]["content"]

        print(f"AI unexpected response: {data}")
        return "Sorry, I'm having trouble right now. Please try again."

    except requests.Timeout:
        print("AI request timed out")
        return "Server is busy. Please try again in a moment."
    except Exception as e:
        print(f"ask_ai error: {e}")
        return "Server error. Please try again."
