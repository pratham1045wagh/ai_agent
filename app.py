import re
import os
import ast
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import StrOutputParser

# --- 1. Initialization and Setup ---
load_dotenv()
app = Flask(__name__, template_folder='templates')
CORS(app) # Enable Cross-Origin Resource Sharing

# --- 2. LangChain and AI Model Setup ---
# Initialize the Gemini model, ensuring the API key is loaded from the environment
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.environ.get("GOOGLE_API_KEY"),
    temperature=0.1 # Lower temperature for more predictable code comments
)

# --- Helper functions to analyze code ---
def guess_language(code_snippet):
    """A simplified heuristic to guess the programming language of a code snippet."""
    if re.search(r'\b(def|class)\b', code_snippet): return "python"
    if re.search(r'\b(public|static|class|void|main)\b', code_snippet): return "java"
    if re.search(r'#include|<iostream>', code_snippet): return "cpp"
    if re.search(r'\b(function|const|let|var|import)\b', code_snippet): return "javascript"
    return "plaintext"

def extract_functions_regex(code_snippet, language):
    """Extracts function names from a code snippet using regular expressions."""
    functions = set()
    keywords_to_exclude = {'for', 'if', 'while', 'switch', 'catch', 'do', 'class', 'new'}

    # Use different regex patterns for different languages
    if language in ["javascript", "java", "cpp", "c#"]:
        regex = r'(?:public\s+|private\s+|protected\s+|static\s+)\w+\s+(&?\w+)\s\([^)]\)\s\{'
        matches = re.findall(regex, code_snippet)
        if matches:
            functions.update(matches)
    elif language == "python":
        regex = r"def\s+(\w+)\s*\([^)]*\):"
        matches = re.findall(regex, code_snippet)
        if matches:
            functions.update(matches)
    
    # A common case for main functions
    if re.search(r'\s+main\s*\(', code_snippet):
        functions.add('main')

    return sorted(list(functions - keywords_to_exclude))

# --- 3. Flask Routes (The "Brain" of the Web App) ---

# This is the main homepage route. It just shows the HTML page.
@app.route("/")
def index():
    return render_template("index.html")

# This route is called by the JavaScript to detect functions in the code
@app.route('/functions', methods=['POST'])
def get_functions_from_code():
    data = request.get_json()
    code_snippet = data.get('code_snippet', '')
    
    language = guess_language(code_snippet)
    functions = extract_functions_regex(code_snippet, language)

    # Always provide an "All Code" option
    functions.insert(0, "All Code")
    return jsonify({"functions": functions, "language": language})

# This is the main route for generating comments
@app.route('/comment', methods=['POST'])
def comment_code():
    data = request.get_json()
    code_snippet = data.get('code_snippet')
    function_name = data.get('function_name')
    
    if not code_snippet:
        return jsonify({"error": "Missing code snippet"}), 400

    language = guess_language(code_snippet)
    
    try:
        # Determine if we are commenting the whole file or a specific function
        target_text = f"the entire code snippet"
        if function_name and function_name != "All Code":
            target_text = f"only the function named '{function_name}' within the snippet"

        # --- Prompt Engineering ---
        prompt_template = f"""
        You are an expert programmer and an AI code commenting agent. Your ONLY task is to return a single Markdown code block with the provided code, including clean, extremely brief, and precise comments.

        *Instructions:*
        1.  *Target:* You must add comments for {target_text}.
        2.  *Add Comments:* Add comments directly into the code. The comments should explain the "why" or complex parts of the code, not just the "what".
        3.  *Preserve Code:* Do not change, alter, or reformat the original code in any way. Only add comments.
        4.  *Output:* Return ONLY the final, commented code block. Do not include any extra explanations, markdown formatting (` ``` `), or introductory text.

        *Code Snippet to Comment:*
        {code_snippet}
        """
        
        prompt = ChatPromptTemplate.from_template(template=prompt_template)
        # Create the processing chain
        chain = prompt | llm | StrOutputParser()

        # Invoke the AI to get the commented code
        commented_code = chain.invoke({})
        
        return jsonify({
            "commented_code": commented_code.strip(),
            "language": language
        })
    except Exception as e:
        print(f"Error during code commenting: {e}")
        return jsonify({"error": str(e)}), 500

# --- 4. Run the Application ---
if __name__ == '__main__':
    # Starts the local development server
    app.run(debug=True)