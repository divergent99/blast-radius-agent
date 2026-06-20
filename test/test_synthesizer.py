import sys, os
sys.path.append("agent")
from dotenv import load_dotenv
load_dotenv()

from synthesizer import Synthesizer

s = Synthesizer(os.environ["ANTHROPIC_API_KEY"])

comment = s.generate_blast_radius_comment(
    mr_title="Update file token.py",
    mr_author="abhineetsharma77",
    changed_files=["src/auth/token.py"],
    blast_radius={"src/auth/token.py": ["src/auth/validator.py"]},
    imported_symbols={"src/auth/token.py": [{"symbol": "TokenService", "in_file": "src/auth/validator.py"}]},
    suggested_reviewers=[],
)

print(comment)