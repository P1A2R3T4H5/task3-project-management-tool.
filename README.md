# Task 3 — TaskFlow Project Management Tool

## Included
- Register/login/logout with hashed passwords
- Create project boards and add registered users as members
- Create and assign tasks, set status, priority and due date
- Task comments and discussion
- In-app notifications and Socket.IO real-time events
- SQLite database automatically created

## Run on Windows / VS Code
1. Extract the ZIP and open this folder in VS Code.
2. In the terminal, run:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
   ```
   Or double-click `run_windows.bat`.
3. Open http://127.0.0.1:5000

## Demo
Register account A, create a project, register account B in another browser/incognito window, then invite B by their registered email. Create tasks, assign members, add comments and update status.

This is a college-project starter. Before public deployment, change SECRET_KEY, add CSRF protection, rate limiting and production server configuration.
