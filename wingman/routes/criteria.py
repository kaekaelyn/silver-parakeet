"""Criteria profiles editor."""

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from wingman import db, scoring
from wingman.boolquery import QueryError, compile_query
from wingman.web import settings_of, templates

router = APIRouter()


def _form_dict(criteria_id: int, name: str, config: scoring.CriteriaConfig) -> dict:
    """Flat dict shaped for criteria_form.html — one source for the field list."""
    return {
        "id": criteria_id,
        "name": name,
        "query": config.query,
        "nice_to_have": ", ".join(config.nice_to_have),
        "exclude": ", ".join(config.exclude),
        "company_blocklist": ", ".join(config.company_blocklist),
        "remote_only": config.remote_only,
        "salary_floor": config.salary_floor if config.salary_floor is not None else "",
        "freshness_days": config.freshness_days if config.freshness_days is not None else "",
    }


EMPTY_FORM = _form_dict(0, "", scoring.CriteriaConfig())


def _criteria_rows(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM criteria ORDER BY id").fetchall()
    out = []
    for row in rows:
        config = scoring.CriteriaConfig.model_validate(json.loads(row["config_json"] or "{}"))
        out.append(
            dict(row) | {"config": config, "form": _form_dict(row["id"], row["name"], config)}
        )
    return out


def _page(
    request: Request, form: dict | None, error: str | None, status_code: int = 200
) -> HTMLResponse:
    with db.session(settings_of(request).db_path) as conn:
        criteria = _criteria_rows(conn)
        threshold = scoring.get_threshold(conn)
    return templates.TemplateResponse(
        request,
        "criteria.html",
        {
            "criteria": criteria,
            "threshold": threshold,
            "form": form,
            "error": error,
            "empty_form": EMPTY_FORM,
        },
        status_code=status_code,
    )


@router.get("/criteria", response_class=HTMLResponse)
def criteria_page(request: Request) -> HTMLResponse:
    return _page(request, form=None, error=None)


@router.post("/criteria/save", response_class=HTMLResponse)
def save_criteria(
    request: Request,
    criteria_id: int = Form(0),
    name: str = Form(...),
    query: str = Form(""),
    nice_to_have: str = Form(""),
    exclude: str = Form(""),
    company_blocklist: str = Form(""),
    remote_only: bool = Form(False),
    salary_floor: str = Form(""),
    freshness_days: str = Form(""),
) -> Response:
    def split_terms(raw: str) -> list[str]:
        return [t.strip() for t in raw.split(",") if t.strip()]

    clean_name = name.strip() or "Unnamed"
    try:
        compile_query(query)
        config = scoring.CriteriaConfig(
            query=query.strip(),
            nice_to_have=split_terms(nice_to_have),
            exclude=split_terms(exclude),
            company_blocklist=split_terms(company_blocklist),
            remote_only=remote_only,
            salary_floor=int(salary_floor) if salary_floor.strip() else None,
            freshness_days=int(freshness_days) if freshness_days.strip() else None,
        )
    except (QueryError, ValueError) as exc:
        failed_form = {
            "id": criteria_id,
            "name": clean_name,
            "query": query.strip(),
            "nice_to_have": nice_to_have,
            "exclude": exclude,
            "company_blocklist": company_blocklist,
            "remote_only": remote_only,
            "salary_floor": salary_floor,
            "freshness_days": freshness_days,
        }
        return _page(request, failed_form, str(exc), status_code=422)
    with db.session(settings_of(request).db_path) as conn:
        if criteria_id:
            conn.execute(
                "UPDATE criteria SET name = ?, config_json = ? WHERE id = ?",
                (clean_name, config.model_dump_json(), criteria_id),
            )
        else:
            conn.execute(
                "INSERT INTO criteria (name, config_json) VALUES (?, ?)",
                (clean_name, config.model_dump_json()),
            )
        conn.commit()
        db.record_event(conn, "criteria.saved", json.dumps({"name": clean_name}))
        scoring.rescore_all(conn)
    return RedirectResponse("/criteria", status_code=303)


@router.post("/criteria/{criteria_id}/toggle")
def toggle_criteria(request: Request, criteria_id: int) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        conn.execute("UPDATE criteria SET enabled = 1 - enabled WHERE id = ?", (criteria_id,))
        conn.commit()
        db.record_event(conn, "criteria.toggled", json.dumps({"id": criteria_id}))
        scoring.rescore_all(conn)
    return RedirectResponse("/criteria", status_code=303)


@router.post("/criteria/{criteria_id}/delete")
def delete_criteria(request: Request, criteria_id: int) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        conn.execute("DELETE FROM criteria WHERE id = ?", (criteria_id,))
        conn.commit()
        db.record_event(conn, "criteria.deleted", json.dumps({"id": criteria_id}))
        scoring.rescore_all(conn)
    return RedirectResponse("/criteria", status_code=303)
