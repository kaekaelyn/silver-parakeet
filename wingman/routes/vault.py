"""Profile vault pages: contact details, documents, canned answers."""

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from wingman import db, vault
from wingman.web import settings_of, templates

router = APIRouter()


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request) -> HTMLResponse:
    with db.session(settings_of(request).db_path) as conn:
        profile = vault.get_profile(conn)
        documents = vault.list_documents(conn)
        answers = vault.list_answers(conn)
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "profile": profile,
            "documents": documents,
            "answers": answers,
            "contact_fields": vault.CONTACT_FIELDS,
            "cover_letter": profile.get(vault.COVER_LETTER_KEY, ""),
        },
    )


@router.post("/profile/contact")
async def save_contact(request: Request) -> RedirectResponse:
    form = await request.form()
    allowed = {key for key, _label in vault.CONTACT_FIELDS}
    values = {key: str(value) for key, value in form.items() if key in allowed}
    with db.session(settings_of(request).db_path) as conn:
        vault.set_profile_values(conn, values)
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/cover-letter")
def save_cover_letter(request: Request, template_text: str = Form("")) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        vault.set_profile_values(conn, {vault.COVER_LETTER_KEY: template_text})
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/documents")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form("resume"),
    name: str = Form(""),
) -> RedirectResponse:
    if kind not in vault.DOCUMENT_KINDS:
        raise HTTPException(status_code=422, detail=f"unknown document kind {kind!r}")
    content = await file.read()
    if len(content) > vault.MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="document too large (20MB max)")
    settings = settings_of(request)
    with db.session(settings.db_path) as conn:
        vault.add_document(
            conn,
            settings.documents_dir,
            kind,
            name,
            file.filename or "document",
            content,
        )
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/documents/{document_id}/default")
def make_default_document(request: Request, document_id: int) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        vault.set_default_document(conn, document_id)
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/documents/{document_id}/delete")
def remove_document(request: Request, document_id: int) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        vault.delete_document(conn, document_id)
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/answers")
def add_answer(
    request: Request,
    question_pattern: str = Form(...),
    answer: str = Form(...),
    kind: str = Form("text"),
) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        vault.add_answer(conn, question_pattern, answer, kind)
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/answers/{answer_id}/delete")
def remove_answer(request: Request, answer_id: int) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        vault.delete_answer(conn, answer_id)
    return RedirectResponse("/profile", status_code=303)
