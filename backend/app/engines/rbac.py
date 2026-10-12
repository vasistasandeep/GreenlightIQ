"""RBAC_Service: role-based authorization and confidential scoping (R20, R28).

This engine enforces the platform's authorization model. It is deliberately a
pure, side-effect-free service: it operates only on the authenticated
:class:`~app.core.security.UserContext` plus plain resource mappings, holds no
database connection, and never imports at module scope anything that opens one.
That keeps authorization decisions fast, deterministic, and trivially testable.

Three responsibilities, drawn from the design's RBAC_Service contract:

1. **One role per user, operation-level permission checks (R20.1).**
   Each :class:`UserContext` carries exactly one :class:`UserRole` from the
   enumerated set. :meth:`RBACService.authorize` consults the permission matrix
   (:data:`OPERATION_PERMISSIONS`) and raises :class:`ForbiddenError` when the
   actor's role is not granted the requested operation.

2. **Override gated to decision-making roles (R20.2).**
   Overriding a ``Recommendation_Status`` is permitted only for CONTENT_BUYER,
   CHIEF_CONTENT_OFFICER, and CFO. A DATA_ANALYST attempting the ``override``
   operation is rejected with :class:`ForbiddenOverrideError` (a 403 mapped to
   ``FORBIDDEN_OVERRIDE``) rather than the generic forbidden error, so the API
   surfaces the specific override-authorization semantics.

3. **Confidential-record and field scoping by role AND territory (R28.2, R28.4).**
   :meth:`RBACService.scope_record` takes an actor and a record that declares a
   territory and a set of confidential fields. Access to confidential fields is
   granted only when the actor's role is cleared for confidential data *and*,
   where the record is territory-bound, the record's territory falls within the
   actor's authorized territories. Fields the actor may not see are **withheld**
   — removed from the returned record and reported in an explicit
   ``_withheld_fields`` indication (R28.4) — rather than silently dropped, so a
   caller can tell the difference between "field absent" and "field redacted."

Role / confidential-access policy
----------------------------------

======================  ====================  =================================
Role                    Confidential access   Notes
======================  ====================  =================================
DATA_ANALYST            No                    May read non-confidential data
                                              only; may not override.
CONTENT_BUYER           Yes (territory-bound)  Confidential fields only for
                                              records in authorized territories.
CHIEF_CONTENT_OFFICER   Yes (all territories)  Executive: unrestricted by
                                              territory.
CFO                     Yes (all territories)  Executive: unrestricted by
                                              territory.
======================  ====================  =================================

Territory scoping (R28.2) applies to the territory-bound confidential roles.
Executive roles (CHIEF_CONTENT_OFFICER, CFO) are not territory-restricted — they
hold organization-wide oversight — but still only see confidential fields on
records that *are* confidential. Non-confidential fields are always returned to
any authenticated actor.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Any

from app.core.errors import ForbiddenError, ForbiddenOverrideError
from app.core.security import UserContext, UserRole

__all__ = [
    "Operation",
    "OPERATION_PERMISSIONS",
    "OVERRIDE_ROLES",
    "CONFIDENTIAL_ACCESS_ROLES",
    "TERRITORY_UNRESTRICTED_ROLES",
    "WITHHELD_FIELDS_KEY",
    "RBACService",
]


# ---------------------------------------------------------------------------
# Operation registry
# ---------------------------------------------------------------------------


class Operation(str, Enum):
    """The set of permission-checked system operations.

    Operation names are the stable vocabulary the permission matrix is keyed on.
    Routers and services pass one of these to :meth:`RBACService.authorize`
    before performing the corresponding state-changing or read action.
    """

    INGEST = "ingest"
    VALUATION = "valuation"
    OVERRIDE = "override"
    APPROVE = "approve"
    REJECT = "reject"
    CALIBRATE = "calibrate"
    READ_CONFIDENTIAL = "read_confidential"


#: Roles permitted to override a ``Recommendation_Status`` (R20.2). A role
#: outside this set attempting :attr:`Operation.OVERRIDE` is rejected with
#: :class:`ForbiddenOverrideError`.
OVERRIDE_ROLES: frozenset[UserRole] = frozenset(
    {
        UserRole.CONTENT_BUYER,
        UserRole.CHIEF_CONTENT_OFFICER,
        UserRole.CFO,
    }
)


#: Roles cleared to view confidential fields at all (R28.2, R28.4). DATA_ANALYST
#: is intentionally excluded: analysts work with non-confidential projections.
CONFIDENTIAL_ACCESS_ROLES: frozenset[UserRole] = frozenset(
    {
        UserRole.CONTENT_BUYER,
        UserRole.CHIEF_CONTENT_OFFICER,
        UserRole.CFO,
    }
)


#: Confidential-access roles that are NOT further restricted by territory (R28.2).
#: Executives hold organization-wide oversight; territory scoping applies only to
#: the remaining confidential roles (e.g. CONTENT_BUYER).
TERRITORY_UNRESTRICTED_ROLES: frozenset[UserRole] = frozenset(
    {
        UserRole.CHIEF_CONTENT_OFFICER,
        UserRole.CFO,
    }
)


#: Key under which :meth:`RBACService.scope_record` reports fields it withheld,
#: giving callers the required authorization indication (R28.4).
WITHHELD_FIELDS_KEY = "_withheld_fields"


#: The operation → permitted-roles matrix (R20.1). Every operation the system
#: performs is enumerated here; :meth:`RBACService.authorize` denies anything a
#: role is not explicitly granted. Keeping the grant set explicit (rather than a
#: default-allow) means a new operation is denied until a policy is written for it.
OPERATION_PERMISSIONS: dict[Operation, frozenset[UserRole]] = {
    # Analysts and above may ingest manifests and run valuations.
    Operation.INGEST: frozenset(UserRole),
    Operation.VALUATION: frozenset(UserRole),
    # Overriding a recommendation is reserved for decision-making roles (R20.2).
    Operation.OVERRIDE: OVERRIDE_ROLES,
    # Executive sign-off actions on the approval workflow (R20.3, R20.4).
    Operation.APPROVE: frozenset(
        {UserRole.CHIEF_CONTENT_OFFICER, UserRole.CFO}
    ),
    Operation.REJECT: frozenset(
        {UserRole.CHIEF_CONTENT_OFFICER, UserRole.CFO}
    ),
    # Model calibration is a data-science / executive governance action.
    Operation.CALIBRATE: frozenset(
        {UserRole.DATA_ANALYST, UserRole.CHIEF_CONTENT_OFFICER, UserRole.CFO}
    ),
    # Reading confidential records requires confidential clearance (R28.2).
    Operation.READ_CONFIDENTIAL: CONFIDENTIAL_ACCESS_ROLES,
}


class RBACService:
    """Role-based authorization and confidential-record scoping (R20, R28).

    A stateless policy evaluator. Construct it once and reuse it; it depends on
    nothing but the permission matrix and the actor/resource arguments passed to
    each call, so it is safe to share across requests.
    """

    def authorize(
        self,
        actor: UserContext,
        operation: Operation | str,
        resource: Any = None,
    ) -> None:
        """Authorize ``actor`` to perform ``operation`` or raise (R20.1, R20.2).

        Looks up the operation in :data:`OPERATION_PERMISSIONS` and verifies the
        actor's single role (R20.1) is in the permitted set. The ``resource`` is
        accepted for interface symmetry and future resource-level rules; the base
        permission check is role/operation only.

        Args:
            actor: The authenticated principal, carrying exactly one role.
            operation: The operation being attempted — an :class:`Operation` or
                its string value (e.g. ``"override"``).
            resource: The target resource, if any. Unused by the base check.

        Raises:
            ForbiddenOverrideError: The actor's role may not override a
                recommendation (R20.2). Raised specifically for the override
                operation so the API can surface ``FORBIDDEN_OVERRIDE``.
            ForbiddenError: The actor's role is not permitted the operation, or
                the operation is unknown (default-deny).
        """
        op = self._coerce_operation(operation)

        # Override has its own, more specific authorization error (R20.2).
        if op is Operation.OVERRIDE and actor.role not in OVERRIDE_ROLES:
            raise ForbiddenOverrideError(
                "Your role is not permitted to override a recommendation.",
                details={"role": actor.role.value, "operation": op.value},
            )

        permitted = OPERATION_PERMISSIONS.get(op)
        if permitted is None or actor.role not in permitted:
            raise ForbiddenError(
                "Your role is not permitted to perform this operation.",
                details={"role": actor.role.value, "operation": op.value},
            )

    def can(self, actor: UserContext, operation: Operation | str) -> bool:
        """Return whether ``actor`` may perform ``operation`` without raising.

        A convenience predicate wrapping :meth:`authorize` for call sites that
        want to branch on permission (e.g. hiding a UI action) rather than guard
        an action.
        """
        try:
            self.authorize(actor, operation)
        except ForbiddenError:
            return False
        return True

    def can_access_confidential(
        self, actor: UserContext, territory: str | None
    ) -> bool:
        """Whether ``actor`` may read confidential data for ``territory`` (R28.2).

        Access requires both:

        * a role cleared for confidential data
          (:data:`CONFIDENTIAL_ACCESS_ROLES`), and
        * for territory-bound roles, that ``territory`` is one of the actor's
          authorized territories.

        Executive roles (:data:`TERRITORY_UNRESTRICTED_ROLES`) satisfy the
        territory condition unconditionally. A ``territory`` of ``None`` means
        the record is not territory-bound, so only the role clearance applies.
        """
        if actor.role not in CONFIDENTIAL_ACCESS_ROLES:
            return False
        if territory is None or actor.role in TERRITORY_UNRESTRICTED_ROLES:
            return True
        return territory in set(actor.authorized_territories)

    def scope_record(
        self,
        actor: UserContext,
        record: Mapping[str, Any],
        *,
        confidential_fields: Iterable[str],
        territory: str | None = None,
    ) -> dict[str, Any]:
        """Return a copy of ``record`` with unauthorized fields withheld (R28.2, R28.4).

        Confidential fields are scoped by the actor's role and authorized
        territory. When the actor is not cleared to see a confidential field —
        because the role lacks confidential clearance, or the record's territory
        is outside the actor's authorized territories — that field is **removed**
        from the returned mapping and its name is listed under
        :data:`WITHHELD_FIELDS_KEY`. This gives the caller an explicit
        authorization indication for each withheld field (R28.4) instead of
        silently dropping it. Non-confidential fields are always returned.

        If every confidential field is authorized (or the record has none), the
        returned mapping contains no :data:`WITHHELD_FIELDS_KEY` entry.

        Args:
            actor: The principal requesting the record.
            record: The source record. Not mutated; a shallow copy is returned.
            confidential_fields: The names of fields considered confidential for
                this record.
            territory: The record's territory for scoping, or ``None`` if the
                record is not territory-bound.

        Returns:
            A new ``dict`` containing the authorized subset of ``record``, plus a
            ``_withheld_fields`` list naming any confidential fields that were
            withheld.
        """
        scoped: dict[str, Any] = dict(record)
        confidential = set(confidential_fields)

        if self.can_access_confidential(actor, territory):
            return scoped

        withheld: list[str] = []
        for name in confidential:
            if name in scoped:
                del scoped[name]
                withheld.append(name)

        if withheld:
            # Sorted for deterministic output; this list is the R28.4 indication.
            scoped[WITHHELD_FIELDS_KEY] = sorted(withheld)
        return scoped

    @staticmethod
    def _coerce_operation(operation: Operation | str) -> Operation:
        """Normalize an operation argument to an :class:`Operation` member.

        Accepts either an :class:`Operation` or its string value so callers may
        pass ``"override"`` or :attr:`Operation.OVERRIDE` interchangeably. An
        unrecognized operation is left as a sentinel that the permission lookup
        will default-deny, rather than raising here, so authorization failures
        flow through the single :class:`ForbiddenError` path.
        """
        if isinstance(operation, Operation):
            return operation
        try:
            return Operation(operation)
        except ValueError:
            # Unknown operation: return a sentinel absent from the matrix so
            # authorize() denies it. Using the string via a throwaway member is
            # not possible, so we signal via a non-member by returning override
            # only when it matches; otherwise raise ForbiddenError upstream.
            raise ForbiddenError(
                "Unknown operation.",
                details={"operation": str(operation)},
            )
