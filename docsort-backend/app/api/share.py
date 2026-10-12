from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.core.database import get_supabase_sync
from app.core.document_access import get_writable_document
from app.core.concurrency import run_blocking_io
from app.core.security import get_current_user
from app.core.rate_limit import limiter
from app.schemas.share_schema import (
    ShareLinkAccess,
    ShareLinkCreate,
    ShareLinkResponse,
    ShareLinkRevocationResponse,
    ShareLinkSummary,
)
from app.services.activity_service import activity_service
from app.services.share_service import share_service

router = APIRouter(prefix="/share", tags=["share"])


@router.post("/link", response_model=ShareLinkResponse)
async def create_share_link(
    payload: ShareLinkCreate,
    user: dict = Depends(get_current_user),
):
    """Create a time-limited public link for a document the caller may modify."""
    supabase = get_supabase_sync()

    # External sharing is a mutation-like privilege: regular users may share
    # only their own documents; administrators acting within their assigned department may share department docs.
    document = await run_blocking_io(
        get_writable_document,
        supabase,
        payload.document_id,
        user,
        "id, filename",
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    result = await run_blocking_io(
        share_service.create_public_link,
        document_id=payload.document_id,
        created_by=user["id"],
        expires_in_hours=payload.expires_in_hours,
        password=payload.password,
    )
    await run_blocking_io(
        activity_service.log_share,
        user["id"],
        user.get("department_id"),
        payload.document_id,
    )
    return {
        "share_id": result["share_id"],
        "url": f"/share/access/{result['token']}",
        "expires_at": result["expires_at"],
    }


@router.get("/links/{document_id}", response_model=list[ShareLinkSummary])
async def list_share_links(
    document_id: str,
    user: dict = Depends(get_current_user),
):
    """List public-link metadata for a document the caller may modify."""
    supabase = get_supabase_sync()
    document = await run_blocking_io(
        get_writable_document,
        supabase,
        document_id,
        user,
        "id",
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    return await run_blocking_io(share_service.list_public_links, document_id)


@router.delete("/link/{share_id}", response_model=ShareLinkRevocationResponse)
async def revoke_share_link(
    share_id: str,
    user: dict = Depends(get_current_user),
):
    """Deactivate a public link when the caller may modify its document."""
    metadata = await run_blocking_io(
        share_service.get_public_link_metadata, share_id
    )
    if not metadata:
        raise HTTPException(status_code=404, detail="Share link not found.")

    supabase = get_supabase_sync()
    document = await run_blocking_io(
        get_writable_document,
        supabase,
        metadata["document_id"],
        user,
        "id",
    )
    if not document:
        # Keep unauthorized and nonexistent management targets indistinguishable.
        raise HTTPException(status_code=404, detail="Share link not found.")

    result = await run_blocking_io(share_service.revoke_public_link, share_id)
    if not result:
        raise HTTPException(status_code=404, detail="Share link not found.")

    await run_blocking_io(
        activity_service.log,
        user["id"],
        user.get("department_id"),
        "share_revoke",
        metadata["document_id"],
    )
    return result


@router.get("/access/{token}")
async def access_shared_document(token: str, response: Response):
    """Access a passwordless public link.

    Password-protected links intentionally require POST so passwords do not
    appear in URLs, browser history, proxies, or access logs.
    """
    result = await run_blocking_io(share_service.access_public_link, token)
    if not result:
        raise HTTPException(status_code=404, detail="Share link is invalid or expired.")
    if result.get("password_required"):
        raise HTTPException(status_code=401, detail="Share link password required.")
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/access/{token}")
@limiter.limit("10/minute")
async def access_password_protected_document(request: Request, token: str, payload: ShareLinkAccess, response: Response):
    """Access a public link with an optional password in the request body."""
    result = await run_blocking_io(
        share_service.access_public_link, token, payload.password
    )
    if not result:
        raise HTTPException(status_code=404, detail="Share link is invalid or expired.")
    if result.get("password_required"):
        raise HTTPException(status_code=401, detail="Invalid share link password.")
    response.headers["Cache-Control"] = "no-store"
    return result
