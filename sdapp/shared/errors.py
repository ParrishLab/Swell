class SDAppError(Exception):
    """Base exception for all SDApp custom errors."""
    pass

class UserInputError(SDAppError):
    """Raised when the user provides invalid input that cannot be processed."""
    pass

class DataCorruptionError(SDAppError):
    """Raised when data loaded from disk or memory is corrupted or invalid."""
    pass

class InferenceRuntimeError(SDAppError):
    """Raised when the machine learning inference engine encounters an error (e.g., OOM, model failure)."""
    pass

class ProjectLoadError(DataCorruptionError):
    """Raised when an .sdproj file is malformed, corrupt, or version-mismatched."""
    pass
