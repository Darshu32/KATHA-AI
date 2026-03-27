"""Re-export all ORM and schema models for convenient imports."""

from app.models.architecture import (
    ArchitectureEdge,
    ArchitectureFileFact,
    ArchitectureNode,
    ArchitectureSnapshot,
)
from app.models.orm import (
    Design,
    DesignGraphVersion,
    EstimateLineItem,
    EstimateSnapshot,
    GeneratedAsset,
    KnowledgeChunk,
    KnowledgeDocument,
    Project,
    User,
)
from app.models.design_graph import (
    AssetBundle,
    DesignGraph,
    SiteInfo,
    StyleProfile,
    build_starter_graph,
)
from app.models.schemas import (
    DesignOut,
    DesignStatus,
    DesignGraphOut,
    EstimateOut,
    ThemeEnum,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    PromptRequest,
    GenerationStatus,
)

__all__ = [
    "ArchitectureSnapshot",
    "ArchitectureNode",
    "ArchitectureEdge",
    "ArchitectureFileFact",
    # ORM
    "User",
    "Design",
    "Project",
    "DesignGraphVersion",
    "EstimateSnapshot",
    "EstimateLineItem",
    "GeneratedAsset",
    "KnowledgeDocument",
    "KnowledgeChunk",
    # Pydantic domain
    "DesignGraph",
    "StyleProfile",
    "SiteInfo",
    "AssetBundle",
    "build_starter_graph",
    # API schemas
    "ProjectCreate",
    "ProjectUpdate",
    "ProjectOut",
    "PromptRequest",
    "ThemeEnum",
    "DesignStatus",
    "DesignOut",
    "DesignGraphOut",
    "EstimateOut",
    "GenerationStatus",
]
