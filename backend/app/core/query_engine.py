"""
query_engine.py — Precision query engine with:
1. Full call chain traversal   (TRACE type)
2. Cross-file relationship search (USES type)
3. Stats/counting queries      (STATS type)
4. All original question types preserved
"""

import re
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

from app.core import code_graph
from app.core.code_graph import (
    find_symbol_exact, find_symbol_fuzzy,
    find_callers, find_callees,
    find_in_file, get_top_symbols,
    get_file_summaries, get_repo_stats,
)

logger = logging.getLogger(__name__)


@dataclass
class QuestionIntent:
    question_type: str
    target: Optional[str]
    sub_targets: List[str]
    confidence: float


QUESTION_PATTERNS = {
    "WHERE": [
        r"where is (.+?)(?:\s+(?:defined|implemented|handled|located|found|declared))?\??$",
        r"where (?:can i find|do i find|is) (.+)",
        r"which file (?:contains|has|handles) (.+)",
        r"find (.+?) (?:function|class|method|definition)",
        r"locate (.+)",
        r"in which (?:file|folder|directory) is (.+)",
    ],
    "WHAT": [
        r"what does (.+?) do",
        r"what is (.+?)(?:\?|$)",
        r"explain (?:the )?(.+?) (?:function|class|method|module|component)",
        r"describe (.+)",
        r"tell me about (.+)",
        r"what is the purpose of (.+)",
        r"what does (.+?) return",
    ],
    "HOW": [
        r"how does (.+?) work",
        r"how is (.+?) (?:implemented|done|handled|processed)",
        r"how (?:do|does|can) (?:i |the )?(.+?)(?:\?|$)",
        r"explain how (.+?) works",
        r"walk (?:me )?through (.+)",
    ],
    "EXPLAIN": [
        r"explain (?:the )?(?:core )?(?:logic|architecture|structure|flow|system|overview)",
        r"(?:give me )?(?:an? )?overview of (?:the )?(?:project|codebase|system|app)",
        r"summarize (?:the )?(?:project|codebase|system)",
        r"what does (?:this|the) (?:project|app|system|codebase) do",
        r"explain (?:this|the) (?:project|codebase|system|app)",
    ],
    "CALLS": [
        r"what (?:functions?|methods?) (?:call|calls|invoke|uses?) (.+)",
        r"who calls (.+)",
        r"what calls (.+)",
        r"callers? of (.+)",
        r"where is (.+?) called",
    ],
    "CALLED_BY": [
        r"what does (.+?) call",
        r"what (?:functions?|methods?) does (.+?) (?:call|use|invoke)",
        r"(?:function|method) calls inside (.+)",
        r"what does (.+?) invoke",
    ],
    "TRACE": [
        r"trace (?:the )?(?:flow|path|execution) (?:of |for |from )?(.+)",
        r"full (?:call )?chain (?:of|for) (.+)",
        r"end.to.end flow (?:of|for) (.+)",
        r"execution path (?:of|for) (.+)",
        r"how does data flow (?:through|in) (.+)",
        r"what happens when (.+)",
        r"step by step (?:flow|process) (?:of|for) (.+)",
    ],
    "USES": [
        r"what (?:uses|imports|depends on|references) (.+)",
        r"where is (.+?) (?:used|imported|referenced|called from)",
        r"which (?:files?|components?|modules?) (?:use|import|depend on) (.+)",
        r"who (?:uses|imports) (.+)",
        r"usages? of (.+)",
        r"references? to (.+)",
    ],
    "STATS": [
        r"how many (.+?) (?:are there|exist|do we have|are in|does this|are present)",
        r"count (?:all )?(?:the )?(.+)",
        r"total (?:number of )?(.+)",
        r"number of (.+)",
        r"how many (.+)",
        r"list all (.+?) files",
        r"show all (.+?) files",
    ],
    "LIST": [
        r"list (?:all )?(?:the )?(.+?)s?\s*(?:in the codebase|in this project)?$",
        r"show (?:me )?(?:all )?(?:the )?(.+?)s?$",
        r"find all (.+?)s?",
        r"what (?:are|were) (?:all )?(?:the )?(.+?)s?",
        r"give me all (.+)",
    ],
    "FILE": [
        r"what (?:functions?|methods?|components?|is|are) (?:are )?in (.+?\.(?:py|js|ts|tsx|jsx|java|go|rs|rb|css|scss|mjs|vue))",
        r"what is in (.+?\.(?:py|js|ts|tsx|jsx|java|go|rs|rb|css|scss|mjs|vue))",
        r"show (?:me )?(.+?\.(?:py|js|ts|tsx|jsx|java|go|rs|rb|css|scss|mjs|vue))",
        r"what does (.+?\.(?:py|js|ts|tsx|jsx|java|go|rs|rb|css|scss|mjs|vue)) (?:do|contain|have|export)",
        r"explain (.+?\.(?:py|js|ts|tsx|jsx|java|go|rs|rb|css|scss|mjs|vue))",
        r"describe (.+?\.(?:py|js|ts|tsx|jsx|java|go|rs|rb|css|scss|mjs|vue))",
        r"contents? of (.+?\.(?:py|js|ts|tsx|jsx|java|go|rs|rb|css|scss|mjs|vue))",
        r"inside (.+?\.(?:py|js|ts|tsx|jsx|java|go|rs|rb|css|scss|mjs|vue))",
    ],
}


def classify_question(question: str) -> QuestionIntent:
    q = question.strip().lower().rstrip('?').strip()
    for qtype, patterns in QUESTION_PATTERNS.items():
        for pattern in patterns:
            m = re.search(pattern, q)
            if m:
                target = m.group(1).strip() if m.lastindex else None
                if target:
                    target = re.sub(
                        r'\b(the|a|an|this|that|my|our)\b', '', target
                    ).strip()
                return QuestionIntent(
                    question_type=qtype,
                    target=target,
                    sub_targets=extract_terms(q),
                    confidence=0.9,
                )
    return QuestionIntent(
        question_type="HOW",
        target=extract_main_term(q),
        sub_targets=extract_terms(q),
        confidence=0.5,
    )


def extract_main_term(text: str) -> Optional[str]:
    cleaned = re.sub(
        r'\b(how|what|where|which|who|when|why|does|do|is|are|the|a|an|'
        r'this|that|explain|describe|tell|show|find|list|get|give|me|'
        r'us|i|my|our|your)\b',
        '', text
    ).strip()
    words = [w for w in cleaned.split() if len(w) > 2]
    return words[0] if words else None


def extract_terms(text: str) -> List[str]:
    stop_words = {
        'how', 'what', 'where', 'which', 'who', 'when', 'why',
        'does', 'do', 'is', 'are', 'the', 'a', 'an', 'this', 'that',
        'it', 'its', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
        'and', 'or', 'but', 'not', 'can', 'will', 'should', 'would',
        'work', 'works', 'working', 'handled', 'handle', 'handles',
        'defined', 'define', 'implement', 'implemented', 'function',
        'method', 'class', 'file', 'code', 'codebase', 'there', 'exist',
        'many', 'all', 'total', 'count', 'number', 'present',
    }
    words = re.findall(r'\b[a-zA-Z_]\w*\b', text)
    return [w for w in words if w.lower() not in stop_words and len(w) > 2]


# ─────────────────────────────────────────────────────────────────────────────
# Feature 1 — Full call chain traversal
# ─────────────────────────────────────────────────────────────────────────────

def trace_call_chain(repo_id: str, function_name: str,
                      depth: int = 4) -> List[Dict]:
    """
    Trace the full execution chain from a function.
    Goes DOWN (what it calls) and UP (what calls it).
    """
    visited = set()
    chain   = []

    def _trace_down(name: str, current_depth: int):
        if current_depth <= 0 or name in visited:
            return
        visited.add(name)
        syms = find_symbol_exact(repo_id, name)
        if syms:
            sym = syms[0]
            chain.append({
                "direction":   "calls",
                "depth":        depth - current_depth,
                "name":         sym["name"],
                "file":         sym["file"],
                "line_start":   sym["line_start"],
                "source_code":  sym.get("source_code", ""),
                "language":     sym.get("language", ""),
                "docstring":    sym.get("docstring", ""),
            })
        callees = find_callees(repo_id, name)
        for callee in callees[:5]:
            cn = callee.get("callee_name", "")
            if cn and cn not in visited:
                _trace_down(cn, current_depth - 1)

    def _trace_up(name: str, current_depth: int):
        if current_depth <= 0 or f"up:{name}" in visited:
            return
        visited.add(f"up:{name}")
        callers = find_callers(repo_id, name)
        for caller in callers[:5]:
            cn = caller.get("caller_name", "")
            if cn and f"up:{cn}" not in visited:
                caller_syms = find_symbol_exact(repo_id, cn)
                if caller_syms:
                    sym = caller_syms[0]
                    chain.append({
                        "direction":  "called_by",
                        "depth":       depth - current_depth,
                        "name":        sym["name"],
                        "file":        sym["file"],
                        "line_start":  sym["line_start"],
                        "source_code": sym.get("source_code", ""),
                        "language":    sym.get("language", ""),
                        "docstring":   sym.get("docstring", ""),
                    })
                _trace_up(cn, current_depth - 1)

    _trace_down(function_name, depth)
    _trace_up(function_name, 2)
    return chain


def format_call_chain(chain: List[Dict], root_name: str) -> str:
    if not chain:
        return f"No call chain data found for `{root_name}`."
    lines   = [f"## Execution Flow for `{root_name}`\n"]
    callers = [c for c in chain if c["direction"] == "called_by"]
    callees = [c for c in chain if c["direction"] == "calls"]

    if callers:
        lines.append("### Called by (upstream):")
        for c in callers:
            lines.append(
                f"  📥 `{c['name']}` in `{c['file']}` line {c['line_start']}"
            )
            if c.get("docstring"):
                lines.append(f"     {c['docstring'][:100]}")

    if callees:
        lines.append("\n### Calls downstream:")
        for c in callees:
            indent = "  " * c.get("depth", 0)
            lines.append(
                f"{indent}📤 `{c['name']}` in `{c['file']}` line {c['line_start']}"
            )
            if c.get("docstring"):
                lines.append(f"{indent}   {c['docstring'][:100]}")
            if c.get("source_code"):
                lang = c.get("language", "")
                lines.append(
                    f"{indent}   ```{lang}\n"
                    f"{indent}   {c['source_code'][:600]}\n"
                    f"{indent}   ```"
                )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Feature 2 — Cross-file usage / import search
# ─────────────────────────────────────────────────────────────────────────────

def find_usages(repo_id: str, target: str) -> List[Dict]:
    """Find all files that import or call a given symbol."""
    results = []
    seen    = set()

    with code_graph.get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT file, line, module, names FROM imports
            WHERE repo_id = ?
            AND (LOWER(module) LIKE LOWER(?) OR LOWER(names) LIKE LOWER(?))
            LIMIT 20
        """, (repo_id, f"%{target}%", f"%{target}%")).fetchall()

        for row in rows:
            key = f"{row[0]}:{row[1]}"
            if key not in seen:
                seen.add(key)
                results.append({
                    "file": row[0], "line": row[1],
                    "via":  f"imports from `{row[2]}`",
                    "kind": "import",
                })

        rows = conn.execute("""
            SELECT DISTINCT caller_file, caller_name, caller_line FROM calls
            WHERE repo_id = ? AND LOWER(callee_name) LIKE LOWER(?)
            LIMIT 20
        """, (repo_id, f"%{target}%")).fetchall()

        for row in rows:
            key = f"{row[0]}:{row[2]}"
            if key not in seen:
                seen.add(key)
                results.append({
                    "file": row[0], "line": row[2],
                    "via":  f"`{row[1]}` calls `{target}`",
                    "kind": "call",
                })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Feature 3 — Stats / counting queries
# ─────────────────────────────────────────────────────────────────────────────

def get_stats(repo_id: str, target: str) -> str:
    """Answer counting questions directly from the database."""
    t     = (target or "").lower()
    lines = []

    with code_graph.get_conn() as conn:

        # File extension counts
        ext_map = {
            "tsx": "%.tsx", "jsx": "%.jsx",
            "ts":  "%.ts",  "js":  "%.js",
            "py":  "%.py",  "python": "%.py",
            "java": "%.java", "go": "%.go",
        }

        matched = False
        for keyword, pattern in ext_map.items():
            if keyword in t:
                count = conn.execute(
                    "SELECT COUNT(DISTINCT file) FROM symbols "
                    "WHERE repo_id=? AND file LIKE ?",
                    (repo_id, pattern)
                ).fetchone()[0]
                files = conn.execute(
                    "SELECT DISTINCT file FROM symbols "
                    "WHERE repo_id=? AND file LIKE ? ORDER BY file",
                    (repo_id, pattern)
                ).fetchall()
                lines.append(f"**{keyword.upper()} files: {count}**")
                for f in files:
                    lines.append(f"  - `{f[0]}`")
                matched = True
                break

        if not matched:
            sym_map = {
                "function": "function", "functions": "function",
                "method":   "method",   "methods":   "method",
                "class":    "class",    "classes":   "class",
            }
            for keyword, kind in sym_map.items():
                if keyword in t:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM symbols WHERE repo_id=? AND kind=?",
                        (repo_id, kind)
                    ).fetchone()[0]
                    lines.append(f"**Total {kind}s: {count}**")
                    rows = conn.execute(
                        "SELECT name, file, line_start FROM symbols "
                        "WHERE repo_id=? AND kind=? ORDER BY file, line_start",
                        (repo_id, kind)
                    ).fetchall()
                    for r in rows[:30]:
                        lines.append(f"  - `{r[0]}` in `{r[1]}` line {r[2]}")
                    matched = True
                    break

        if not matched and "component" in t:
            count = conn.execute(
                "SELECT COUNT(DISTINCT file) FROM symbols "
                "WHERE repo_id=? AND (file LIKE '%.tsx' OR file LIKE '%.jsx')",
                (repo_id,)
            ).fetchone()[0]
            lines.append(f"**React component files: {count}**")
            rows = conn.execute(
                "SELECT DISTINCT file FROM symbols "
                "WHERE repo_id=? AND (file LIKE '%.tsx' OR file LIKE '%.jsx') "
                "ORDER BY file",
                (repo_id,)
            ).fetchall()
            for r in rows:
                lines.append(f"  - `{r[0]}`")
            matched = True

        if not matched:
            # General stats
            stats = get_repo_stats(repo_id)
            lines = [
                f"**Total symbols indexed: {stats['total_symbols']}**",
                f"Files with code: {stats['total_files']}",
                f"Call relationships: {stats['total_calls']}",
                "\nFile type breakdown:",
            ]
            rows = conn.execute("""
                SELECT
                    CASE
                        WHEN file LIKE '%.tsx' THEN 'tsx'
                        WHEN file LIKE '%.ts'  THEN 'ts'
                        WHEN file LIKE '%.jsx' THEN 'jsx'
                        WHEN file LIKE '%.js'  THEN 'js'
                        WHEN file LIKE '%.py'  THEN 'py'
                        ELSE 'other'
                    END as ext,
                    COUNT(DISTINCT file) as cnt
                FROM symbols WHERE repo_id=?
                GROUP BY ext ORDER BY cnt DESC
            """, (repo_id,)).fetchall()
            for r in rows:
                lines.append(f"  .{r[0]}: {r[1]} files")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Context formatter
# ─────────────────────────────────────────────────────────────────────────────

def format_symbol_for_llm(sym: Dict) -> str:
    parts      = []
    kind       = sym.get('kind', 'function').upper()
    name       = sym.get('name', 'unknown')
    file       = sym.get('file', 'unknown')
    line_start = sym.get('line_start', '?')
    line_end   = sym.get('line_end', '?')
    language   = sym.get('language', '')
    class_name = sym.get('class_name', '')
    docstring  = sym.get('docstring', '')
    source     = sym.get('source_code', '')

    loc = f"📍 {kind}: `{name}`"
    if class_name:
        loc += f" (in class `{class_name}`)"
    loc += f"\n   File: `{file}` | Lines: {line_start}–{line_end}"
    parts.append(loc)

    if docstring:
        parts.append(f"   Purpose: {docstring[:200]}")
    if source:
        parts.append(f"   Source:\n```{language}\n{source[:1500]}\n```")

    return "\n".join(parts)


def _make_source(sym: Dict) -> Dict:
    return {
        "file":       sym.get("file", ""),
        "start_line": sym.get("line_start", 0),
        "language":   sym.get("language", ""),
        "score":      sym.get("importance", 0.9),
    }


def _search_symbols(repo_id: str, target: Optional[str],
                     sub_targets: List[str]) -> List[Dict]:
    seen    = set()
    results = []

    def add(new_results):
        for r in new_results:
            key = f"{r['file']}:{r['line_start']}"
            if key not in seen:
                seen.add(key)
                results.append(r)

    if target:
        exact = find_symbol_exact(repo_id, target)
        if exact:
            add(exact)
            return results
        add(find_symbol_fuzzy(repo_id, target))
        for word in target.split():
            if len(word) > 3:
                add(find_symbol_fuzzy(repo_id, word))

    if len(results) < 3:
        for term in sub_targets[:3]:
            if len(term) > 3:
                add(find_symbol_fuzzy(repo_id, term))

    results.sort(key=lambda x: x.get('importance', 0), reverse=True)
    return results[:10]


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def answer_question(repo_id: str, question: str,
                     repo_map: Optional[str] = None) -> Tuple[str, List[Dict]]:
    intent = classify_question(question)
    logger.info(
        f"[{repo_id}] Type={intent.question_type} "
        f"Target={intent.target}"
    )

    context_parts = []
    sources       = []

    if repo_map:
        context_parts.append("## Repository Architecture\n" + repo_map)

    if intent.question_type == "WHERE":
        context_parts.append("## Exact Symbol Location")
        results = _search_symbols(repo_id, intent.target, intent.sub_targets)
        for sym in results[:6]:
            context_parts.append(format_symbol_for_llm(sym))
            sources.append(_make_source(sym))

    elif intent.question_type == "WHAT":
        context_parts.append("## Symbol Definition and Purpose")
        results = _search_symbols(repo_id, intent.target, intent.sub_targets)
        for sym in results[:5]:
            context_parts.append(format_symbol_for_llm(sym))
            sources.append(_make_source(sym))

    elif intent.question_type == "HOW":
        context_parts.append("## Implementation Details")
        results = _search_symbols(repo_id, intent.target, intent.sub_targets)
        for sym in results[:4]:
            context_parts.append(format_symbol_for_llm(sym))
            sources.append(_make_source(sym))
            if sym.get("kind") in ("function", "method"):
                callees = find_callees(repo_id, sym["name"])
                if callees:
                    callee_names = [c["callee_name"] for c in callees[:6]]
                    context_parts.append(
                        f"   ↳ `{sym['name']}` calls: "
                        + ", ".join(f"`{n}`" for n in callee_names)
                    )

    elif intent.question_type == "EXPLAIN":
        context_parts.append("## Core Project Logic")
        top_syms = get_top_symbols(repo_id, limit=15)
        if top_syms:
            context_parts.append("### Most Important Functions and Classes:")
            for sym in top_syms:
                context_parts.append(format_symbol_for_llm(sym))
                sources.append(_make_source(sym))
        summaries = get_file_summaries(repo_id, limit=8)
        if summaries:
            context_parts.append("\n### Key File Summaries:")
            for s in summaries:
                context_parts.append(f"**{s['file']}** — {s['summary']}")
        stats = get_repo_stats(repo_id)
        context_parts.append(
            f"\n### Scale: {stats['total_symbols']} symbols | "
            f"{stats['total_files']} files | "
            f"{stats['total_calls']} call relationships"
        )

    elif intent.question_type == "CALLS":
        context_parts.append(f"## Who Calls `{intent.target}`")
        callers = find_callers(repo_id, intent.target or "")
        if callers:
            for c in callers[:10]:
                context_parts.append(
                    f"📍 `{c['caller_name']}` in `{c['caller_file']}` "
                    f"line {c['caller_line']}"
                )
                if c.get("source_code"):
                    context_parts.append(f"```\n{c['source_code'][:500]}\n```")
                sources.append({
                    "file": c["caller_file"],
                    "start_line": c["caller_line"] or 0,
                    "language": "", "score": 0.9,
                })
        else:
            context_parts.append(
                f"No callers found for `{intent.target}`. "
                "It may be an entry point or called dynamically."
            )

    elif intent.question_type == "CALLED_BY":
        context_parts.append(f"## What `{intent.target}` Calls")
        callees = find_callees(repo_id, intent.target or "")
        if callees:
            for c in callees[:10]:
                line = f"📍 calls `{c['callee_name']}`"
                if c.get("file"):
                    line += f" → `{c['file']}` line {c.get('line_start','?')}"
                context_parts.append(line)
                if c.get("file"):
                    sources.append({
                        "file": c["file"],
                        "start_line": c.get("line_start", 0),
                        "language": "", "score": 0.9,
                    })

    elif intent.question_type == "TRACE":
        target = intent.target or extract_main_term(question) or ""
        context_parts.append(f"## Full Execution Trace for `{target}`")
        start_syms = _search_symbols(repo_id, target, intent.sub_targets)
        if start_syms:
            start = start_syms[0]
            context_parts.append(format_symbol_for_llm(start))
            sources.append(_make_source(start))
            chain = trace_call_chain(repo_id, start["name"], depth=4)
            context_parts.append(format_call_chain(chain, start["name"]))
            for node in chain[:8]:
                if node.get("file") and node.get("file") != start["file"]:
                    sources.append({
                        "file":       node["file"],
                        "start_line": node.get("line_start", 0),
                        "language":   node.get("language", ""),
                        "score":      0.85,
                    })
        else:
            top = get_top_symbols(repo_id, limit=10)
            for sym in top:
                context_parts.append(format_symbol_for_llm(sym))
                sources.append(_make_source(sym))

    elif intent.question_type == "USES":
        target = intent.target or ""
        context_parts.append(f"## Files That Use `{target}`")
        usages = find_usages(repo_id, target)
        if usages:
            for u in usages[:15]:
                context_parts.append(
                    f"📄 `{u['file']}` line {u['line']} — {u['via']}"
                )
                sources.append({
                    "file": u["file"], "start_line": u["line"],
                    "language": "", "score": 0.9,
                })
        else:
            context_parts.append(
                f"No direct imports or calls found for `{target}`. "
                "It may be used dynamically or passed as props."
            )

    elif intent.question_type == "STATS":
        target = intent.target or ""
        context_parts.append(f"## Statistics: {target}")
        context_parts.append(get_stats(repo_id, target))

    elif intent.question_type == "FILE":
        target_file = intent.target or ""
        context_parts.append(f"## Contents of `{target_file}`")
        file_syms = find_in_file(repo_id, target_file)
        if not file_syms:
            bare = target_file.split('/')[-1].split('\\')[-1]
            file_syms = find_in_file(repo_id, bare)
        if not file_syms:
            bare_no_ext = bare.rsplit('.', 1)[0] if '.' in bare else bare
            file_syms = find_in_file(repo_id, bare_no_ext)
        if file_syms:
            for sym in file_syms[:20]:
                context_parts.append(format_symbol_for_llm(sym))
                sources.append(_make_source(sym))
        summaries = get_file_summaries(repo_id)
        for s in summaries:
            if target_file.lower() in s["file"].lower():
                context_parts.insert(1, f"**File Summary:** {s['summary']}")

    elif intent.question_type == "LIST":
        context_parts.append(f"## All `{intent.target}` in Project")
        results = find_symbol_fuzzy(repo_id, intent.target or "")
        for sym in results[:25]:
            line = (
                f"• `{sym['name']}` ({sym['kind']}) in "
                f"`{sym['file']}` line {sym['line_start']}"
            )
            if sym.get("docstring"):
                line += f" — {sym['docstring'][:80]}"
            context_parts.append(line)
            sources.append(_make_source(sym))

    # Fallback
    if len(context_parts) <= 2:
        context_parts.append("## Best Match")
        fallback = _search_symbols(repo_id, question, intent.sub_targets)
        for sym in fallback[:5]:
            context_parts.append(format_symbol_for_llm(sym))
            sources.append(_make_source(sym))

    return "\n\n".join(context_parts), sources