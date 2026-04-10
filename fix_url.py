import subprocess
# Use Vertex AI endpoint instead - no rate limits on GCP
old = '"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"'
new = '"https://us-central1-aiplatform.googleapis.com/v1/projects/study-buddy-bro-guide/locations/us-central1/publishers/google/models/gemini-2.0-flash:generateContent"'
for f in ['tools.py', 'agent.py']:
    with open(f, 'r') as file:
        content = file.read()
    content = content.replace(old.strip('"'), new.strip('"'))
    with open(f, 'w') as file:
        file.write(content)
    print(f"Updated {f}")
