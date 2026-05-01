"""Client + client-profile repositories (Stage 8)."""

from app.repositories.clients.client_repo import ClientRepository
from app.repositories.clients.profile_repo import ClientProfileRepository

__all__ = ["ClientProfileRepository", "ClientRepository"]
