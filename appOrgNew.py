from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_mysqldb import MySQL
import bcrypt
import json
import re # Import regular expressions library for parsing

app = Flask(__name__)
app.secret_key = 'your_very_long_and_random_secret_key' 

# --- Configure Gemini API (placeholder) ---
import google.generativeai as genai
genai.configure(api_key="AIzaSyDhHyiURBNplE76A9K6oO3k-Wh1eAbwyGA")
model = genai.GenerativeModel('gemini-2.5-pro')

# Configure MySQL
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'Pokemonbw@2015'
app.config['MYSQL_DB'] = 'SmartLearnAI_New'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor' 

mysql = MySQL(app)

# ----------------- HELPER FUNCTION: PARSE LLM RESPONSE -----------------
def parse_gemini_response_to_json(text_response):
    """
    Parses the structured text response from the LLM into a JSON-serializable dictionary.
    """
    try:
        # Extract the main title
        title_match = re.search(r'Title: "?(.*?)"?\n', text_response)
        title = title_match.group(1).strip() if title_match else "Untitled Curriculum"

        parsed_data = {"Title": title}
        
        # Define the paths to look for
        paths = ["Short Duration path", "Moderate Duration path", "Long Duration path"]

        for path_name in paths:
            # Find the block of text for each path
            path_regex = re.compile(rf'{re.escape(path_name)}(.*?)(?=\n(?:Short|Moderate|Long) Duration path|$)', re.DOTALL)
            path_match = path_regex.search(text_response)
            if not path_match:
                continue

            path_content = path_match.group(1)
            parsed_data[path_name] = []

            # Find all phases within the path
            phase_regex = re.compile(r'Phase (\d+): (.*?)\n', re.DOTALL)
            phase_matches = phase_regex.finditer(path_content)
            
            phases = list(phase_matches)
            for i, current_phase_match in enumerate(phases):
                phase_number = current_phase_match.group(1)
                phase_title = current_phase_match.group(2).strip()
                
                phase_obj = {
                    "Phase": f"Phase {phase_number}: {phase_title}",
                    "Steps": []
                }

                # Determine the content block for the current phase
                start_index = current_phase_match.end()
                end_index = phases[i+1].start() if i + 1 < len(phases) else len(path_content)
                phase_content_block = path_content[start_index:end_index]

                # Find all steps within the phase block
                step_regex = re.compile(r'Step (\d+): (.*?)\n\s*Course: (.*?)\n\s*Duration: (.*?)\n\s*Description: (.*?)(?=\n\s*Step|\Z)', re.DOTALL)
                step_matches = step_regex.finditer(phase_content_block)

                for step_match in step_matches:
                    step_obj = {
                        "Step": f"Step {step_match.group(1)}: {step_match.group(2).strip()}",
                        "Course Link": step_match.group(3).strip(),
                        "Duration": step_match.group(4).strip(),
                        "Description": step_match.group(5).strip()
                    }
                    phase_obj["Steps"].append(step_obj)
                
                if phase_obj["Steps"]:
                    parsed_data[path_name].append(phase_obj)

        return parsed_data

    except Exception as e:
        print(f"Error parsing LLM response: {e}")
        # Return a fallback structure
        return {"Title": "Error Parsing Curriculum", "Short Duration path": [], "Moderate Duration path": [], "Long Duration path": []}


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
                # The response is stored as JSON, so we can directly access keys
                goal['title'] = goal['curriculum_response'].get('Title', 'Untitled Curriculum')
            except (AttributeError, TypeError): # Handles if it's not a dict
                goal['title'] = 'View Curriculum'
        else:
            goal['title'] = 'Processing...'

    return render_template('DashBoard.html', message=message, username=username, prefilled_prompt=prefilled_prompt, past_goals=past_goals)

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
    
    # The response is already a JSON object from the DB
    curriculum_data = goal['curriculum_response']
    
    return render_template('CurriculumPage.html', curriculum_data=curriculum_data)

# ---Handle Landing Page Prompt ---

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

# ----------------- API: Save Goal and Details -----------------

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

        # --- 2. Call Gemini API (Simulated) ---
        response = model.generate_content(final_llm_prompt)
        raw_response_text = response.text
        
        """ mock_response_text = ""Title: Data Analyst Career Path
Short Duration path
Phase 1: Foundations (Weeks 1-4)
Step 1: Core Concepts (Weeks 1-2)
    Course: [Google Data Analytics Professional Certificate](https://www.coursera.org/professional-certificates/google-data-analytics)
    Duration: 2 Weeks
    Description: Learn the absolute basics of data analysis, spreadsheets, and SQL.
Step 2: SQL Deep Dive (Weeks 3-4)
    Course: [The Complete SQL Bootcamp](https://www.udemy.com/course/the-complete-sql-bootcamp/)
    Duration: 2 Weeks
    Description: Master PostgreSQL and handle complex queries required for data analysis.
Moderate Duration path
Phase 1: Core Skills (Weeks 1-8)
Step 1: Data Analytics Foundations (Weeks 1-4)
    Course: [Google Data Analytics Professional Certificate](https://www.coursera.org/professional-certificates/google-data-analytics)
    Duration: 4 Weeks
    Description: A comprehensive introduction to the entire data analysis ecosystem.
Step 2: Python for Everybody (Weeks 5-8)
    Course: [Python for Everybody Specialization](https://www.coursera.org/specializations/python-for-everybody)
    Duration: 4 Weeks
    Description: Learn the fundamentals of Python programming, a key skill for data analysts.
Long Duration path
Phase 1: Foundational Mastery (Weeks 1-12)
Step 1: Complete Data Science Bootcamp (Weeks 1-8)
    Course: [The Data Science Course 2024: Complete Data Science Bootcamp](https://www.udemy.com/course/the-data-science-course-complete-data-science-bootcamp/)
    Duration: 8 Weeks
    Description: An extensive course covering everything from stats and math to Python and Tableau.
Step 2: Advanced SQL and Database Management (Weeks 9-12)
    Course: [NPTEL - Database Management System](https://onlinecourses.nptel.ac.in/noc24_cs30/preview)
    Duration: 4 Weeks
    Description: University-level course on database design, normalization, and advanced querying.

        raw_response_text = mock_response_text """

        # --- 3. Parse the response and save the structured JSON to DB ---
        parsed_curriculum = parse_gemini_response_to_json(raw_response_text)
        
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
