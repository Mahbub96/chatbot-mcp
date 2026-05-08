from __future__ import annotations

import re
from typing import Any

MIN_MEMORY_FACT_CONFIDENCE = 0.75


def select_context_memories(user_text: str, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_query = (user_text or "").strip().lower()
    selected: list[dict[str, Any]] = []
    for item in memories:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        if is_low_quality_memory_text(text):
            continue
        if normalized_query and text.lower() == normalized_query:
            continue
        source = (item.get("source") or "").strip().lower()
        if source == "chat_assistant":
            if len(text) > 500:
                continue
            if text.startswith("I ") and ("don't have" in text.lower() or "couldn't find" in text.lower()):
                continue
            if float(item.get("importance") or 0.0) < 0.4:
                continue
        if has_question_like_shape(text):
            continue
        selected.append(item)
        if len(selected) >= 5:
            break
    return selected


def has_question_like_shape(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if cleaned.endswith("?") or cleaned.endswith("؟"):
        return True
    lower = cleaned.lower()
    return lower.startswith(("what ", "who ", "where ", "when ", "why ", "how ", "can ", "should "))


def is_low_quality_memory_text(text: str) -> bool:
    lower = (text or "").strip().lower()
    if not lower:
        return True
    bad_signals = (
        "### task:",
        "<chat_history>",
        "json format:",
        "follow_ups",
        "guidelines:",
        "output:",
    )
    if any(sig in lower for sig in bad_signals):
        return True
    if len(lower) > 500:
        return True
    return False


def text_token_overlap(a: str, b: str) -> float:
    a_tokens = set(re.findall(r"\w+", (a or "").lower()))
    b_tokens = set(re.findall(r"\w+", (b or "").lower()))
    if not a_tokens or not b_tokens:
        return 0.0
    inter = len(a_tokens.intersection(b_tokens))
    return inter / max(1, min(len(a_tokens), len(b_tokens)))


def detect_fact_slots(text: str) -> set[str]:
    t = (text or "").lower()
    slots: set[str] = set()
    if any(k in t for k in ("university", "varsity", "বিশ্ববিদ্যাল", "univ")):
        slots.add("university")
    if any(k in t for k in ("name", "nam", "নাম")):
        slots.add("name")
    if any(k in t for k in ("favorite", "favourite", "fav", "প্রিয়", "pochondo")):
        slots.add("favorite")
    if any(k in t for k in ("hobby", "hobbie", "শখ")):
        slots.add("hobby")
    if any(k in t for k in ("cv", "resume", "biodata", "curriculum vitae")):
        slots.add("cv")
    if any(k in t for k in ("email", "mail", "ইমেইল")):
        slots.add("email")
    if any(
        k in t
        for k in (
            "office",
            "work",
            "company",
            "employer",
            "job",
            "role",
            "experience",
            "profession",
            "occupation",
            "career",
            "designation",
            "কাজ",
            "অফিস",
            "পেশা",
        )
    ):
        slots.add("work")
    return slots


def source_priority(source: str) -> int:
    s = (source or "").strip().lower()
    if s == "profile_fact":
        return 100
    if s == "manual":
        return 90
    if s == "profile_full":
        return 80
    if s == "chat_user":
        return 40
    if s == "chat_assistant":
        return 10
    return 20


def has_slot_match(query_text: str, memory_text: str) -> bool:
    q_slots = detect_fact_slots(query_text)
    if not q_slots:
        return True
    m_slots = detect_fact_slots(memory_text)
    # Prioritize specific slots over generic "name" matches.
    for preferred in ("university", "email", "work", "hobby", "favorite", "cv", "name"):
        if preferred in q_slots:
            return preferred in m_slots
    return len(q_slots.intersection(m_slots)) > 0


def is_cv_query(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ("cv", "resume", "biodata", "curriculum vitae"))


def is_exact_cv_request(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if not is_cv_query(t):
        return False
    exact_signals = (
        "exactly my cv",
        "my full cv",
        "entire cv",
        "full resume",
        "show my cv",
        "give me my cv",
        "amar cv",
        "amar full cv",
        "exact cv",
    )
    return any(s in t for s in exact_signals)


def is_exact_shared_request(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    exact_signals = (
        "exactly what i shared",
        "show what i shared",
        "what i shared earlier",
        "give me what i shared",
        "full text i shared",
        "shared earlier",
        "previously shared",
        "আগে যা শেয়ার করেছি",
        "আমি যা শেয়ার করেছি",
    )
    return any(sig in t for sig in exact_signals)


def is_shared_summary_request(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    summary_signals = ("summary", "summarize", "summarise", "in short", "brief", "সংক্ষেপ", "সারাংশ")
    shared_signals = ("what i shared", "shared information", "my information", "that information", "আমি যা শেয়ার")
    return any(s in t for s in summary_signals) and any(s in t for s in shared_signals)


def build_exact_cv_response(cv_text: str) -> str:
    return "Here is your saved full CV text from local memory:\n\n" + cv_text


def pick_best_shared_memory(memories: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not memories:
        return None
    priority = {
        "profile_full": 100,
        "manual": 90,
        "chat_user": 80,
        "profile_fact": 50,
        "chat_assistant": 30,
    }
    ranked = sorted(
        memories,
        key=lambda m: (
            priority.get((m.get("source") or "").strip().lower(), 10),
            len((m.get("text") or "").strip()),
            float(m.get("importance") or 0.0),
            float(m.get("score") or 0.0),
        ),
        reverse=True,
    )
    for item in ranked:
        if len((item.get("text") or "").strip()) >= 20:
            return item
    return ranked[0]


def build_exact_shared_response(item: dict[str, Any]) -> str:
    text = (item.get("text") or "").strip()
    source = (item.get("source") or "unknown").strip()
    return f"Here is the exact content I found from your saved memory ({source}):\n\n{text}"


def build_shared_summary_response(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return "I couldn't find relevant shared information in local memory yet."
    lines: list[str] = []
    seen: set[str] = set()
    for item in memories:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        source = (item.get("source") or "").strip().lower()
        if source == "chat_assistant" and len(text) > 300:
            continue
        snippet = " ".join(text.split())
        if len(snippet) > 160:
            snippet = snippet[:157] + "..."
        key = snippet.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {snippet}")
        if len(lines) >= 8:
            break
    if not lines:
        return "I found memory entries, but none were clean enough to summarize safely."
    return "Here is a concise summary of what you shared earlier:\n" + "\n".join(lines)


def is_offer_intent_query(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    offer_signals = (
        "may i share",
        "can i share",
        "may i send",
        "can i send",
        "may i provide",
        "can i provide",
        "may i upload",
        "can i upload",
        "should i share",
        "should i send",
        "i want to share",
        "i want to send",
        "let me share",
        "let me send",
        "ami share korte pari",
        "ami pathate pari",
        "ami dibo",
    )
    return any(sig in t for sig in offer_signals)


def build_offer_intent_answer() -> str:
    return (
        "Yes, please share it. I will store what is useful, keep exact facts clearly marked, "
        "and label uncertain assumptions transparently."
    )


def is_user_profile_summary_query(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    patterns = (
        "everything you know about me",
        "what do you know about me",
        "tell me about me",
        "all information about me",
        "all info about me",
        "আমার সম্পর্কে",
        "আমাকে নিয়ে যা জানো",
    )
    return any(p in t for p in patterns)


def build_user_profile_summary(memories: list[dict[str, Any]]) -> str:
    allowed_keys = {
        "name",
        "full name",
        "email",
        "phone",
        "mobile",
        "location",
        "education",
        "university",
        "experience",
        "skills",
        "summary",
        "objective",
        "website",
    }
    core_keys = {
        "name",
        "full name",
        "email",
        "phone",
        "mobile",
        "location",
        "education",
        "university",
        "experience",
        "skills",
    }
    by_key: dict[str, list[tuple[str, int, float]]] = {}
    has_full_profile = False
    for item in memories:
        source = (item.get("source") or "").strip().lower()
        text = (item.get("text") or "").strip()
        if not text:
            continue
        if source == "profile_full":
            has_full_profile = True
            continue
        if ":" not in text:
            continue
        key, value = text.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key not in allowed_keys or not value:
            continue
        score = source_priority(source)
        importance = float(item.get("importance") or 0.0)
        by_key.setdefault(key, []).append((value, score, importance))

    if not by_key and not has_full_profile:
        return "I couldn't find reliable saved profile information in local memory yet."

    selected_lines: list[str] = []
    conflict_notes: list[str] = []
    keys_in_order = [
        "name",
        "full name",
        "email",
        "phone",
        "mobile",
        "location",
        "education",
        "university",
        "experience",
        "skills",
        "website",
    ]
    for key in keys_in_order:
        entries = by_key.get(key, [])
        if not entries:
            continue
        unique_map: dict[str, tuple[int, float]] = {}
        for value, score, importance in entries:
            prev = unique_map.get(value)
            if prev is None or (score, importance) > prev:
                unique_map[value] = (score, importance)
        ranked = sorted(unique_map.items(), key=lambda x: (x[1][0], x[1][1]), reverse=True)
        best_value = ranked[0][0]
        if key == "website" and any(k in by_key for k in core_keys):
            continue
        selected_lines.append(f"- {key}: {best_value}")
        if len(ranked) > 1 and key in {"name", "full name", "email", "university"}:
            alternatives = ", ".join(v for v, _ in ranked[1:3])
            conflict_notes.append(f"- conflict on {key}: primary={best_value}; also_found={alternatives}")

    lines = ["Here is what I found in your local memory:"]
    lines.extend(selected_lines[:12])
    if conflict_notes:
        lines.append("I also found conflicting values that need your confirmation:")
        lines.extend(conflict_notes)
    if has_full_profile:
        lines.append("- full profile/CV text is also saved")
    return "\n".join(lines)


def build_cv_context_answer(memories: list[dict[str, Any]]) -> str | None:
    if not memories:
        return None
    fact_lines: list[str] = []
    has_full_cv = False
    seen_facts: set[str] = set()
    allowed_fact_keys = {
        "name",
        "full name",
        "email",
        "phone",
        "mobile",
        "website",
        "linkedin",
        "github",
        "location",
        "education",
        "university",
        "experience",
        "skills",
        "summary",
        "objective",
    }
    for item in memories[:8]:
        source = (item.get("source") or "").strip().lower()
        text = (item.get("text") or "").strip()
        if not text:
            continue
        if source == "profile_full":
            has_full_cv = True
            continue
        if ":" in text and len(text) < 180:
            key = text.split(":", 1)[0].strip().lower()
            if key not in allowed_fact_keys:
                continue
            normalized = text.lower().strip()
            if normalized in seen_facts:
                continue
            seen_facts.add(normalized)
            fact_lines.append(text)
    if fact_lines:
        joined = "; ".join(fact_lines[:4])
        if has_full_cv:
            return f"Saved facts for your CV: {joined}. I also have full CV text saved."
        return f"Saved facts for your CV: {joined}."
    if has_full_cv:
        return "I have full CV text saved in memory; extracted exact facts are limited right now."
    return None


def matched_memories_for_query(query_text: str, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query = (query_text or "").strip()
    if not query:
        return []
    q_slots = detect_fact_slots(query)
    matched: list[dict[str, Any]] = []
    for item in memories:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        src = (item.get("source") or "").strip().lower()
        if is_cv_query(query) and src == "profile_fact":
            matched.append(item)
            continue
        if not has_slot_match(query, text):
            continue
        if (
            src != "profile_full"
            and text_token_overlap(query, text) < 0.12
            and detect_fact_slots(query)
        ):
            continue
        if q_slots.intersection({"name", "university", "email"}):
            if src == "chat_assistant":
                continue
            if src == "chat_user" and ":" not in text:
                continue
        matched.append(item)
    matched.sort(
        key=lambda x: (
            source_priority(str(x.get("source") or "")),
            float(x.get("importance") or 0.0),
            float(x.get("score") or 0.0),
        ),
        reverse=True,
    )
    return matched


def build_memory_fallback_answer(user_text: str, memories: list[dict[str, Any]]) -> str | None:
    if not is_personal_memory_query(user_text):
        return None
    if not memories:
        return None
    query_slots = detect_fact_slots(user_text)
    for item in memories:
        top_text = (item.get("text") or "").strip()
        source = (item.get("source") or "").strip().lower()
        confidence = float(item.get("confidence") or 0.0)
        if confidence < MIN_MEMORY_FACT_CONFIDENCE:
            continue
        if not top_text or is_low_quality_memory_text(top_text) or has_question_like_shape(top_text):
            continue
        if not has_slot_match(user_text, top_text):
            continue
        # For slot-specific questions, avoid dumping full documents unless we can extract
        # a concise slot-related snippet (important for work/role info often stored in CV text).
        if query_slots and source == "profile_full":
            # Keep concise fact preference for most slots; use profile_full extraction
            # primarily for work/role info that is often only present in resume text.
            if "work" in query_slots:
                extracted = extract_profile_full_slot_fact(user_text, top_text)
                if extracted:
                    return f"Saved fact: {extracted}"
            continue
        if query_slots and ":" not in top_text and len(top_text) > 180:
            continue
        if ":" in top_text:
            return f"Saved fact: {top_text}"
        if "work" in query_slots:
            extracted_work = extract_work_fact_from_text(top_text)
            if extracted_work:
                return f"Saved fact: {extracted_work}"
        return f"Possible memory (not fully verified): {top_text}"
    return None


def extract_work_fact_from_text(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    compact = " ".join(raw.split())
    patterns = (
        r"(?i)\bmy profession is ([^.]{2,120})",
        r"(?i)\bi work as ([^.]{2,120})",
        r"(?i)\bi work at ([^.]{2,120})",
        r"(?i)\brole\s*[:=-]\s*([^.]{2,120})",
        r"(?i)\bcompany\s*[:=-]\s*([^.]{2,120})",
    )
    for pattern in patterns:
        match = re.search(pattern, compact)
        if not match:
            continue
        value = (match.group(1) or "").strip(" ,.;:-")
        if not value:
            continue
        lowered = pattern.lower()
        if "work at" in lowered or "company" in lowered:
            return f"company: {value}"
        return f"profession: {value}"
    if any(k in compact.lower() for k in ("engineer", "developer", "manager", "analyst")):
        return f"profession: {compact}"
    return None


def extract_profile_full_slot_fact(query_text: str, profile_text: str) -> str | None:
    slots = detect_fact_slots(query_text)
    if not slots:
        return None
    raw = (profile_text or "").strip()
    if not raw:
        return None
    normalized = " ".join(raw.replace("\\n", "\n").split())
    if len(normalized) > 3000:
        normalized = normalized[:3000]
    lower = normalized.lower()
    slot_keywords: dict[str, tuple[str, ...]] = {
        "work": ("work", "worked", "office", "company", "employer", "role", "experience", "brotecs"),
        "university": ("university", "education", "varsity", "campus"),
        "email": ("email", "@"),
        "name": ("name", "full name"),
        "hobby": ("hobby", "interests"),
        "favorite": ("favorite", "favourite"),
    }
    for slot in ("work", "university", "email", "name", "hobby", "favorite"):
        if slot not in slots:
            continue
        keywords = slot_keywords.get(slot, ())
        candidates: list[tuple[int, str]] = []
        segments = re.split(r"[.;]|\\section\*?\{[^}]*\}|\\entryheader\{[^}]*\}\{[^}]*\}", normalized)
        for seg in segments:
            snippet = " ".join(seg.split()).strip(" ,.;:-")
            if len(snippet) < 12:
                continue
            s_lower = snippet.lower()
            if not any(kw in s_lower for kw in keywords):
                continue
            if slot == "work":
                score = 0
                if any(k in s_lower for k in ("worked", "work", "company", "employer", "role", "experience", "brotecs", "technologies", "software engineer")):
                    score += 4
                if any(k in s_lower for k in ("year", "years", "month", "present")):
                    score += 2
                if "@" in s_lower:
                    score -= 3
                if "education" in s_lower:
                    score -= 2
                if score <= 0:
                    continue
                candidates.append((score, snippet))
            else:
                candidates.append((1, snippet))
        if candidates:
            candidates.sort(key=lambda x: (x[0], len(x[1])), reverse=True)
            best = candidates[0][1]
            best = re.sub(r"\\[a-zA-Z]+\*?\{", "", best)
            best = best.replace("}", " ")
            best = " ".join(best.split())
            return best.strip(" ,.;:-")
    return None


def build_memory_first_answer(user_text: str, memories: list[dict[str, Any]]) -> str | None:
    if not is_personal_memory_query(user_text):
        return None
    if not memories:
        return None
    query = (user_text or "").strip()
    if not query:
        return None
    top = memories[0]
    top_source = (top.get("source") or "").strip().lower()
    top_text = (top.get("text") or "").strip()
    top_confidence = float(top.get("confidence") or 0.0)
    if top_confidence < MIN_MEMORY_FACT_CONFIDENCE:
        return None
    if not top_text or is_low_quality_memory_text(top_text):
        return None
    if top_source == "chat_assistant" or has_question_like_shape(top_text) or len(top_text) > 400:
        return None
    if top_source not in {"profile_fact", "manual"} and (top.get("score") or 0.0) < 0.6:
        return None
    if not has_slot_match(query, top_text):
        return None
    if top_source not in {"profile_fact", "manual"} and text_token_overlap(query, top_text) < 0.2:
        return None
    if ":" in top_text:
        return f"Saved fact: {top_text}"
    return f"Possible memory (not fully verified): {top_text}"


def is_personal_memory_query(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    personal_signals = (
        "my ",
        "amar ",
        "আমার",
        "name",
        "nam",
        "hobby",
        "cv",
        "resume",
        "university",
        "email",
        "office",
        "work",
        "company",
        "employer",
        "role",
        "where i work",
        "profession",
        "occupation",
        "career",
        "designation",
        "পেশা",
    )
    return any(sig in t for sig in personal_signals)


def build_memory_missing_answer(user_text: str) -> str | None:
    if not is_personal_memory_query(user_text):
        return None
    return "I couldn't find an exact saved fact for this yet. If you share it once, I will store it as a fact for next time."


def should_reject_personal_answer(
    *,
    user_text: str,
    response_text: str,
    memories: list[dict[str, Any]],
) -> bool:
    query = (user_text or "").strip().lower()
    answer = (response_text or "").strip().lower()
    if not query or not answer:
        return False
    if not is_personal_memory_query(query):
        return False
    # If the model is already uncertain, keep it (safe behavior).
    uncertainty_markers = (
        "i don't have",
        "i do not have",
        "i'm not sure",
        "i am not sure",
        "not enough information",
        "couldn't find",
    )
    if any(marker in answer for marker in uncertainty_markers):
        return False

    query_slots = detect_fact_slots(query)
    answer_slots = detect_fact_slots(answer)
    if query_slots and not query_slots.intersection(answer_slots):
        return True

    # Profession/work questions must not be answered with plain link-only facts.
    if "work" in query_slots:
        if any(tok in answer for tok in ("linkedin.com", "http://", "https://", "www.")):
            work_terms = ("engineer", "developer", "manager", "analyst", "role", "company", "employer", "work")
            if not any(term in answer for term in work_terms):
                return True

    # Guard against answers unrelated to top matched memory content.
    if memories:
        top = memories[0]
        top_text = (top.get("text") or "").strip()
        if top_text and text_token_overlap(answer, top_text) < 0.08 and query_slots:
            return True
    return False


def user_disputes_identity(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    signals = ("i am not", "that's not me", "not my name", "i'm not", "আমি না", "আমি নই", "ওটা আমি না")
    return any(sig in t for sig in signals)


def build_identity_dispute_answer() -> str:
    return (
        "Understood — thanks for correcting me. Please share your correct name "
        "(and any profile details you want me to keep), and I will update memory accordingly."
    )


def looks_like_structured_document_text(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if len(t) > 700:
        return True
    signals = ("\\documentclass", "\\begin{document}", "\\section", "curriculum vitae", "resume", "latex")
    return sum(1 for s in signals if s in t) >= 2


def build_document_ingest_ack() -> str:
    return (
        "Thanks — I received your structured CV/profile text and saved it to memory "
        "(including full text and extracted facts)."
    )

