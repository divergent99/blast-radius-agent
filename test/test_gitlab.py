import sys, os
sys.path.append("agent")
from dotenv import load_dotenv
load_dotenv()

from gitlab_client import GitLabClient

client = GitLabClient(os.environ["GITLAB_TOKEN"])

# Get MR details
mr = client.get_mr("gitlab-ai-hackathon%2Ftranscend%2F35648667", 1)
print("MR title:", mr["title"])
print("Author:", mr["author"]["username"])

# Get changed files
files = client.get_mr_changed_files("gitlab-ai-hackathon%2Ftranscend%2F35648667", 1)
print("Changed files:", files)