from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Item
from app.schemas import ItemCreate, ItemRead

router = APIRouter(prefix="/items", tags=["items"])

DB = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[ItemRead])
def list_items(db: DB) -> list[Item]:
    return list(db.scalars(select(Item).order_by(Item.id)))


@router.post("", response_model=ItemRead, status_code=201)
def create_item(payload: ItemCreate, db: DB) -> Item:
    item = Item(name=payload.name)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
