"""Notes on the traffic graph.

- GET    /annotations                  a website's notes, any role
- POST   /annotations                  add one, owner or admin
- PUT    /annotations/{annotation_id}  change one, owner or admin
- DELETE /annotations/{annotation_id}  remove one, owner or admin

The roles are the ones goals and funnels use: everyone on the team reads,
owner and admin write. The row-level security policies say the same thing
(see the migration), so a route that forgot to ask would still be refused.

Session only. An API token reads statistics on a site's behalf; nothing has
needed it to read or write the team's notes.
"""
import logging
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.annotation import Annotation
from app.models.user import User
from app.models.website_member import MemberRole
from app.routers.auth import get_current_user
from app.schemas.annotation import AnnotationResponse, AnnotationWrite
from app.services.annotations_service import (
    MAX_PER_WEBSITE,
    annotations_between,
    has_room,
)
from app.services.team_service import require_website_role_or_404

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/annotations", tags=["annotations"])


def _own_annotation(db: Session, annotation_id: int, website_id: int) -> Annotation:
    """The note, if it is on this website. 404 otherwise.

    Filtered on the website the caller was just checked against, so the id of
    a note on somebody else's website finds nothing whatever the policies say.
    """
    annotation = db.query(Annotation).filter(
        Annotation.id == annotation_id,
        Annotation.website_id == website_id,
    ).first()
    if not annotation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return annotation


@router.get("", response_model=List[AnnotationResponse])
async def list_annotations(
    website_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A website's notes, oldest first. start_date and end_date are days in
    the website's time zone, both inclusive, both optional."""
    require_website_role_or_404(db, current_user.email, website_id, MemberRole.VIEWER)
    return [
        {**row, "website_id": website_id}
        for row in annotations_between(db, website_id, start_date, end_date)
    ]


@router.post("", response_model=AnnotationResponse, status_code=status.HTTP_201_CREATED)
async def create_annotation(
    body: AnnotationWrite,
    website_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a note to a day."""
    require_website_role_or_404(db, current_user.email, website_id, MemberRole.ADMIN)

    if not has_room(db, website_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A website can hold {MAX_PER_WEBSITE} notes. Delete one to add another.",
        )

    annotation = Annotation(website_id=website_id, day=body.day, note=body.note)
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    logger.info(f"Annotation created: id={annotation.id}, website_id={website_id}")
    return annotation


@router.put("/{annotation_id}", response_model=AnnotationResponse)
async def update_annotation(
    annotation_id: int,
    body: AnnotationWrite,
    website_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change a note's day or text."""
    require_website_role_or_404(db, current_user.email, website_id, MemberRole.ADMIN)

    annotation = _own_annotation(db, annotation_id, website_id)
    annotation.day = body.day
    annotation.note = body.note
    db.commit()
    db.refresh(annotation)
    return annotation


@router.delete("/{annotation_id}")
async def delete_annotation(
    annotation_id: int,
    website_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a note."""
    require_website_role_or_404(db, current_user.email, website_id, MemberRole.ADMIN)

    annotation = _own_annotation(db, annotation_id, website_id)
    db.delete(annotation)
    db.commit()
    logger.info(f"Annotation deleted: id={annotation_id}, website_id={website_id}")
    return {"success": True, "message": "Note deleted"}
