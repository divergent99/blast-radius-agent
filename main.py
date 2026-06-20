from dotenv import load_dotenv
load_dotenv()

import os
import logging
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orbit_client import OrbitClient, file_path_to_module
from gitlab_client import GitLabClient
from synthesizer import Synthesizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Blast Radius Reviewer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GITLAB_TOKEN = os.environ["GITLAB_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

orbit = OrbitClient(GITLAB_TOKEN)
gitlab = GitLabClient(GITLAB_TOKEN)
synth = Synthesizer(ANTHROPIC_API_KEY)


@app.get("/health")
def health():
    return {"status": "ok"}


class AnalyzeRequest(BaseModel):
    project_path: str
    mr_iid: int


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """Dashboard endpoint - returns blast radius data for visualization."""
    try:
        changed_files = gitlab.get_mr_changed_files(req.project_path.replace("/", "%2F"), req.mr_iid)

        if not changed_files:
            return JSONResponse({"changed_files": [], "blast_radius": {}, "imported_symbols": {}})

        project_file_nodes = orbit.get_project_files(req.project_path)
        project_file_paths = {f.path for f in project_file_nodes}

        blast_radius = {}
        imported_symbols = {}

        for file_path in changed_files:
            if not file_path.endswith(".py"):
                continue
            module_path = file_path_to_module(file_path)
            result = orbit.get_blast_radius(module_path, project_files=project_file_paths)
            affected = list({f for f in result.affected_files if f != file_path})
            blast_radius[file_path] = affected
            imported_symbols[file_path] = [
                s for s in result.imported_symbols if s["in_file"] in affected
            ]

        return JSONResponse({
            "changed_files": changed_files,
            "blast_radius": blast_radius,
            "imported_symbols": imported_symbols,
        })

    except Exception as e:
        logger.error(f"Error in /analyze: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/graph")
async def graph(req: AnalyzeRequest):
    """Returns full project dependency graph for visualization."""
    try:
        project_file_nodes = orbit.get_project_files(req.project_path)
        project_file_paths = {f.path for f in project_file_nodes}
        files = [{"id": f.id, "path": f.path, "name": f.name, "language": f.language}
                 for f in project_file_nodes]
        edges = []
        for f in project_file_nodes:
            if f.language != "python":
                continue
            module_path = file_path_to_module(f.path)
            result = orbit.get_blast_radius(module_path, project_files=project_file_paths)
            for affected in result.affected_files:
                if affected != f.path:
                    edges.append({
                        "source": f.path,
                        "target": affected,
                        "symbols": [s["symbol"] for s in result.imported_symbols if s["in_file"] == affected]
                    })
        return JSONResponse({"files": files, "edges": edges})
    except Exception as e:
        logger.error(f"Error in /graph: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class DescribeRequest(BaseModel):
    file_path: str


@app.post("/describe")
async def describe_file(req: DescribeRequest):
    """Generate a one-line description of a file using Claude."""
    try:
        message = synth.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=60,
            messages=[{
                "role": "user",
                "content": f"In one short sentence (max 12 words), describe what this file likely does based on its path: {req.file_path}"
            }]
        )
        return JSONResponse({"description": message.content[0].text.strip()})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ChatRequest(BaseModel):
    message: str
    graph_context: dict


@app.post("/chat")
async def chat(req: ChatRequest):
    """Answer questions about the codebase using graph context."""
    try:
        files = req.graph_context.get("files", [])
        edges = req.graph_context.get("edges", [])
        files_summary = "\n".join([f"- {f['path']}" for f in files])
        edges_summary = "\n".join([f"- {e['source']} → {e['target']} (imports: {', '.join(e['symbols'])})" for e in edges])

        message = synth.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": f"""You are a code assistant with access to a project's dependency graph from GitLab Orbit.

Files in project:
{files_summary}

Import relationships:
{edges_summary}

Answer this question concisely based on the graph structure above:
{req.message}"""
            }]
        )
        return JSONResponse({"answer": message.content[0].text.strip()})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    if WEBHOOK_SECRET:
        token = request.headers.get("X-Gitlab-Token", "")
        if token != WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook token")

    payload = await request.json()
    event = request.headers.get("X-Gitlab-Event", "")

    if event != "Merge Request Hook":
        return JSONResponse({"status": "ignored", "reason": "not an MR event"})

    action = payload.get("object_attributes", {}).get("action", "")
    if action not in ("open", "reopen", "update"):
        return JSONResponse({"status": "ignored", "reason": f"action '{action}' not handled"})

    mr_iid = payload["object_attributes"]["iid"]
    project_id = payload["project"]["id"]
    project_path = payload["project"]["path_with_namespace"]

    logger.info(f"Processing MR !{mr_iid} in {project_path}")

    background_tasks.add_task(
        analyze_and_comment,
        project_id=project_id,
        project_path=project_path,
        mr_iid=mr_iid,
        mr_title=payload["object_attributes"]["title"],
        mr_author=payload["user"]["username"],
    )

    return JSONResponse({"status": "accepted", "mr": mr_iid})


async def analyze_and_comment(
    project_id: int,
    project_path: str,
    mr_iid: int,
    mr_title: str,
    mr_author: str,
):
    try:
        # 1. Get changed files from MR via GitLab REST API
        changed_files = gitlab.get_mr_changed_files(project_id, mr_iid)
        logger.info(f"Changed files: {changed_files}")

        if not changed_files:
            logger.info("No changed files found, skipping")
            return

        # 2. Get all files in this project for noise filtering
        project_file_nodes = orbit.get_project_files(project_path)
        project_file_paths = {f.path for f in project_file_nodes}
        logger.info(f"Project has {len(project_file_paths)} indexed files")

        # 3. For each changed Python file, get blast radius
        blast_radius = {}
        imported_symbols = {}

        for file_path in changed_files:
            if not file_path.endswith(".py"):
                continue

            module_path = file_path_to_module(file_path)
            result = orbit.get_blast_radius(module_path, project_files=project_file_paths)

            # Exclude the changed file itself
            affected = list({f for f in result.affected_files if f != file_path})
            blast_radius[file_path] = affected
            imported_symbols[file_path] = [
                s for s in result.imported_symbols if s["in_file"] in affected
            ]

        # 4. Get historical reviewers
        try:
            reviewers = orbit.get_historical_reviewers(project_path)
        except Exception as e:
            logger.warning(f"Could not fetch reviewers: {e}")
            reviewers = []

        # 5. Generate comment with Claude
        comment = synth.generate_blast_radius_comment(
            mr_title=mr_title,
            mr_author=mr_author,
            changed_files=changed_files,
            blast_radius=blast_radius,
            imported_symbols=imported_symbols,
            suggested_reviewers=reviewers,
        )

        # 6. Post to MR
        full_comment = (
            "## 💥 Blast Radius Analysis\n\n"
            "*Powered by [Blast Radius Reviewer](https://gitlab.com/gitlab-ai-hackathon/transcend/35648667) "
            "using GitLab Orbit*\n\n"
            f"{comment}"
        )
        gitlab.post_mr_comment(project_id, mr_iid, full_comment)
        logger.info(f"Posted blast radius comment on MR !{mr_iid}")

    except Exception as e:
        logger.error(f"Error analyzing MR !{mr_iid}: {e}", exc_info=True)