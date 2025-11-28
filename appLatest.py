from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_mysqldb import MySQL
import bcrypt
import json
import re # Import regular expressions library for parsing
import google.generativeai as genai
import os
import time # Import the time module for handling delays

app = Flask(__name__)
# IMPORTANT: Use a long, random, and secret key in a real application
app.secret_key = 'your_very_long_and_random_secret_key' 

# --- Configure Gemini API ---
genai.configure(api_key="AIzaSyDhHyiURBNplE76A9K6oO3k-Wh1eAbwyGA") 
model = genai.GenerativeModel('gemini-2.5-pro')

# Configure MySQL
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'Pokemonbw@2015'
app.config['MYSQL_DB'] = 'SmartLearnAI_New'
# Use DictCursor to get results as dictionaries, which is easier to work with
app.config['MYSQL_CURSORCLASS'] = 'DictCursor' 

mysql = MySQL(app)

# ----------------- HELPER FUNCTION: PARSE LLM RESPONSE (IMPROVED V4) -----------------
def parse_gemini_response_to_json(text_response):
    """
    Parses the structured text response from the LLM into a JSON-serializable dictionary.
    This version is highly robust to handle complex markdown and formatting variations.
    """
    print("--- Raw Gemini Response Received ---")
    print(text_response)
    print("------------------------------------")
    
    try:
        # Extract the main title, ignoring markdown asterisks
        title_match = re.search(r'\*\*Title:\*\*\s*(.*?)\n', text_response)
        title = title_match.group(1).strip() if title_match else "Untitled Curriculum"

        parsed_data = {"Title": title}
        
        # Split the entire response into the 3 main paths
        # This pattern looks for "### **1. Short Duration Path...**" and uses it as a delimiter
        paths = re.split(r'### \*\*\d+\.\s*(.*?)\*\*', text_response)
        
        # The first element is intro text, the rest are pairs of (path_name, path_content)
        path_contents = zip(paths[1::2], paths[2::2])

        for path_header, path_content in path_contents:
            # Clean up the path name to get "Short Duration Path", etc.
            path_name = path_header.split('(')[0].strip()
            parsed_data[path_name] = []

            # Split the current path's content by phases
            phases = re.split(r'\*\*(Phase \d+:.*?)\*\*', path_content)
            phase_contents = zip(phases[1::2], phases[2::2])

            for phase_title, phase_content_block in phase_contents:
                phase_obj = {
                    "Phase": phase_title.strip(),
                    "Steps": []
                }

                # Split the phase content into individual step blocks. A step starts with "* **Step..."
                step_blocks = re.split(r'\n\s*(?=\*\s*\*\*Step)', phase_content_block)

                for i, block in enumerate(step_blocks, 1):
                    if not block.strip() or not block.startswith('*'):
                        continue
                    
                    # Use re.search for each field to handle variations in formatting
                    step_title_match = re.search(r'\*\*Step \d+:\s*(.*?)\*\*', block)
                    # This regex is key: it finds the markdown link and captures ONLY the URL inside the parentheses
                    course_link_match = re.search(r'\[.*?\]\(([^)]+)\)', block)
                    duration_match = re.search(r'\*\*Duration:\*\*\s*(.*?)\n', block)
                    description_match = re.search(r'\*\*Description:\*\*\s*(.*)', block, re.DOTALL)

                    if all([step_title_match, course_link_match, duration_match, description_match]):
                        # Clean up the description to remove any trailing free alternative text
                        description_text = description_match.group(1).split('* **Free Alternative:**')[0].strip()

                        step_obj = {
                            # Store just the title of the step, without the "Step X:" prefix
                            "Step": step_title_match.group(1).strip(),
                            "Course Link": course_link_match.group(1).strip(),
                            "Duration": duration_match.group(1).strip(),
                            "Description": description_text
                        }
                        phase_obj["Steps"].append(step_obj)
                
                if phase_obj["Steps"]:
                    parsed_data[path_name].append(phase_obj)

        return parsed_data

    except Exception as e:
        print(f"FATAL ERROR while parsing LLM response: {e}")
        # Return a fallback structure
        return {"Title": "Error: Could Not Parse Curriculum", "Short Duration path": [], "Moderate Duration path": [], "Long Duration path": []}


# --------------------- ROUTES ---------------------

@app.route('/')
def home():
    return render_template('LandingPageUltimate.html')

@app.route('/login')
def login_page():
    message = session.pop('message', None)
    return render_template('LoginPage.html', message=message)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/signup')
def signup_page():
    return render_template('SignUpPage.html')

@app.route('/dashboard')
def dashboard_page():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    user_id = session['user_id']
    username = session.get('username', 'User')
    message = session.pop('message', None)
    prefilled_prompt = session.pop('landing_prompt', None)
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, goal_prompt, curriculum_response FROM goals WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    past_goals = cur.fetchall()
    cur.close()

    for goal in past_goals:
        if goal['curriculum_response']:
            try:
                response_data = json.loads(goal['curriculum_response'])
                # The response is stored as JSON, so we can directly access keys
                goal['title'] = response_data.get('Title', 'Untitled Curriculum')
            except (json.JSONDecodeError, TypeError): # Handles if it's not a dict
                goal['title'] = 'View Curriculum'
        else:
            goal['title'] = 'Processing...'

    return render_template('DashBoard.html', 
                           message=message, 
                           username=username, 
                           prefilled_prompt=prefilled_prompt,
                           past_goals=past_goals)

@app.route('/curriculum/<int:goal_id>')
def curriculum_page(goal_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT curriculum_response FROM goals WHERE id = %s AND user_id = %s", (goal_id, session['user_id']))
    goal = cur.fetchone()
    cur.close()

    if not goal or not goal['curriculum_response']:
        return "Curriculum not found or is still being generated.", 404

    # The response from the DB is a JSON string. We must parse it into a Python dict.    
    try:
        curriculum_data = json.loads(goal['curriculum_response'])
    except (json.JSONDecodeError, TypeError):
        # Handle cases where the data is malformed or not a string
        curriculum_data = {"Title": "Error: Could not load curriculum data."}
    
    return render_template('CurriculumPage.html', curriculum_data=curriculum_data)

@app.route('/handle_landing_prompt', methods=['POST'])
def handle_landing_prompt():
    prompt = request.form.get('prompt')
    if prompt:
        session['landing_prompt'] = prompt
    session['message'] = 'Please log-in first'
    return redirect(url_for('login_page'))

# ----------------- API: Email Check -----------------

@app.route('/check_email', methods=['POST'])
def check_email():
    email = request.json['email']
    cur = mysql.connection.cursor()
    cur.execute("SELECT email FROM users WHERE email = %s", (email,))
    user = cur.fetchone()
    cur.close()
    return jsonify({'exists': bool(user)})

# ----------------- API: Sign-Up -----------------

@app.route('/signup_user', methods=['POST'])
def signup_user():
    email = request.form['email']
    password = request.form['password']

    cur = mysql.connection.cursor()
    cur.execute("SELECT email FROM users WHERE email = %s", (email,))
    user = cur.fetchone()

    if user:
        return render_template('LoginPage.html', message='Email already exists. Please log in.')

    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    cur.execute("INSERT INTO users (email, password) VALUES (%s, %s)", (email, hashed_password))
    mysql.connection.commit()
    cur.close()

    return render_template('LoginPage.html', message='User registered successfully. Please log in.')

# ----------------- API: Login -----------------

@app.route('/login_user', methods=['POST'])
def login_user():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Request must be JSON'}), 400

        email = data.get('email')
        password = data.get('password')

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()

        if not user:
            return jsonify({'success': False, 'message': 'No account found. Please sign up.'})

        # Use the column name 'password' thanks to DictCursor
        hashed_pw = user['password'].encode('utf-8')
        if bcrypt.checkpw(password.encode('utf-8'), hashed_pw):
            # Store essential user info in the session
            session['user_id'] = user['id']
            session['username'] = email.split('@')[0].capitalize()
            session['message'] = 'Login successful!'
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Incorrect Password.'})

    except Exception as e:
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

# ----------------- API: Save Goal and Generate Curriculum -----------------
@app.route('/api/save_and_generate', methods=['POST'])
def save_and_generate():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'User not logged in'}), 401

    try:
        data = request.get_json()
        user_id = session['user_id']
        
        main_prompt = data['mainPrompt']
        responses = data['questionnaireResponses']
        final_llm_prompt = data['finalPromptForLLM']

        # --- 1. Save initial data to get a goal_id ---
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO goals (user_id, goal_prompt) VALUES (%s, %s)", (user_id, main_prompt))
        goal_id = cur.lastrowid
        
        # (Save profile, details, domains, subdomains as before)
        cur.execute("SELECT id FROM user_profiles WHERE user_id = %s", (user_id,))
        profile = cur.fetchone()
        if profile:
            cur.execute("UPDATE user_profiles SET user_type = %s, education_level = %s WHERE user_id = %s", (responses['general'], responses['level'], user_id))
        else:
            cur.execute("INSERT INTO user_profiles (user_id, user_type, education_level) VALUES (%s, %s, %s)", (user_id, responses['general'], responses['level']))
        duration = ", ".join(responses['duration'])
        cur.execute("INSERT INTO goal_details (goal_id, preferred_duration, reason) VALUES (%s, %s, %s)", (goal_id, duration, responses['reason']))
        for domain in responses['domain']:
            cur.execute("INSERT INTO goal_domains (goal_id, domain_name) VALUES (%s, %s)", (goal_id, domain))
            if domain in responses['subdomains'] and responses['subdomains'][domain]:
                for subdomain in responses['subdomains'][domain]:
                    cur.execute("INSERT INTO goal_subdomains (goal_id, domain_name, subdomain_name) VALUES (%s, %s, %s)", (goal_id, domain, subdomain))
        
        mysql.connection.commit() # Commit initial data

        # --- 2. Call Gemini API ---
        response = model.generate_content(final_llm_prompt)
        raw_response_text = response.text
        
        # --- 3. Parse the response and save the structured JSON to DB ---
        parsed_curriculum = parse_gemini_response_to_json(raw_response_text)
        
        # NOTE: The column type in MySQL should be JSON for this to work best
        cur.execute("UPDATE goals SET curriculum_response = %s WHERE id = %s", (json.dumps(parsed_curriculum), goal_id))
        mysql.connection.commit()
        cur.close()
        
        # --- 4. Return the URL for redirection ---
        return jsonify({'success': True, 'redirect_url': url_for('curriculum_page', goal_id=goal_id)})

    except Exception as e:
        print(f"Error in save_and_generate: {str(e)}")
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(debug=True)
