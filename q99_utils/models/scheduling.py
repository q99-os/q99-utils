from pydantic import BaseModel


class UMCrontab(BaseModel):
    """Cron schedule. Each field accepts standard cron syntax ('*', '0', '*/15', '1,3,5', etc.)."""
    minute: str = "*"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"


class UMTaskSchedule(BaseModel):
    """Request body for creating a scheduled task. `task_definition` is the
    registered task name (slug, e.g. 'run_file_discovery'); see UM's
    TASK_REGISTRY for what's available."""
    task_definition: str
    crontab: UMCrontab
    enabled: bool = True


__all__ = ["UMCrontab", "UMTaskSchedule"]
