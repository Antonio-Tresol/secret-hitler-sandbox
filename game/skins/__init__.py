"""Skin registry: maps skin name strings to skin classes."""

from game.skins.base import BaseSkin
from game.skins.corporate_board import CorporateBoardSkin
from game.skins.secret_hitler import SecretHitlerSkin

SKIN_REGISTRY: dict[str, type[BaseSkin]] = {
    "secret_hitler": SecretHitlerSkin,
    "corporate_board": CorporateBoardSkin,
}
