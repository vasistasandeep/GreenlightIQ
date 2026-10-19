"""Pure domain module for the Content_Eval params block (content-eval-model).

The top-level parser for the ``content_eval`` sub-object that lives under the
immutable ``model_versions.guardrail_params`` JSONB (design Component 9, R5.1,
R5.3). It composes the per-driver parsers already defined in the sibling pure
modules into a single validated :class:`ContentEvalParams` object, carrying both
the OVERALL source tag and each nested block's source tag, exactly mirroring the
full-fallback contract of :func:`app.domain.churn.parse_params`:

    parse_content_eval_params(raw) -> ContentEvalParams   # .source is the tag

The composed block carries:

- ``version_label`` (str) -- provenance label for the fitted version.
- ``fit_dataset_version`` (str | None) -- the KPI_Test_Dataset version the model
  was fitted against (``None`` when no fitted version / illustrative defaults).
- ``dominant_label_type`` (str) -- the honesty tag (e.g. ``"PROXY"``) carried
  through to every surface so proxy accuracy is never shown as real-world.
- ``link_churn_to_ltv`` (bool, DEFAULT ``False``) -- the pointer-3 opt-in toggle;
  when off (the default) today's independent ``churn_reduction_value`` behavior is
  preserved so the demo verdicts never move.
- ``viewing_hours`` -- a :class:`app.domain.viewing_hours.ViewingHoursParams`
  parsed via :func:`app.domain.viewing_hours.parse_params`.
- ``watch_time_elasticity`` / ``ad_load_receptivity`` -- the two engagement blocks
  parsed via :func:`app.domain.engagement.parse_watch_time_elasticity_params` and
  :func:`app.domain.engagement.parse_ad_load_receptivity_params`.
- ``source`` -- the OVERALL source tag (``"MODEL_VERSION"`` | ``"DEFAULTS"``).
- ``viewing_hours_source`` / ``watch_time_elasticity_source`` /
  ``ad_load_receptivity_source`` -- the per-nested-block source tags, so a caller
  can tell which slices came from the model version and which fell back.

The per-driver parsers already apply their OWN churn-style full fallback, so each
nested block independently collapses to its illustrative defaults (with its own
``"DEFAULTS"`` source) when its slice of ``content_eval`` is invalid/absent. This
top-level parser adds the provenance/toggle fields on top and classifies the
OVERALL source: it reports ``"MODEL_VERSION"`` only when ``raw`` is a usable
mapping; any non-mapping / ``None`` input yields the full default params with
source ``"DEFAULTS"`` (and every nested source ``"DEFAULTS"``). A ``content_eval``
block present but entirely malformed in its nested slices still parses (each
nested block falls back) -- matching the churn model's posture that a malformed
param set degrades to defaults rather than raising.

Versioning note: ``model_versions`` rows are immutable and
``app.engines.calibration`` forks a new version via
``create_version(..., guardrail_params=dict(active.guardrail_params))``, so a
``content_eval`` sub-object is carried forward UNCHANGED on every calibration
fork with no migration required (JSONB).

This module is pure: no I/O, no database access, no async, no global mutable
state. It imports only the Python standard library plus the sibling pure domain
modules (``viewing_hours`` and ``engagement``), so it is importable without the
application framework.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.domain import engagement as engmod
from app.domain import viewing_hours as vhmod

__all__ = [
    "DEFAULT_VERSION_LABEL",
    "DEFAULT_DOMINANT_LABEL_TYPE",
    "DEFAULT_LINK_CHURN_TO_LTV",
    "DEFAULT_CONTENT_EVAL_PARAMS",
    "ContentEvalParams",
    "parse_content_eval_params",
]

_SOURCE_MODEL_VERSION = "MODEL_VERSION"
_SOURCE_DEFAULTS = "DEFAULTS"

# Illustrative provenance defaults (no fitted version active). The dominant label
# type defaults to PROXY so any value surfaced from the defaults is honestly
# flagged as proxy rather than mislabeled as observed real-world accuracy.
DEFAULT_VERSION_LABEL = "illustrative"
DEFAULT_DOMINANT_LABEL_TYPE = "PROXY"

# The pointer-3 churn->LTV link is OFF by default so demo verdicts stay
# byte-identical until a deployment explicitly opts in.
DEFAULT_LINK_CHURN_TO_LTV = False


@dataclass(frozen=True)
class ContentEvalParams:
    """The composed, validated ``content_eval`` params block.

    ``version_label``, ``fit_dataset_version`` and ``dominant_label_type`` are
    provenance/honesty metadata. ``link_churn_to_ltv`` is the pointer-3 opt-in
    toggle (default ``False``). The three nested blocks are the per-driver params
    produced by the sibling pure modules, each already carrying its own
    full-fallback defaults. ``source`` is the OVERALL source tag; the three
    ``*_source`` fields report where each nested block came from
    (``"MODEL_VERSION"`` vs ``"DEFAULTS"``).
    """

    version_label: str
    fit_dataset_version: str | None
    dominant_label_type: str
    link_churn_to_ltv: bool
    viewing_hours: vhmod.ViewingHoursParams
    watch_time_elasticity: engmod.WatchTimeElasticityParams
    ad_load_receptivity: engmod.AdLoadReceptivityParams
    source: str
    viewing_hours_source: str
    watch_time_elasticity_source: str
    ad_load_receptivity_source: str


# The all-defaults params: illustrative provenance, link off, every nested block
# at its own illustrative defaults, and every source tag ``"DEFAULTS"``. Returned
# whenever ``content_eval`` is absent/invalid so the system always has a complete,
# usable param set.
DEFAULT_CONTENT_EVAL_PARAMS = ContentEvalParams(
    version_label=DEFAULT_VERSION_LABEL,
    fit_dataset_version=None,
    dominant_label_type=DEFAULT_DOMINANT_LABEL_TYPE,
    link_churn_to_ltv=DEFAULT_LINK_CHURN_TO_LTV,
    viewing_hours=vhmod.DEFAULT_VIEWING_HOURS_PARAMS,
    watch_time_elasticity=engmod.DEFAULT_WATCH_TIME_ELASTICITY_PARAMS,
    ad_load_receptivity=engmod.DEFAULT_AD_LOAD_RECEPTIVITY_PARAMS,
    source=_SOURCE_DEFAULTS,
    viewing_hours_source=_SOURCE_DEFAULTS,
    watch_time_elasticity_source=_SOURCE_DEFAULTS,
    ad_load_receptivity_source=_SOURCE_DEFAULTS,
)


def _coerce_label(raw: object, default: str) -> str:
    """Coerce a raw provenance label to a non-empty ``str``, else ``default``.

    A present, non-blank string is trimmed and returned; anything else (absent,
    blank, non-string) falls back to ``default``. Never raises.
    """
    if isinstance(raw, str):
        text = raw.strip()
        if text:
            return text
    return default


def _coerce_optional_label(raw: object) -> str | None:
    """Coerce a raw optional label to a non-empty ``str``, else ``None``.

    Used for ``fit_dataset_version`` which is legitimately absent (``None``) when
    no fitted version is active. Never raises.
    """
    if isinstance(raw, str):
        text = raw.strip()
        if text:
            return text
    return None


def _coerce_bool(raw: object, default: bool) -> bool:
    """Coerce a raw toggle to a ``bool``, else ``default`` (never raises).

    A real ``bool`` is returned as-is. Common JSON-ish truthy/falsey string and
    integer encodings are accepted (``"true"``/``"false"``, ``1``/``0``) so a
    JSONB value serialized as a string still parses. Anything ambiguous or absent
    falls back to ``default`` -- for the churn->LTV toggle this means defaulting
    OFF, preserving today's behavior.
    """
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):  # note: bool handled above
        if raw == 1:
            return True
        if raw == 0:
            return False
        return default
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
    return default


def parse_content_eval_params(raw: Mapping | None) -> ContentEvalParams:
    """Parse a ``content_eval`` mapping into a :class:`ContentEvalParams`.

    Returns a params object whose ``source`` is ``"MODEL_VERSION"`` when ``raw`` is
    a usable mapping, else :data:`DEFAULT_CONTENT_EVAL_PARAMS` (``source`` ==
    ``"DEFAULTS"``) for a ``None`` / non-mapping input. Mirrors the churn model's
    full-fallback contract: never raises, and any invalid/missing field collapses
    to its default. The three nested driver blocks are delegated to their own
    parsers (each applying its own full fallback and reporting its own source), so
    a partially-malformed ``content_eval`` still yields a complete param set with
    the valid slices honored (source ``"MODEL_VERSION"``) and the invalid slices
    defaulted (source ``"DEFAULTS"``).

    Unknown keys in ``raw`` are ignored (only the recognized keys are read), so a
    newer serialized block never breaks an older reader.
    """
    if not isinstance(raw, Mapping):
        return DEFAULT_CONTENT_EVAL_PARAMS

    version_label = _coerce_label(raw.get("version_label"), DEFAULT_VERSION_LABEL)
    fit_dataset_version = _coerce_optional_label(raw.get("fit_dataset_version"))
    dominant_label_type = _coerce_label(
        raw.get("dominant_label_type"), DEFAULT_DOMINANT_LABEL_TYPE
    )
    link_churn_to_ltv = _coerce_bool(
        raw.get("link_churn_to_ltv"), DEFAULT_LINK_CHURN_TO_LTV
    )

    # Each nested block is parsed by its own full-fallback parser (returning a
    # (params, source) tuple). A non-mapping slice is tolerated by those parsers
    # (they fall back to their defaults with source "DEFAULTS").
    viewing_hours_raw = raw.get("viewing_hours")
    viewing_hours_params, viewing_hours_source = vhmod.parse_params(
        viewing_hours_raw if isinstance(viewing_hours_raw, Mapping) else None
    )

    engagement_raw = raw.get("engagement")
    engagement_map = engagement_raw if isinstance(engagement_raw, Mapping) else {}
    wte_raw = engagement_map.get("watch_time_elasticity")
    alr_raw = engagement_map.get("ad_load_receptivity")
    wte_params, wte_source = engmod.parse_watch_time_elasticity_params(
        wte_raw if isinstance(wte_raw, Mapping) else None
    )
    alr_params, alr_source = engmod.parse_ad_load_receptivity_params(
        alr_raw if isinstance(alr_raw, Mapping) else None
    )

    return ContentEvalParams(
        version_label=version_label,
        fit_dataset_version=fit_dataset_version,
        dominant_label_type=dominant_label_type,
        link_churn_to_ltv=link_churn_to_ltv,
        viewing_hours=viewing_hours_params,
        watch_time_elasticity=wte_params,
        ad_load_receptivity=alr_params,
        source=_SOURCE_MODEL_VERSION,
        viewing_hours_source=viewing_hours_source,
        watch_time_elasticity_source=wte_source,
        ad_load_receptivity_source=alr_source,
    )
