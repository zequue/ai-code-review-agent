"""Publica una revisión en un pull request de GitHub.

Solo sale de la máquina el resultado de la revisión (reporte y comentarios), nunca el código:
el código ya está en GitHub, y el modelo corrió local.
"""

import os

import requests

from reviewer.models import Finding, Review
from reviewer.report import CATEGORY_LABEL, merge, merged_severity, render_markdown, sources_label

API = "https://api.github.com"
TIMEOUT_S = 30


class GitHubError(RuntimeError):
    pass


def _session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return s


def _comment_body(f: Finding, extra: Finding | None) -> str:
    category = CATEGORY_LABEL.get(f.category, f.category)
    header = f"**{merged_severity(f, extra).upper()}** · {category} · {sources_label(f, extra)}"
    body = f"{header}\n\n{f.message}"
    suggestion = f.suggestion or (extra.suggestion if extra else None)
    if suggestion:
        body += f"\n\n**Sugerencia:** {suggestion}"
    return body


def inline_comments(review: Review) -> list[dict]:
    """Un comentario por hallazgo, solo en líneas que el diff agrega (GitHub rechaza el resto)."""
    comments = []
    for findings, blocking in ((review.verdict.blocking, True), (review.verdict.comments, False)):
        for f, extra in merge(findings):
            if f.line is None or f.line not in review.changed_lines.get(f.file, []):
                continue  # p. ej. un test que falla fuera del diff: queda en el cuerpo del review
            prefix = "⛔ Bloqueante · " if blocking else ""
            comments.append(
                {
                    "path": f.file,
                    "line": f.line,
                    "side": "RIGHT",
                    "body": prefix + _comment_body(f, extra),
                }
            )
    return comments


def post_review(
    review: Review, pr_number: int, repo: str | None = None, token: str | None = None
) -> dict:
    """Publica el review. Devuelve {"url", "event", "note"}."""
    repo = repo or os.environ.get("GITHUB_REPO", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token:
        raise GitHubError("Faltan GITHUB_REPO o GITHUB_TOKEN en el .env")

    session = _session(token)
    pr = session.get(f"{API}/repos/{repo}/pulls/{pr_number}", timeout=TIMEOUT_S)
    if pr.status_code != 200:
        raise GitHubError(f"No se pudo leer el PR #{pr_number}: {pr.status_code} {pr.text[:200]}")
    pr_data = pr.json()

    event = "APPROVE" if review.verdict.approved else "REQUEST_CHANGES"
    payload = {
        "commit_id": pr_data["head"]["sha"],
        "body": render_markdown(review),
        "event": event,
        "comments": inline_comments(review),
    }
    url = f"{API}/repos/{repo}/pulls/{pr_number}/reviews"
    resp = session.post(url, json=payload, timeout=TIMEOUT_S)

    note = None
    if resp.status_code == 422 and "own pull request" in resp.text:
        # GitHub no deja aprobar ni pedir cambios en un PR propio. Con un token de bot o una
        # GitHub App el veredicto se aplica; acá se publica como comentario.
        note = f"GitHub no permite {event} sobre un PR propio: se publicó como comentario."
        payload["event"] = "COMMENT"
        resp = session.post(url, json=payload, timeout=TIMEOUT_S)
    if resp.status_code not in (200, 201):
        raise GitHubError(f"GitHub rechazó el review: {resp.status_code} {resp.text[:300]}")

    return {"url": resp.json().get("html_url"), "event": payload["event"], "note": note}
