"""
Tag Mapping Service - applies configurable field overrides to PCTrack before sync.

The mapping is a dict of ``{target_field: source_template}`` where
``source_template`` may be:

* A plain ``%fieldname`` token — replaced by the value of that PCTrack field.
* A composite string such as ``%tracknumber - %title`` — each ``%name``
  token is substituted; missing fields become empty strings.

If the resolved value is ``None`` (i.e. the template is a bare ``%field`` and
that field is ``None`` on the source track) the target field is **not**
overridden and a ``DEBUG`` log entry is written.  No exceptions are raised.

Example mapping::

    {
        "artist": "%album_artist",
        "title": "%tracknumber - %title",
    }
"""

import copy
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Recognises a template that is *only* a single %field token (no surrounding
# text), so we can preserve the original type of the value (e.g. int for
# track_number) instead of always returning a string.
_SINGLE_TOKEN_RE = re.compile(r'^%(\w+)$')
_TOKEN_RE = re.compile(r'%(\w+)')


class TagMappingService:
    """Applies a configurable tag-mapping to a :class:`~SyncEngine.pc_library.PCTrack`.

    The service is intentionally stateless; all logic lives in static methods
    so it can be called without instantiation.
    """

    @staticmethod
    def apply(pc_track, mapping: dict[str, str]):
        """Return a shallow copy of *pc_track* with mapped fields applied.

        If *mapping* is empty the original *pc_track* is returned unchanged
        (no copy is made).

        Args:
            pc_track: A :class:`~SyncEngine.pc_library.PCTrack` instance.
            mapping:  ``{target_field: source_template}`` dict from settings.

        Returns:
            A shallow copy of *pc_track* with overridden fields, or the
            original object when *mapping* is empty.
        """
        if not mapping:
            return pc_track

        # Build a brief track identifier for log messages (best-effort)
        _track_id = (
            getattr(pc_track, "title", None)
            or getattr(pc_track, "filename", None)
            or repr(pc_track)
        )

        result = copy.copy(pc_track)

        for target_field, source_template in mapping.items():
            if not target_field or not source_template:
                continue

            try:
                value = TagMappingService._resolve_template(
                    source_template, pc_track, target_field
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "TagMapping [%s]: error resolving template '%s' for field '%s': %s",
                    _track_id, source_template, target_field, exc,
                )
                continue

            if value is None:
                # Source field exists but is None — skip silently at DEBUG level
                logger.debug(
                    "TagMapping [%s]: source template '%s' resolved to None for target '%s' "
                    "— override skipped",
                    _track_id, source_template, target_field,
                )
                continue

            if not hasattr(result, target_field):
                logger.warning(
                    "TagMapping [%s]: target field '%s' does not exist on PCTrack — skipping",
                    _track_id, target_field,
                )
                continue

            logger.debug(
                "TagMapping [%s]: %s = %r  (template: %r)",
                _track_id, target_field, value, source_template,
            )
            setattr(result, target_field, value)

        return result

    @staticmethod
    def _resolve_template(template: str, pc_track, target_field: str):
        """Resolve *template* against *pc_track* field values.

        For a bare ``%fieldname`` template the original value (with its
        natural type) is returned so that integer fields such as
        ``track_number`` remain integers.

        For composite templates (text mixed with ``%tokens``) a string is
        always returned.  Missing fields are replaced with an empty string
        and a WARNING is emitted.

        Args:
            template:     The template string.
            pc_track:     Source :class:`~SyncEngine.pc_library.PCTrack`.
            target_field: Name of the destination field (for log messages).

        Returns:
            The resolved value, or ``None`` if a bare ``%fieldname`` template
            refers to a field whose value is ``None``.
        """
        # ── Single token: %fieldname ─────────────────────────────────────
        single = _SINGLE_TOKEN_RE.match(template)
        if single:
            field_name = single.group(1)
            if not hasattr(pc_track, field_name):
                _track_id = (
                    getattr(pc_track, "title", None)
                    or getattr(pc_track, "filename", None)
                    or repr(pc_track)
                )
                logger.warning(
                    "TagMapping [%s]: source field '%%%s' does not exist on PCTrack "
                    "(target: '%s') — override skipped",
                    _track_id, field_name, target_field,
                )
                return None
            return getattr(pc_track, field_name)  # may be None

        # ── Composite template ───────────────────────────────────────────
        def _replace(match: re.Match) -> str:
            field_name = match.group(1)
            if not hasattr(pc_track, field_name):
                _track_id = (
                    getattr(pc_track, "title", None)
                    or getattr(pc_track, "filename", None)
                    or repr(pc_track)
                )
                logger.warning(
                    "TagMapping [%s]: source field '%%%s' does not exist on PCTrack "
                    "(target: '%s') — substituted with empty string",
                    _track_id, field_name, target_field,
                )
                return ""
            val = getattr(pc_track, field_name)
            return "" if val is None else str(val)

        return _TOKEN_RE.sub(_replace, template)
