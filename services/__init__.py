# Services package
from services.canva_service import CanvaService, canva_service, render_local_signal_card

def __getattr__(name: str):
    if name in ("NotionSyncService", "notion_sync_service", "fetch_platform_metrics"):
        import services.notion_sync as _ns
        return getattr(_ns, name)
    raise AttributeError(f"module 'services' has no attribute '{name}'")
