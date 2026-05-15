from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import v1, v2, v3


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Generate data/index.json from all HTML files in data/
    try:
        from core.indexer_utils import generate_index
        entries = generate_index()
        print(f"[startup] index.json generated: {len(entries)} files")
    except Exception as e:
        print(f"[startup] index.json generation failed: {e}")
    yield


app = FastAPI(title="On-Call Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1.router, prefix="/v1")
app.include_router(v2.router, prefix="/v2")
app.include_router(v3.router, prefix="/v3")
