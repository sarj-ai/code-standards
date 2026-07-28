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
                    comment = tok.string.lstrip('#').strip().lower()
                    if comment.startswith('increment') or comment.startswith('return') or comment.startswith('function to') or 'TODO' in tok.string:
                        issues.append(f"{path}:{tok.start[0]} - Useless or redundant comment: {tok.string}")
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
                    if docstring.strip().lower() == node.name.replace('_', ' ').lower():
                        issues.append(f"{path}:{node.lineno} - Trivial docstring duplicates name: {docstring}")
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
