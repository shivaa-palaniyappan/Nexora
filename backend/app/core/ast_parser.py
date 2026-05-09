"""
ast_parser.py — FIXED version with improved JS/TS React component detection.
"""

import ast
import re
import logging
from typing import List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FunctionDef:
    name: str
    file: str
    line_start: int
    line_end: int
    parameters: List[str]
    return_type: Optional[str]
    docstring: Optional[str]
    calls: List[str]
    decorators: List[str]
    is_method: bool
    class_name: Optional[str]
    language: str
    source_code: str


@dataclass
class ClassDef:
    name: str
    file: str
    line_start: int
    line_end: int
    methods: List[str]
    parent_classes: List[str]
    docstring: Optional[str]
    language: str


@dataclass
class ImportDef:
    file: str
    line: int
    module: str
    names: List[str]
    alias: Optional[str]


@dataclass
class FileSymbols:
    file: str
    language: str
    functions: List[FunctionDef] = field(default_factory=list)
    classes: List[ClassDef]     = field(default_factory=list)
    imports: List[ImportDef]    = field(default_factory=list)
    parse_error: Optional[str]  = None


# ── Python Parser ────────────────────────────────────────────────────────────

class PythonASTParser:

    def parse(self, content: str, filepath: str) -> FileSymbols:
        symbols = FileSymbols(file=filepath, language="python")
        lines   = content.splitlines()

        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            symbols.parse_error = f"SyntaxError: {e}"
            return symbols

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                line_start = node.lineno
                line_end   = getattr(node, 'end_lineno', line_start + 10)
                source     = "\n".join(lines[line_start-1:line_end])
                params     = [a.arg for a in node.args.args]

                return_type = None
                if node.returns:
                    try: return_type = ast.unparse(node.returns)
                    except: pass

                decorators = []
                for d in node.decorator_list:
                    try: decorators.append(ast.unparse(d))
                    except: pass

                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        try: calls.append(ast.unparse(child.func))
                        except: pass

                is_method = False
                class_name = None
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.ClassDef):
                        if node in ast.walk(parent):
                            is_method  = True
                            class_name = parent.name
                            break

                symbols.functions.append(FunctionDef(
                    name=node.name, file=filepath,
                    line_start=line_start, line_end=line_end,
                    parameters=params, return_type=return_type,
                    docstring=ast.get_docstring(node),
                    calls=calls[:20], decorators=decorators,
                    is_method=is_method, class_name=class_name,
                    language="python", source_code=source[:2000],
                ))

            elif isinstance(node, ast.ClassDef):
                line_start = node.lineno
                line_end   = getattr(node, 'end_lineno', line_start + 5)
                methods    = [n.name for n in ast.walk(node)
                              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                parents = []
                for base in node.bases:
                    try: parents.append(ast.unparse(base))
                    except: pass
                symbols.classes.append(ClassDef(
                    name=node.name, file=filepath,
                    line_start=line_start, line_end=line_end,
                    methods=methods, parent_classes=parents,
                    docstring=ast.get_docstring(node), language="python",
                ))

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    symbols.imports.append(ImportDef(
                        file=filepath, line=node.lineno,
                        module=alias.name, names=[alias.name], alias=alias.asname,
                    ))

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    symbols.imports.append(ImportDef(
                        file=filepath, line=node.lineno,
                        module=node.module,
                        names=[a.name for a in node.names],
                        alias=None,
                    ))

        return symbols


# ── JavaScript / TypeScript Parser (FIXED) ───────────────────────────────────

class JavaScriptParser:

    JS_KEYWORDS = {
        'if', 'for', 'while', 'switch', 'catch', 'function', 'return',
        'typeof', 'instanceof', 'const', 'let', 'var', 'import', 'export',
        'default', 'class', 'new', 'delete', 'throw', 'case', 'else',
        'do', 'in', 'of', 'try', 'async', 'await', 'from', 'as', 'type',
    }

    # Comprehensive patterns covering all React/TS function styles
    FUNC_PATTERNS = [
        # function declaration: function myFunc(
        r'^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(',
        # export default function
        r'^export\s+default\s+(?:async\s+)?function\s+(\w+)',
        # top-level arrow: const myFunc = () =>
        r'^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(\s*\)\s*=>',
        # top-level arrow with params: const myFunc = (a, b) =>
        r'^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>',
        # top-level function expression: const x = function(
        r'^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function[\s(]',
        # typed arrow: const MyComp: React.FC = () =>
        r'^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*:\s*[\w.<>\[\]| &]+\s*=\s*(?:async\s*)?\(',
        # export const: export const MyThing =
        r'^export\s+const\s+(\w+)\s*[=:]',
        # INDENTED arrow inside component: const handleClick = () =>
        r'^\s{2,}const\s+(\w+)\s*=\s*(?:async\s*)?\(\s*\)\s*=>',
        # INDENTED arrow with params: const onDrop = (files) =>
        r'^\s{2,}const\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>',
        # INDENTED useCallback: const onDrop = useCallback((files) =>
        r'^\s{2,}const\s+(\w+)\s*=\s*useCallback\(',
        # INDENTED useMemo / useEffect handlers
        r'^\s{2,}const\s+(\w+)\s*=\s*(?:useMemo|useEffect|useRef|useReducer)\(',
        # class method: myMethod(params) {
        r'^\s{2,}(?:async\s+)?(?:(?:public|private|protected|static|readonly)\s+)*(\w+)\s*\([^)]*\)\s*(?::\s*[\w<>\[\]| &]+)?\s*\{',
        # class arrow method: myMethod = () =>
        r'^\s{2,}(?:readonly\s+)?(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>',
    ]

    CLASS_PATTERN  = r'^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?'
    IMPORT_PATTERN = r'^import\s+(?:type\s+)?(?:\{([^}]+)\}|(\w+)|\*\s+as\s+(\w+))\s+from\s+[\'"]([^\'"]+)[\'"]'

    def parse(self, content: str, filepath: str) -> FileSymbols:
        symbols = FileSymbols(file=filepath, language="javascript")
        lines   = content.splitlines()
        seen    = set()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Skip blank lines and comments
            if not stripped:
                continue
            if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('/*'):
                continue

            # ── Functions ──────────────────────────────────────────
            for pattern in self.FUNC_PATTERNS:
                m = re.match(pattern, line)
                if not m:
                    continue
                func_name = m.group(1)
                if not func_name:
                    continue
                if func_name in self.JS_KEYWORDS:
                    continue
                if len(func_name) < 2:
                    continue

                key = f"{func_name}:{i}"
                if key in seen:
                    break
                seen.add(key)

                end_line = self._find_block_end(lines, i - 1)
                source   = "\n".join(lines[i-1:min(end_line, i + 80)])

                symbols.functions.append(FunctionDef(
                    name=func_name, file=filepath,
                    line_start=i, line_end=end_line,
                    parameters=[], return_type=None, docstring=None,
                    calls=self._extract_calls(source)[:20],
                    decorators=[], is_method=False, class_name=None,
                    language="javascript", source_code=source[:2000],
                ))
                break

            # ── Classes ────────────────────────────────────────────
            m = re.match(self.CLASS_PATTERN, line)
            if m:
                end_line = self._find_block_end(lines, i - 1)
                symbols.classes.append(ClassDef(
                    name=m.group(1), file=filepath,
                    line_start=i, line_end=end_line,
                    methods=[], parent_classes=[m.group(2)] if m.group(2) else [],
                    docstring=None, language="javascript",
                ))

            # ── Imports ────────────────────────────────────────────
            m = re.match(self.IMPORT_PATTERN, line)
            if m:
                named  = m.group(1)
                deflt  = m.group(2)
                star   = m.group(3)
                module = m.group(4)
                names  = []
                if named:
                    names = [n.strip().split(' as ')[0].strip() for n in named.split(',')]
                if deflt:
                    names.append(deflt)
                if star:
                    names.append(f"* as {star}")
                symbols.imports.append(ImportDef(
                    file=filepath, line=i, module=module,
                    names=names, alias=None,
                ))

        return symbols

    def _find_block_end(self, lines: List[str], start: int) -> int:
        depth = 0
        for i in range(start, min(start + 300, len(lines))):
            depth += lines[i].count('{') - lines[i].count('}')
            if depth < 0 or (depth == 0 and i > start):
                return i + 1
        return start + 80

    def _extract_calls(self, source: str) -> List[str]:
        calls = re.findall(r'\b(\w+)\s*\(', source)
        return [c for c in calls if c not in self.JS_KEYWORDS]


# ── Java Parser ──────────────────────────────────────────────────────────────

class JavaParser:

    METHOD_PATTERN = (
        r'(?:public|private|protected|static|final|abstract|synchronized|\s)+'
        r'(?:<[^>]+>\s*)?(\w+)\s+(\w+)\s*\(([^)]*)\)'
    )
    CLASS_PATTERN  = r'(?:public|private|abstract|final|\s)*class\s+(\w+)(?:\s+extends\s+(\w+))?'
    IMPORT_PATTERN = r'^import\s+(static\s+)?([\w.]+(?:\.\*)?)\s*;'

    def parse(self, content: str, filepath: str) -> FileSymbols:
        symbols = FileSymbols(file=filepath, language="java")
        lines   = content.splitlines()

        for i, line in enumerate(lines, 1):
            m = re.search(self.METHOD_PATTERN, line)
            if m and '{' in line:
                method_name = m.group(2)
                if method_name not in ('if', 'for', 'while', 'switch'):
                    source = "\n".join(lines[i-1:min(i+30, len(lines))])
                    symbols.functions.append(FunctionDef(
                        name=method_name, file=filepath,
                        line_start=i, line_end=i+30,
                        parameters=[], return_type=m.group(1).strip(),
                        docstring=None,
                        calls=self._extract_calls(source),
                        decorators=[], is_method=True, class_name=None,
                        language="java", source_code=source[:2000],
                    ))

            m = re.search(self.CLASS_PATTERN, line)
            if m:
                symbols.classes.append(ClassDef(
                    name=m.group(1), file=filepath,
                    line_start=i, line_end=i+100,
                    methods=[], parent_classes=[m.group(2)] if m.group(2) else [],
                    docstring=None, language="java",
                ))

            m = re.match(self.IMPORT_PATTERN, line.strip())
            if m:
                symbols.imports.append(ImportDef(
                    file=filepath, line=i, module=m.group(2),
                    names=[m.group(2).split('.')[-1]], alias=None,
                ))

        return symbols

    def _extract_calls(self, source: str) -> List[str]:
        calls = re.findall(r'(\w+)\s*\(', source)
        return [c for c in calls
                if c not in {'if','for','while','new','return','switch','catch'}][:20]


# ── Generic Parser (Rust, Go, Ruby, etc.) ────────────────────────────────────

class GenericParser:

    FUNC_PATTERNS = [
        r'^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*\(',
        r'^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(',
        r'^def\s+(\w+)\s*\(',
        r'^(?:public|private)?\s*(?:static)?\s*\w+\s+(\w+)\s*\(',
    ]

    def parse(self, content: str, filepath: str) -> FileSymbols:
        ext = filepath.rsplit('.', 1)[-1].lower() if '.' in filepath else ''
        lang_map = {
            'rs':'rust','go':'go','rb':'ruby','php':'php',
            'cs':'csharp','kt':'kotlin','swift':'swift','cpp':'cpp','c':'c',
        }
        language = lang_map.get(ext, ext or 'unknown')
        symbols  = FileSymbols(file=filepath, language=language)
        lines    = content.splitlines()

        for i, line in enumerate(lines, 1):
            for pattern in self.FUNC_PATTERNS:
                m = re.match(pattern, line.strip())
                if m:
                    name = m.group(1)
                    if name and len(name) > 1:
                        source = "\n".join(lines[i-1:min(i+30, len(lines))])
                        symbols.functions.append(FunctionDef(
                            name=name, file=filepath,
                            line_start=i, line_end=i+30,
                            parameters=[], return_type=None, docstring=None,
                            calls=[], decorators=[], is_method=False,
                            class_name=None, language=language,
                            source_code=source[:2000],
                        ))
                    break

        return symbols


# ── Dispatcher ───────────────────────────────────────────────────────────────

_python_parser = PythonASTParser()
_js_parser     = JavaScriptParser()
_java_parser   = JavaParser()
_generic       = GenericParser()

EXTENSION_MAP = {
    'py':'python', 'js':'javascript', 'ts':'javascript',
    'jsx':'javascript', 'tsx':'javascript', 'mjs':'javascript',
    'cjs':'javascript', 'vue':'javascript',
    'java':'java',
    'rs':'generic', 'go':'generic', 'rb':'generic', 'php':'generic',
    'cs':'generic', 'kt':'generic', 'swift':'generic',
    'cpp':'generic', 'c':'generic',
}

PARSER_MAP = {
    'python':     _python_parser,
    'javascript': _js_parser,
    'java':       _java_parser,
    'generic':    _generic,
}


def parse_file(content: str, filepath: str) -> FileSymbols:
    ext    = filepath.rsplit('.', 1)[-1].lower() if '.' in filepath else ''
    lang   = EXTENSION_MAP.get(ext, 'generic')
    parser = PARSER_MAP.get(lang, _generic)

    try:
        return parser.parse(content, filepath)
    except Exception as e:
        logger.warning(f"Parser error for {filepath}: {e}")
        result = FileSymbols(file=filepath, language=ext)
        result.parse_error = str(e)
        return result
