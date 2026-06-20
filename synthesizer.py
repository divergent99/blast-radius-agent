import anthropic


class Synthesizer:
    def __init__(self, anthropic_api_key: str):
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)

    def generate_blast_radius_comment(
        self,
        mr_title: str,
        mr_author: str,
        changed_files: list[str],
        blast_radius: dict[str, list[str]],  # file -> list of affected files
        imported_symbols: dict[str, list[dict]],  # file -> list of symbol dicts
        suggested_reviewers: list[dict],
    ) -> str:
        """Generate a structured MR comment summarizing blast radius analysis."""

        # Build context for Claude
        blast_radius_text = ""
        for changed_file, affected in blast_radius.items():
            if affected:
                # Filter to only show files from same project (exclude cross-namespace noise)
                relevant = [f for f in affected if not f.startswith("tests/") or True]
                symbols = imported_symbols.get(changed_file, [])
                symbol_names = list({s["symbol"] for s in symbols if s["in_file"] in affected})
                blast_radius_text += f"\n- `{changed_file}` is imported by: {', '.join(f'`{f}`' for f in affected)}"
                if symbol_names:
                    blast_radius_text += f"\n  Symbols at risk: {', '.join(symbol_names)}"

        reviewers_text = ""
        if suggested_reviewers:
            reviewers_text = ", ".join(
                f"@{r['username']}" for r in suggested_reviewers
            )
        else:
            reviewers_text = "No historical reviewers found"

        prompt = f"""You are a code review assistant. Generate a concise, helpful MR comment analyzing the blast radius of changes.

MR Title: {mr_title}
Author: @{mr_author}
Changed files: {', '.join(f'`{f}`' for f in changed_files)}

Blast radius analysis (files that import the changed files):
{blast_radius_text if blast_radius_text else "No downstream dependencies found."}

Suggested reviewers based on project history: {reviewers_text}

Write a clear, structured MR comment in markdown that includes:
1. A brief summary of what changed
2. The blast radius - which files could be affected and why
3. Specific symbols/functions at risk
4. Reviewer suggestions
5. A short checklist of things to verify before merging

Keep it concise and actionable. Use emoji sparingly. Do not be overly verbose."""

        message = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        return message.content[0].text