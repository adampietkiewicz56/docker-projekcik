import os
import logging
from datetime import datetime
from typing import List, Optional

import redis
from fastapi import FastAPI, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

from .database import SessionLocal, engine, get_db
from .models import Note, Base

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("notes-api")

app = FastAPI(title="Notes API", version="1.0.0")

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_CHANNEL = "notes-events"
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

NOTES_CREATED = Counter("notes_created_total", "Total notes created")
NOTES_DELETED = Counter("notes_deleted_total", "Total notes deleted")
NOTES_READS = Counter("notes_read_total", "Total note read operations")


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=10000)


class NoteOut(BaseModel):
    id: int
    title: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    log.info("schema ensured at startup")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        redis_client.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"not ready: {exc}")
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/notes", response_model=List[NoteOut])
def list_notes(db: Session = Depends(get_db)) -> List[Note]:
    NOTES_READS.inc()
    return db.query(Note).order_by(Note.id.desc()).all()


@app.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: int, db: Session = Depends(get_db)) -> Note:
    NOTES_READS.inc()
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="not found")
    return note


@app.post("/notes", response_model=NoteOut, status_code=201)
def create_note(payload: NoteIn, db: Session = Depends(get_db)) -> Note:
    note = Note(title=payload.title, content=payload.content)
    db.add(note)
    db.commit()
    db.refresh(note)
    NOTES_CREATED.inc()
    try:
        redis_client.publish(REDIS_CHANNEL, f"created:{note.id}:{note.title}")
    except redis.RedisError as exc:
        log.warning("redis publish failed: %s", exc)
    return note


@app.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, db: Session = Depends(get_db)) -> Response:
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(note)
    db.commit()
    NOTES_DELETED.inc()
    try:
        redis_client.publish(REDIS_CHANNEL, f"deleted:{note_id}")
    except redis.RedisError as exc:
        log.warning("redis publish failed: %s", exc)
    return Response(status_code=204)
