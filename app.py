import re
import os
import ast
from flask import Flask, request, jsonify
from flask_cors import CORS
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import StrOutputParser

app = Flask(__name__)
CORS(app)

# The hardcoded API key and the os.environ assignment are removed.
# The application now relies on the API key being set in the environment before it starts.

# --- Helper to guess language (simplified heuristic) ---
def guess_language(code_snippet):
    if re.search(r'^\s*(def|class)\s+', code_snippet, re.MULTILINE):
        return 'python'
    if re.search(r'^\s*public\s+(class|static\s+void\s+main)', code_snippet, re.MULTILINE):
        return 'java'
    if re.search(r'^\s*(#include|int\s+main)', code_snippet, re.MULTILINE) or re.search(r'^\s*using\s+namespace', code_snippet, re.MULTILINE):
        return 'c++'
    if re.search(r'^\s*(function|const\s+\w+\s*=\s*\(|import|export)', code_snippet, re.MULTILINE):
        return 'javascript'
    return 'plaintext'

# --- Helper to extract function names and code blocks ---
def extract_functions(code_snippet, language):
    functions = set()
    keywords_to_exclude = {'for', 'if', 'while', 'switch', 'catch', 'do', 'class', 'new'}

    if language == 'python':
        try:
            tree = ast.parse(code_snippet)
            functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        except SyntaxError:
            regex_def = r'^\s*def\s+(\w+)\s*\(.*?\):'
            matches = re.findall(regex_def, code_snippet, re.MULTILINE)
            functions = set(matches)
        except Exception:
            functions = set()
    else:
        regex = r'(?:(?:(?:public|private|protected)\s+)?(?:static\s+)?(?:final\s+)?(?:void|[a-zA-Z_][a-zA-Z0-9_]*)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*\{)|(?:(?:[a-zA-Z_][a-zA-Z0-9_]*::)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*(?:const|noexcept)?\s*\{)|(?:function\s+([a-zA-Z0-9_]+)\s*\(.*?\))|(?:(?:const|let|var)\s+([a-zA-Z0-9_]+)\s*=\s*(?:function)?\s*\(.*?\))|(?:def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(.*?\)\s*:)|(?:([a-zA-Z0-9_]+)\s*\([^)]*\)\s*\{)'
        matches = re.findall(regex, code_snippet, re.MULTILINE)
        for match in matches:
            for group in match:
                if group:
                    functions.add(group)

    if re.search(r'\s+main\s*\(', code_snippet):
        functions.add('main')

    return sorted(list(functions - keywords_to_exclude))

# --- New endpoint to get function names from code ---
@app.route('/functions', methods=['POST'])
def get_functions_from_code():
    data = request.get_json()
    code_snippet = data.get('code_snippet', '')
    
    language = guess_language(code_snippet)
    functions = extract_functions(code_snippet, language)

    functions.insert(0, "All Code")
    return jsonify({"functions": functions, "language": language})

# --- Main endpoint to get comments for a specific function ---
@app.route('/comment', methods=['POST'])
def comment_code():
    data = request.get_json()
    code_snippet = data.get('code_snippet')
    function_name = data.get('function_name')
    
    if not code_snippet:
        return jsonify({"error": "Missing code snippet"}), 400

    language = guess_language(code_snippet)
    
    try:
        system_prompt = (
            f"You are a world-class code commenting agent. Your ONLY task is to return a single Markdown code block with the provided code, including clean, extremely brief, and precise comments. The comments should be single-line notes that explain a specific line or block of code. Do not provide any form of summary, brief explanation, parameter lists, or return value descriptions. Do not add any text outside of the Markdown code block. You MUST preserve the original code's structure and spacing, including all line breaks and indentation. You MUST preserve the original namespace usage (e.g., if 'using namespace std;' is present, do not add 'std::' prefixes; if it is not present, add them). Do not modify the original code's structure or syntax; only add comments."
        )

        if function_name and function_name != "All Code":
            instruction = (
                f"Comment the following code, but only for the function named \"{function_name}\". Preserve the original structure and all other code lines, but do not comment them. Do not provide any form of summary, brief explanation, or text outside of the commented code block.\n```\n{code_snippet}\n```"
            )
        else:
            instruction = (
                f"Comment the entire code below, preserving all original line breaks and spacing. Do not omit any part of the original code, including preprocessor directives and syntax. Provide a single, complete, commented code block and nothing else.\n```\n{code_snippet}\n```"
            )

        # Updated line to get the API key from the environment variable
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=os.environ.get("GOOGLE_API_KEY"), temperature=0.1) 
        response = llm.invoke(system_prompt + "\n\n" + instruction)
        llm_text = response.content.strip()

        code_block_regex = re.compile(r'```(?:[a-zA-Z]+)?\n([\s\S]*?)```')
        match = code_block_regex.search(llm_text)
        
        if not match:
            return jsonify({"error": "Failed to extract a commented code block from the response."}), 500

        commented_code = match.group(1) # Keep the original indentation from the LLM
        
        return jsonify({
            "commented_code": commented_code,
            "language": language
        })
    except Exception as e:
        print(f"Error during code commenting: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)