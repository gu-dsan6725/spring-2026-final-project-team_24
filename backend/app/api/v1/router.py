from fastapi import APIRouter

from app.api.v1 import auth, concepts, edges, items, groups, traversal, data_entities, extraction, vectors

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(concepts.router, prefix="/concepts", tags=["concepts"])
api_router.include_router(edges.router, prefix="/edges", tags=["edges"])
api_router.include_router(items.router, prefix="/items", tags=["items"])
api_router.include_router(vectors.router, prefix="/vectors", tags=["vectors"])
api_router.include_router(groups.router, prefix="/groups", tags=["groups"])
api_router.include_router(traversal.router, prefix="/traversal", tags=["traversal"])
api_router.include_router(data_entities.router, prefix="/data-entities", tags=["data-entities"])
api_router.include_router(extraction.router, prefix="/extract", tags=["extraction"])
