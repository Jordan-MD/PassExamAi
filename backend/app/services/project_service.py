import logging
from typing import Optional
from app.db.supabase_client import supabase

logger = logging.getLogger(__name__)


class ProjectService:

    @staticmethod
    def create(
        user_id: str,
        title: str,
        subject: Optional[str] = None,
        target_exam_type: Optional[str] = None,
        deadline: Optional[str] = None,       # ISO date "2026-06-15"
        hours_per_day: float = 2.0,
        days_per_week: int = 5,
    ) -> dict:
        result = supabase.table("projects").insert({
            "user_id": user_id,
            "title": title,
            "subject": subject,
            "target_exam_type": target_exam_type,
            "deadline": deadline,
            "hours_per_day": hours_per_day,
            "days_per_week": days_per_week,
        }).execute()

        if not result.data:
            raise RuntimeError("Erreur lors de la création du projet")

        logger.info(f"Projet créé: {result.data[0]['id']} pour user {user_id}")
        return result.data[0]

    @staticmethod
    def update(
        project_id: str,
        user_id: str,
        *,
        title: Optional[str] = None,
        subject: Optional[str] = None,
        target_exam_type: Optional[str] = None,
        deadline: Optional[str] = None,
        hours_per_day: Optional[float] = None,
        days_per_week: Optional[int] = None,
    ) -> Optional[dict]:
        """
        Met à jour les champs fournis (partial update).
        Retourne None si le projet n'existe pas ou n'appartient pas à l'utilisateur.
        """
        existing = ProjectService.get_by_id(project_id, user_id)
        if not existing:
            return None

        # Ne met à jour que les champs explicitement fournis
        payload = {
            k: v for k, v in {
                "title": title,
                "subject": subject,
                "target_exam_type": target_exam_type,
                "deadline": deadline,
                "hours_per_day": hours_per_day,
                "days_per_week": days_per_week,
            }.items()
            if v is not None
        }

        if not payload:
            return existing  # Rien à modifier

        result = (
            supabase.table("projects")
            .update(payload)
            .eq("id", project_id)
            .execute()
        )
        return result.data[0] if result.data else None

    @staticmethod
    def get_all_by_user(user_id: str) -> list[dict]:
        result = (
            supabase.table("projects")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    @staticmethod
    def get_by_id(project_id: str, user_id: str) -> Optional[dict]:
        result = (
            supabase.table("projects")
            .select("*")
            .eq("id", project_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return result.data

    @staticmethod
    def delete(project_id: str, user_id: str) -> bool:
        existing = ProjectService.get_by_id(project_id, user_id)
        if not existing:
            return False
        supabase.table("projects").delete().eq("id", project_id).execute()
        logger.info(f"Projet {project_id} supprimé par user {user_id}")
        return True