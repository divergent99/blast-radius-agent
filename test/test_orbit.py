import sys, os
sys.path.append("agent")
from dotenv import load_dotenv
load_dotenv()

from orbit_client import OrbitClient, file_path_to_module

client = OrbitClient(os.environ["GITLAB_TOKEN"])

# Get project files first
project_files = {f.path for f in client.get_project_files("gitlab-ai-hackathon/transcend/35648667")}
print("Project files:", project_files)

# Now get blast radius with filtering
result = client.get_blast_radius("src.auth.token", project_files=project_files)
print("Affected files:", result.affected_files)
print("Symbols:", result.imported_symbols)