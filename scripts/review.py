#!/usr/bin/env python3
"""Ask an LLM to review a filtered Terraform plan and post the results as a
sticky comment on the pull request.

Provider selection is controlled by the LLM_PROVIDER environment variable
(default: "bedrock"). Only "bedrock" is implemented -- get_review() is the
branch point so a second provider can be added later without reshaping the
rest of the script.

This script never fails the build: if the Bedrock call errors out, it posts
a "review skipped" comment and exits 0. There's also no severity threshold
that fails the job -- it always just comments.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import boto3
import requests

COMMENT_MARKER = "<!-- tf-ai-review -->"

# Bedrock's invoke_model has no equivalent to the Anthropic API's structured
# outputs (output_config), so this schema is embedded in the prompt as
# guidance rather than enforced server-side -- see _parse_findings() for the
# defensive parsing that covers the gap.
FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["HIGH", "MEDIUM", "LOW"],
                    },
                    "resource": {"type": "string"},
                    "issue": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["severity", "resource", "issue", "fix"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a Terraform code reviewer. You will be given a \
filtered Terraform plan (JSON) describing the resources a pull request would \
create, update, or destroy.

Review the plan for security misconfigurations, cost concerns, and \
operational risks -- for example: overly permissive security group rules, \
public S3 buckets, overly broad IAM policies, missing encryption, or \
destructive replacements of stateful resources.

Return only findings that matter. If the plan looks fine, return an empty \
findings array rather than inventing minor nitpicks. For each finding, name \
the exact resource address, describe the issue in one or two sentences, and \
propose a concrete fix.

Respond with ONLY a single JSON object matching the schema you're given --
no markdown code fences, no commentary before or after it."""


def _parse_findings(text: str) -> list[dict[str, str]]:
    """Parse the model's JSON response, tolerating markdown code fences.

    Bedrock invoke_model has no server-side structured-outputs enforcement,
    so the model is only prompt-guided to return raw JSON -- it sometimes
    wraps the response in a ```json ... ``` fence (or adds stray text
    around it) despite the instruction not to. Handle both.
    """
    candidate = text.strip()

    fence_match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", candidate, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # Last resort: slice out the outermost braces and try again, in case
        # the model added commentary before or after the JSON object.
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError(f"Could not find a JSON object in model response: {text!r}") from None
        parsed = json.loads(candidate[start : end + 1])

    return parsed["findings"]


def get_review_bedrock(filtered_plan: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Call the Bedrock Runtime API and return a list of finding dicts.

    Credentials come from the ambient AWS session only -- in GitHub Actions
    that's the role assumed via configure-aws-credentials (OIDC). This
    function never reads or references an API key.
    """
    # Cross-region inference profile ID (the "us." prefix). Invoking the
    # plain base model ID (e.g. "anthropic.claude-sonnet-5" with no region
    # prefix) returns HTTP 400 for these models -- Bedrock requires an
    # inference profile for on-demand throughput on current Claude models,
    # it won't accept the bare model ID directly.
    model_id = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-5")

    bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Findings schema:\n\n"
                    f"{json.dumps(FINDINGS_SCHEMA, indent=2)}\n\n"
                    "Terraform plan to review:\n\n"
                    f"{json.dumps(filtered_plan, indent=2)}"
                ),
            }
        ],
    }

    response = bedrock.invoke_model(
        modelId=model_id,
        body=json.dumps(request_body),
        contentType="application/json",
        accept="application/json",
    )

    response_body = json.loads(response["body"].read())
    text = response_body["content"][0]["text"]

    return _parse_findings(text)


def get_review(filtered_plan: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Dispatch to the configured LLM provider.

    Only "bedrock" is implemented today. A second provider slots in here
    later behind the same LLM_PROVIDER switch.
    """
    provider = os.environ.get("LLM_PROVIDER", "bedrock")

    if provider == "bedrock":
        return get_review_bedrock(filtered_plan)

    raise ValueError(f"Unsupported LLM_PROVIDER: {provider!r}")


def render_markdown(findings: list[dict[str, str]]) -> str:
    """Render findings as a markdown table, or a clean-bill-of-health note."""
    if not findings:
        return "No issues found in this plan. :white_check_mark:"

    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    findings = sorted(findings, key=lambda f: severity_order.get(f["severity"], 99))

    lines = ["| Severity | Resource | Issue | Fix |", "| --- | --- | --- | --- |"]
    for finding in findings:
        severity = finding["severity"]
        resource = finding["resource"].replace("|", "\\|")
        issue = finding["issue"].replace("|", "\\|").replace("\n", " ")
        fix = finding["fix"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {severity} | `{resource}` | {issue} | {fix} |")

    return "\n".join(lines)


def build_comment_body(markdown_content: str) -> str:
    return (
        f"{COMMENT_MARKER}\n"
        "## Terraform AI Review\n\n"
        f"{markdown_content}\n\n"
        "_This review was generated automatically by Claude and may be "
        "wrong or incomplete. It does not block merging._"
    )


def find_existing_comment(repo: str, pr_number: str, token: str) -> int | None:
    """Search existing PR comments for the sticky marker; return its ID if found."""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    for comment in response.json():
        if COMMENT_MARKER in comment.get("body", ""):
            return comment["id"]

    return None


def post_comment(body: str) -> None:
    """Create or update the sticky PR comment (searches for COMMENT_MARKER)."""
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    pr_number = os.environ["PR_NUMBER"]

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    existing_comment_id = find_existing_comment(repo, pr_number, token)

    if existing_comment_id is not None:
        url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_comment_id}"
        response = requests.patch(url, headers=headers, json={"body": body}, timeout=30)
    else:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        response = requests.post(url, headers=headers, json={"body": body}, timeout=30)

    response.raise_for_status()


def main() -> int:
    filtered_path = Path(sys.argv[1] if len(sys.argv) > 1 else "filtered.json")
    filtered_plan = json.loads(filtered_path.read_text())

    if not filtered_plan:
        post_comment(build_comment_body("No resource changes in this plan."))
        return 0

    try:
        findings = get_review(filtered_plan)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: never fail the build
        print(f"Bedrock review failed, skipping: {exc}", file=sys.stderr)
        post_comment(
            f"{COMMENT_MARKER}\n"
            "## Terraform AI Review\n\n"
            "_Review skipped: the Bedrock call failed. This does not "
            "block merging._"
        )
        return 0

    post_comment(build_comment_body(render_markdown(findings)))
    return 0


if __name__ == "__main__":
    sys.exit(main())