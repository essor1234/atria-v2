"""Docker execution mixin for SubAgentManager.

Split into :mod:`_docker_prep` (availability, file copy-in, task rewriting) and
:mod:`_docker_run` (handler wiring, run loop). ``DockerMixin`` composes both.
"""

from __future__ import annotations

from ._docker_prep import DockerPrepMixin
from ._docker_run import DockerRunMixin

__all__ = ["DockerMixin"]


class DockerMixin(DockerPrepMixin, DockerRunMixin):
    """Mixin providing Docker availability, file handling, and Docker execution."""
