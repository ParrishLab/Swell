class SwellAppError(Exception):
    """Base exception for all Swell custom errors."""
    pass
class DataCorruptionError(SwellAppError):
    """Raised when data loaded from disk or memory is corrupted or invalid."""
    pass

class InferenceRuntimeError(SwellAppError):
    """Raised when the machine learning inference engine encounters an error (e.g., OOM, model failure)."""
    pass

class ProjectLoadError(DataCorruptionError):
    """Raised when an .swell file is malformed, corrupt, or version-mismatched."""
    pass
