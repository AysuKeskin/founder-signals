from __future__ import annotations

import os
from typing import Optional

from .base import EnrichmentData, EnrichmentProvider


class LinkedInProfileProvider(EnrichmentProvider):
    """Seam for a commercial people-data API (People Data Labs, Coresignal, …).

    Left as a stub on purpose: this project stays free/public, but the contract is
    here so a paid provider can be dropped in without touching the pipeline. Set
    FS_ENRICH=linkedin + FS_LINKEDIN_API_KEY and implement enrich().
    """

    name = "linkedin_api"

    def __init__(self, api_key: Optional[str] = None, endpoint: str = ""):
        self.api_key = api_key or os.environ.get("FS_LINKEDIN_API_KEY")
        self.endpoint = endpoint

    def enrich(self, name: str, company: Optional[str],
               linkedin_url: Optional[str]) -> EnrichmentData:
        if not self.api_key:
            raise NotImplementedError(
                "Set FS_LINKEDIN_API_KEY and implement LinkedInProfileProvider.enrich(), "
                "or use FS_ENRICH=auto."
            )
        raise NotImplementedError("Wire a real LinkedIn data API here.")
