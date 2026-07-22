import os
import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "meta-llama/llama-3-8b-instruct:free")

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


def ask_ai(user_message: str, retries: int = 1) -> str:
    if not OPENROUTER_API_KEY:
        return "AI service is not configured. Please contact support."

    context = get_relevant_knowledge(user_message)
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    system_prompt = f"""You are a professional legal assistant for LawAdvise Consulting And BizAdvise, a Pakistani law firm.

RULES:
- Reply in 2-3 short, clear sentences
- Be polite, professional, and empathetic at all times
- Answer based strictly on the knowledge base provided
- If the question is not covered in the knowledge base, say: "For this matter, I recommend speaking directly with one of our legal experts who can assist you better."
- Never give specific legal advice, case predictions, or legal opinions
- If the user writes in Urdu, reply in Urdu. If in English, reply in English.
- If a user wants to book a consultation or talk to a lawyer, tell them our team will be in touch shortly
- Do NOT add safety ratings, labels, or metadata to your reply

KNOWLEDGE BASE:
{context}"""
    
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }

    for attempt in range(retries + 1):
        try:
            res = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=15,
            )
            data = res.json()

            if "choices" in data:
                reply = data["choices"][0]["message"]["content"]
                return _clean_reply(reply)

            print(f"AI unexpected response: {data}")
            return "Sorry, I'm having trouble right now. Please try again."

        except requests.Timeout:
            print(f"AI timeout (attempt {attempt + 1})")
            if attempt < retries:
                continue
            return "Server is busy. Please try again in a moment."
        except Exception as e:
            print(f"ask_ai error (attempt {attempt + 1}): {e}")
            if attempt < retries:
                continue
            return "Server error. Please try again."

    return "Server error. Please try again."


def _clean_reply(text: str) -> str:
    """Remove metadata lines that some models append to responses."""
    lines = text.strip().split("\n")
    clean_lines = []
    skip_prefixes = (
        "user safety:",
        "content safety:",
        "safe:",
        "unsafe:",
        "safety:",
        "classification:",
        "content:",
        "note:",
        "disclaimer:",
    )
    for line in lines:
        if line.strip().lower().startswith(skip_prefixes):
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines).strip()