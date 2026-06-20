import requests


GITLAB_API = "https://gitlab.com/api/v4"


class GitLabClient:
    def __init__(self, token: str):
        self.headers = {
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
        }

    def get_mr(self, project_id: int | str, mr_iid: int) -> dict:
        """Get MR details by project ID and MR internal ID."""
        response = requests.get(
            f"{GITLAB_API}/projects/{project_id}/merge_requests/{mr_iid}",
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()

    def get_mr_changed_files(self, project_id: int | str, mr_iid: int) -> list[str]:
        """Get list of file paths changed in an MR."""
        response = requests.get(
            f"{GITLAB_API}/projects/{project_id}/merge_requests/{mr_iid}/diffs",
            headers=self.headers,
            params={"per_page": 100},
        )
        response.raise_for_status()
        diffs = response.json()
        return [d["new_path"] for d in diffs if d.get("new_path")]

    def post_mr_comment(self, project_id: int | str, mr_iid: int, body: str) -> dict:
        """Post a comment on an MR."""
        response = requests.post(
            f"{GITLAB_API}/projects/{project_id}/merge_requests/{mr_iid}/notes",
            headers=self.headers,
            json={"body": body},
        )
        response.raise_for_status()
        return response.json()

    def get_project(self, project_id: int | str) -> dict:
        """Get project details."""
        response = requests.get(
            f"{GITLAB_API}/projects/{project_id}",
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()