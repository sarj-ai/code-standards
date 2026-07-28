import ast
import tokenize
import sys
import os

def check_file(path):
    issues = []
    try:
        with tokenize.open(path) as f:
            tokens = tokenize.generate_tokens(f.readline)
            for tok in tokens:
                if tok.type == tokenize.COMMENT:
                    raw_comment = tok.string
                    comment = raw_comment.lstrip('#').strip().lower()
                    
                    # 1. Ban ASCII section banners (e.g. ##### STRINGS #####)
                    if set(comment).issubset({'#', '*', '=', '-', '/'}) and len(comment) > 3:
                        issues.append(f"{path}:{tok.start[0]} - ASCII visual banner comment is forbidden: {raw_comment}")
                    
                    # 2. Ban untracked TODO / FIXME markers without issue ticket link or milestone
                    if ('todo' in comment or 'fixme' in comment) and not ('http' in comment or '#' in comment or '(' in comment):
                        issues.append(f"{path}:{tok.start[0]} - Untracked TODO/FIXME without issue ticket or context: {raw_comment}")
                        
                    # 3. Ban translational / code restatement prefixes
                    prefixes = ('increment', 'return', 'function to', 'extract', 'get ', 'set ', 'check for')
                    if any(comment.startswith(p) for p in prefixes):
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
