"""Version du code executé.

Expose dans le rapport et le journal : un resultat doit toujours pouvoir etre
rattache a la version du code qui l'a produit.
"""

from __future__ import annotations

from . import __version__


def code_version() -> str:
    """Version courte du code, lue dans les rapports et le journal."""
    return f"etatmajor/{__version__}"
