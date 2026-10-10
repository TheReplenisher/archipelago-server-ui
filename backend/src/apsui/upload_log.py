"""The admin's upload log (DESIGN.md §4): for every upload, who sent it, when and its hash,
every check and its result, and the worker's full error and traceback. Built from what
the upload and its job already recorded; uploaders only ever see the short error.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from apsui.models import Apworld, Job, Upload

OK, FAILED, WARNING, WAITING = "ok", "failed", "warning", "waiting"


def check(name: str, status: str, message: str = "", detail: str | None = None) -> dict[str, Any]:
    return {"name": name, "status": status, "message": message, "detail": detail or None}


def entry(item: Upload | Apworld) -> dict[str, Any]:
    kind = "apworld" if isinstance(item, Apworld) else item.kind
    return {
        "kind": kind,
        "id": item.id,
        "key": f"{kind}-{item.id}",
        "filename": item.filename,
        "sha256": item.sha256,
        "size": item.size,
        "status": item.status,
        "error_code": item.error_code,
        "error_message": item.error_message,
        "uploaded_by": item.uploaded_by,
        "uploaded_at": item.uploaded_at,
        "game_id": item.game_id if isinstance(item, Upload) else None,
    }


def detail(session: Session, item: Upload | Apworld) -> dict[str, Any]:
    job = session.get(Job, item.job_id) if item.job_id else None
    checks = apworld_checks(item) if isinstance(item, Apworld) else yaml_checks(item, job)
    return entry(item) | {"checks": checks, "job": job_detail(job)}


def job_detail(job: Job | None) -> dict[str, Any] | None:
    if job is None:
        return None
    result = job.result or {}
    error = result.get("error") or {}
    return {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "submitted_at": job.submitted_at,
        "finished_at": job.finished_at,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "traceback": error.get("traceback"),
        "log_tail": result.get("log_tail") or None,
    }


def _job_check(name: str, job: Job | None) -> dict[str, Any] | None:
    """A failed or unfinished job, as a check; None when it finished ok."""
    if job is None:
        return check(name, WAITING, "Not run")
    if job.status in ("queued", "running"):
        return check(name, WAITING, f"Worker job {job.status}")
    if job.status != "ok":
        return check(name, FAILED, f"Worker job {job.status}: {job.error_message or ''}".strip())
    return None


def yaml_checks(upload: Upload, job: Job | None) -> list[dict[str, Any]]:
    checks = [check("Stored", OK, f"{upload.size} bytes")]
    failed = _job_check("Worker check", job)
    if failed is not None:
        return [*checks, failed]
    output = (job.result or {}).get("output") or {} if job else {}
    error = output.get("error")
    if error:
        return [*checks, check("Parse", FAILED, error.get("message", ""), error.get("detail"))]
    checks.append(check("Parse", OK, f"{len(output.get('documents', []))} documents"))
    for doc in output.get("documents", []):
        if doc.get("empty"):
            continue
        label = f"Document {doc['index'] + 1}"
        if doc.get("name"):
            label += f" ({doc['name']})"
        games = ", ".join(doc.get("games", []))
        doc_error, name_error = doc.get("error"), doc.get("name_error")
        if doc_error:
            checks.append(
                check(label, FAILED, doc_error.get("message", ""), doc_error.get("detail"))
            )
        elif name_error:
            checks.append(check(label, WARNING, name_error.get("message", "")))
        else:
            checks.append(check(label, OK, games))
        for warning in doc.get("warnings", []):
            checks.append(check(label, WARNING, warning))
    for problem in upload.name_problems or []:
        renamed = problem.get("new_name")
        message = problem.get("message", "")
        if renamed:
            checks.append(check("Slot name", OK, f"{message}; renamed to {renamed}"))
        elif upload.status == "needs-name":
            checks.append(check("Slot name", WAITING, f"{message}; waiting for a new name"))
    if upload.worlds:
        games = ", ".join(sorted(upload.worlds))
        checks.append(check("Custom apworlds", OK, f"Checked with library apworlds for {games}"))
    checks.append(_outcome(upload.status, upload.error_code, upload.error_message))
    return checks


def apworld_checks(apworld: Apworld) -> list[dict[str, Any]]:
    if apworld.module is None:  # refused by the static inspection
        return [
            check("Static inspection", FAILED, apworld.error_message or ""),
            _outcome(apworld.status, apworld.error_code, apworld.error_message),
        ]
    checks = [
        check("Static inspection", OK, f"{len(apworld.files or [])} files, game {apworld.game}")
    ]
    result = apworld.import_result
    if result is None:
        checks.append(check("Import test", WAITING, "Running"))
    elif "loaded" in result:
        if result["loaded"]:
            checks.append(check("Import test", OK, f"Loaded {', '.join(result.get('games', []))}"))
        else:
            checks.append(
                check("Import test", FAILED, result.get("error") or "", result.get("detail"))
            )
    else:  # the job itself failed
        error = result.get("error") or {}
        checks.append(
            check("Import test", FAILED, error.get("message", ""), error.get("traceback"))
        )
    if apworld.replaces_builtin:
        checks.append(
            check(
                "Built-in world",
                WARNING,
                f"Replaces the built-in {apworld.game} {apworld.replaces_builtin}",
            )
        )
    checks.append(_outcome(apworld.status, apworld.error_code, apworld.error_message))
    return checks


def _outcome(status: str, code: str | None, message: str | None) -> dict[str, Any]:
    if status in ("accepted", "approved"):
        return check("Result", OK, status.capitalize())
    if status == "removed":
        return check("Result", OK, "Accepted, then removed by the admin")
    if status == "rejected":
        return check("Result", FAILED, f"{code}: {message}" if code else "Rejected")
    return check("Result", WAITING, status)
