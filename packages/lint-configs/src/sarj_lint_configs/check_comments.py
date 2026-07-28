import ast
import tokenize
import sys
import os
import re

def check_file(path):
    issues = []
    try:
        with tokenize.open(path) as f:
            tokens = tokenize.generate_tokens(f.readline)
            for tok in tokens:
                if tok.type == tokenize.COMMENT:
                    raw_comment = tok.string
                    comment = raw_comment.lstrip('#').strip().lower()
                    
                    # Skip top-of-file module summary comments (line 1)
                    if tok.start[0] == 1:
                        continue

                    # 1. Ban ASCII section banners (e.g. ##### STRINGS ##### or // ====== TITLE =====)
                    if re.search(r'^[#\*=\-/]{3,}\s*[A-Z0-9_\s]*\s*[#\*=\-/]{3,}$', comment) and len(comment) > 10 and 'test' not in path.lower():
                        issues.append(f"{path}:{tok.start[0]} - ASCII visual banner comment is forbidden in source files: {raw_comment}")
                    
                    # 2. Ban untracked TODO / FIXME markers (strip # noqa directives before checking for issue numbers/links)
                    comment_no_noqa = re.sub(r'#\s*noqa.*$', '', comment)
                    if ('todo' in comment_no_noqa or 'fixme' in comment_no_noqa):
                        has_context = any(k in comment_no_noqa for k in ('http', '#', '(', 'remove when', 'drop', 'python 3.', 'v2', 'v3', 'version', 'ticket', '-'))
                        if not has_context:
                            issues.append(f"{path}:{tok.start[0]} - Untracked TODO/FIXME without issue ticket or context: {raw_comment}")
                        
                    # 3. Ban translational / code restatement comments (only if purely restating in <=3 words with zero rationale or example context)
                    # Exclude docstrings, JSDoc example blocks, and multi-line doc blocks
                    if not raw_comment.startswith(('"""', "'''", '/*', '*')):
                        words = comment.split()
                        # Only flag ultra-short comments (<=3 words) starting with restatement verbs that contain no explanatory context, parenthetical examples, or rationale
                        if len(words) <= 3 and not any(c in comment for c in ('(', ')', ':', 'e.g.', 'i.e.', '=', 'http')) and not any(w in comment for w in ('when', 'because', 'if', 'so that', 'due to', 'for', 'instead of', 'to prevent', 'to avoid', 'only', '@example')):
                            if any(comment.startswith(p) for p in ('increment ', 'return ', 'function to ', 'get ', 'set ')):
                                issues.append(f"{path}:{tok.start[0]} - Useless translational comment restating code: {raw_comment}")
    except Exception:
        pass
    
    try:
        with open(path, 'r') as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                docstring = ast.get_docstring(node)
                if docstring:
                    clean_doc = docstring.strip().lower().rstrip('.')
                    clean_name = node.name.replace('_', ' ').lower()
                    if clean_doc == clean_name or clean_doc == f"get {clean_name}" or clean_doc == f"set {clean_name}":
                        issues.append(f"{path}:{node.lineno} - Trivial docstring duplicates signature: {docstring}")
    except Exception:
        pass
    
    return issues

if __name__ == '__main__':
    for d in sys.argv[1:]:
        for root, dirs, files in os.walk(d):
            for file in files:
                if file.endswith('.py'):
                    res = check_file(os.path.join(root, file))
                    for r in res:
                        print(r)
