import requests

payload = {
    "object_attributes": {
        "iid": 1,
        "title": "Update file token.py",
        "action": "open"
    },
    "project": {
        "id": 83492513,
        "path_with_namespace": "gitlab-ai-hackathon/transcend/35648667"
    },
    "user": {
        "username": "abhineetsharma77"
    }
}

response = requests.post(
    "http://localhost:8000/webhook",
    json=payload,
    headers={
        "X-Gitlab-Event": "Merge Request Hook",
        "X-Gitlab-Token": "blastradius123"
    }
)

print(response.json())