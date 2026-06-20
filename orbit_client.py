import requests
from dataclasses import dataclass


ORBIT_API = "https://gitlab.com/api/v4/orbit/query"


@dataclass
class FileNode:
    id: str
    path: str
    name: str
    language: str


@dataclass
class DefinitionNode:
    id: str
    name: str
    definition_type: str
    file_path: str


@dataclass
class BlastRadiusResult:
    changed_file: str
    affected_files: list[str]
    imported_symbols: list[dict]


class OrbitClient:
    def __init__(self, gitlab_token: str):
        self.headers = {
            "PRIVATE-TOKEN": gitlab_token,
            "Content-Type": "application/json",
        }

    def _query(self, query: dict) -> dict:
        response = requests.post(
            ORBIT_API,
            headers=self.headers,
            json={"query": query},
        )
        response.raise_for_status()
        return response.json()

    def get_project_files(self, project_full_path: str) -> list[FileNode]:
        """Get all files in a project on the default branch."""
        result = self._query({
            "query_type": "traversal",
            "nodes": [
                {
                    "id": "f",
                    "entity": "File",
                    "columns": ["path", "name", "language"],
                },
                {
                    "id": "b",
                    "entity": "Branch",
                    "filters": {"is_default": True},
                },
                {
                    "id": "p",
                    "entity": "Project",
                    "filters": {
                        "full_path": {"op": "eq", "value": project_full_path}
                    },
                },
            ],
            "relationships": [
                {"type": "ON_BRANCH", "from": "f", "to": "b"},
                {"type": "CONTAINS", "from": "p", "to": "b"},
            ],
            "limit": 100,
        })

        files = []
        for node in result.get("result", {}).get("nodes", []):
            if node["type"] == "File":
                files.append(FileNode(
                    id=node["id"],
                    path=node.get("path", ""),
                    name=node.get("name", ""),
                    language=node.get("language", ""),
                ))
        return files

    def get_definitions_in_file(self, file_node_id: str) -> list[DefinitionNode]:
        """Get all class/function/method definitions in a file."""
        result = self._query({
            "query_type": "traversal",
            "nodes": [
                {
                    "id": "f",
                    "entity": "File",
                    "node_ids": [file_node_id],
                },
                {
                    "id": "d",
                    "entity": "Definition",
                    "columns": ["name", "definition_type", "file_path"],
                },
            ],
            "relationships": [
                {"type": "DEFINES", "from": "f", "to": "d"}
            ],
            "limit": 100,
        })

        defs = []
        for node in result.get("result", {}).get("nodes", []):
            if node["type"] == "Definition":
                defs.append(DefinitionNode(
                    id=node["id"],
                    name=node.get("name", ""),
                    definition_type=node.get("definition_type", ""),
                    file_path=node.get("file_path", ""),
                ))
        return defs

    def get_blast_radius(
        self,
        module_import_path: str,
        project_files: list[str] | None = None,
    ) -> BlastRadiusResult:
        """
        Find all files that import from a given module path.
        module_import_path: Python-style e.g. 'src.auth.token'
        project_files: known file paths in the project - used to filter out cross-namespace noise.
        """
        result = self._query({
            "query_type": "traversal",
            "nodes": [
                {
                    "id": "affected_file",
                    "entity": "File",
                    "columns": ["path", "name", "language"],
                },
                {
                    "id": "sym",
                    "entity": "ImportedSymbol",
                    "columns": ["identifier_name", "import_path", "file_path"],
                    "filters": {
                        "import_path": {
                            "op": "eq",  # exact match to avoid cross-namespace noise
                            "value": module_import_path,
                        }
                    },
                },
            ],
            "relationships": [
                {"type": "IMPORTS", "from": "affected_file", "to": "sym"}
            ],
            "limit": 100,
        })

        nodes = result.get("result", {}).get("nodes", [])
        affected_files = []
        imported_symbols = []

        for node in nodes:
            if node["type"] == "File":
                path = node.get("path", "")
                # Filter to project files only if provided
                if project_files is None or path in project_files:
                    affected_files.append(path)
            elif node["type"] == "ImportedSymbol":
                imported_symbols.append({
                    "symbol": node.get("identifier_name", ""),
                    "import_path": node.get("import_path", ""),
                    "in_file": node.get("file_path", ""),
                })

        return BlastRadiusResult(
            changed_file=module_import_path,
            affected_files=affected_files,
            imported_symbols=imported_symbols,
        )

    def get_mr_changed_files(self, project_full_path: str, mr_iid: int) -> list[str]:
        """
        Get list of file paths changed in a specific MR via Orbit.
        Uses MergeRequest -> HAS_LATEST_DIFF -> MergeRequestDiff -> HAS_FILE -> MergeRequestDiffFile
        """
        result = self._query({
            "query_type": "traversal",
            "nodes": [
                {
                    "id": "mr",
                    "entity": "MergeRequest",
                    "filters": {"iid": mr_iid},
                },
                {
                    "id": "p",
                    "entity": "Project",
                    "filters": {
                        "full_path": {"op": "eq", "value": project_full_path}
                    },
                },
                {"id": "diff", "entity": "MergeRequestDiff"},
                {
                    "id": "df",
                    "entity": "MergeRequestDiffFile",
                    "columns": ["new_path", "old_path"],
                },
            ],
            "relationships": [
                {"type": "IN_PROJECT", "from": "mr", "to": "p"},
                {"type": "HAS_LATEST_DIFF", "from": "mr", "to": "diff"},
                {"type": "HAS_FILE", "from": "diff", "to": "df"},
            ],
            "limit": 100,
        })

        paths = []
        for node in result.get("result", {}).get("nodes", []):
            if node["type"] == "MergeRequestDiffFile":
                path = node.get("new_path") or node.get("old_path", "")
                if path:
                    paths.append(path)
        return paths

    def get_historical_reviewers(self, project_full_path: str) -> list[dict]:
        """Get users who have approved the most MRs in this project."""
        result = self._query({
            "query_type": "aggregation",
            "nodes": [
                {
                    "id": "u",
                    "entity": "User",
                    "columns": ["username", "name"],
                },
                {
                    "id": "mr",
                    "entity": "MergeRequest",
                    "filters": {"state": "merged"},
                },
                {
                    "id": "p",
                    "entity": "Project",
                    "filters": {
                        "full_path": {"op": "eq", "value": project_full_path}
                    },
                },
            ],
            "relationships": [
                {"type": "APPROVED", "from": "u", "to": "mr"},
                {"type": "IN_PROJECT", "from": "mr", "to": "p"},
            ],
            "group_by": [{"kind": "node", "node": "u"}],
            "aggregations": [
                {"function": "count", "target": "mr", "alias": "approvals"}
            ],
            "aggregation_sort": {"column": "approvals", "direction": "DESC"},
            "limit": 5,
        })

        reviewers = []
        for node in result.get("result", {}).get("nodes", []):
            if node["type"] == "User":
                reviewers.append({
                    "username": node.get("username", ""),
                    "name": node.get("name", ""),
                })
        return reviewers


def file_path_to_module(file_path: str) -> str:
    """Convert file path to Python module import path. e.g. src/auth/token.py -> src.auth.token"""
    return file_path.replace("/", ".").removesuffix(".py")