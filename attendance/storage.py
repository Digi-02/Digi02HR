from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible
from pathlib import Path


@deconstructible
class PrivateLetterheadStorage(FileSystemStorage):
    """File storage with no public URL for organization letterhead assets."""

    def __init__(self, location=None, base_url=None):
        private_root = Path(location or settings.PRIVATE_MEDIA_ROOT).resolve()
        public_root = Path(settings.MEDIA_ROOT).resolve()
        if private_root == public_root or public_root in private_root.parents:
            raise ValueError('Private letterhead storage must be outside MEDIA_ROOT.')
        super().__init__(location=str(private_root), base_url=None)
