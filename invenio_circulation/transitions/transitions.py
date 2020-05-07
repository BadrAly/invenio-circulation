# -*- coding: utf-8 -*-
#
# Copyright (C) 2018-2020 CERN.
# Copyright (C) 2018-2020 RERO.
#
# Invenio-Circulation is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.

"""Invenio Circulation custom transitions."""

from flask import current_app
from invenio_db import db

from invenio_circulation.proxies import current_circulation

from ..api import can_be_requested, get_available_item_by_doc_pid, \
    get_document_pid_by_item_pid, get_pending_loans_by_doc_pid, \
    is_item_at_desk_available_for_checkout
from ..errors import ItemDoNotMatchError, ItemNotAvailableError, \
    LoanMaxExtensionError, RecordCannotBeRequestedError, \
    TransitionConditionsFailedError, TransitionConstraintsViolationError
from ..transitions.base import Transition
from ..transitions.conditions import is_same_location


def _ensure_valid_loan_duration(loan):
    """Validate start and end dates for a loan."""
    loan.setdefault("start_date", loan["transaction_date"])

    if not loan.get("end_date"):
        get_loan_duration = current_app.config["CIRCULATION_POLICIES"][
            "checkout"
        ]["duration_default"]
        duration = get_loan_duration(loan)
        loan["end_date"] = loan["start_date"] + duration

    is_duration_valid = current_app.config["CIRCULATION_POLICIES"]["checkout"][
        "duration_validate"
    ]
    if not is_duration_valid(loan):
        msg = "The loan duration from '{0}' to '{1}' is not valid.".format(
            loan["start_date"].isoformat(), loan["end_date"].isoformat()
        )
        raise TransitionConstraintsViolationError(description=msg)


def _ensure_item_attached_to_loan(loan):
    """Validate that an item is attached to a loan."""
    if not loan.get("item_pid"):
        msg = "No item assigned to loan '{0}'.".format(loan.id)
        raise TransitionConditionsFailedError(description=msg)


def ensure_same_item(f):
    """Validate that the item PID exists and cannot be changed."""
    def inner(self, loan, **kwargs):
        item_pid = kwargs.get("item_pid")

        if item_pid:
            if not current_app.config["CIRCULATION_ITEM_EXISTS"](item_pid):
                msg = "Item '{0}:{1}' not found in the system".format(
                    item_pid["type"], item_pid["value"]
                )
                raise ItemNotAvailableError(description=msg)

            wrong_pid_value = loan.get("item_pid") and \
                item_pid["value"] != loan["item_pid"]["value"]
            wrong_pid_type = loan.get("item_pid") and \
                item_pid["type"] != loan["item_pid"]["type"]
            if wrong_pid_value or wrong_pid_type:
                msg = "Cannot change item '{0}:{1}' while performing an " \
                      "action on this loan" \
                    .format(item_pid["type"], item_pid["value"])
                raise ItemDoNotMatchError(description=msg)

        return f(self, loan, **kwargs)

    return inner


def _update_document_pending_request_for_item(item_pid, **kwargs):
    """Update pending loans on a Document with no Item attached yet.

    :param item_pid: a dict containing `value` and `type` fields to
        uniquely identify the item.
    """
    document_pid = get_document_pid_by_item_pid(item_pid)
    for pending_loan in get_pending_loans_by_doc_pid(document_pid):
        pending_loan["item_pid"] = item_pid
        pending_loan.commit()
        db.session.commit()
        current_circulation.loan_indexer().index(pending_loan)


def _ensure_valid_extension(loan):
    """Validate end dates for a extended loan."""
    extension_count = loan.get("extension_count", 0)
    extension_count += 1

    get_extension_max_count_func = current_app.config["CIRCULATION_POLICIES"][
        "extension"
    ]["max_count"]
    extension_max_count = get_extension_max_count_func(loan)
    if extension_count > extension_max_count:
        raise LoanMaxExtensionError(
            loan_pid=loan["pid"], extension_count=extension_max_count
        )
    loan["extension_count"] = extension_count

    get_extension_duration_func = current_app.config["CIRCULATION_POLICIES"][
        "extension"
    ]["duration_default"]
    duration = get_extension_duration_func(loan)

    should_extend_from_end_date = current_app.config["CIRCULATION_POLICIES"][
        "extension"
    ]["from_end_date"]
    if not should_extend_from_end_date:
        # extend from the transaction_date instead
        loan["end_date"] = loan["transaction_date"]

    loan["end_date"] += duration


def _ensure_same_location(item_pid, location_pid, destination, error_msg):
    """Validate that item location is same as given location."""
    if not is_same_location(item_pid, location_pid):
        error_msg += " Transition to '{}' has failed.".format(destination)
        raise TransitionConditionsFailedError(description=error_msg)


def _ensure_not_same_location(item_pid, location_pid, destination, error_msg):
    """Validate that item location is not the same as given location."""
    if is_same_location(item_pid, location_pid):
        error_msg += " Transition to '{}' has failed.".format(destination)
        raise TransitionConditionsFailedError(description=error_msg)


def _get_item_location(item_pid):
    """Retrieve Item location based on PID."""
    return current_app.config["CIRCULATION_ITEM_LOCATION_RETRIEVER"](item_pid)


def _ensure_default_pickup_location(loan, context):
    """Set default pickup location if no one."""
    if not context.get("pickup_location_pid") \
            or "pickup_location_pid" not in loan:
        loan['pickup_location_pid'] = _get_item_location(loan['item_pid'])


class ToItemOnLoan(Transition):
    """Action to checkout."""

    def before(self, loan, **kwargs):
        """Validate checkout action."""
        super().before(loan, **kwargs)

        self.ensure_item_is_available_for_checkout(loan)

        _ensure_default_pickup_location(loan, kwargs)

        _ensure_valid_loan_duration(loan)


class ItemAtDeskToItemOnLoan(Transition):
    """Check-out action to perform a loan when item ready at desk."""

    def before(self, loan, **kwargs):
        """Validate checkout action."""
        super().before(loan, **kwargs)

        self.ensure_at_desk_item_is_available_for_checkout(loan)

        _ensure_default_pickup_location(loan, kwargs)

        _ensure_valid_loan_duration(loan)

    def ensure_at_desk_item_is_available_for_checkout(self, loan):
        """Validate that an item at desk is available for checkout."""
        self._check_item_before_availability(loan)

        # patron_pid is mandatory for next steps
        if 'patron_pid' not in loan:
            msg = "Patron not set for loan with pid '{}'".format(loan['pid'])
            raise TransitionConstraintsViolationError(description=msg)

        is_available = is_item_at_desk_available_for_checkout(
            loan['item_pid'],
            loan['patron_pid']
        )
        if not is_available:
            raise ItemNotAvailableError(
                item_pid=loan['item_pid'], transition=self.dest)


def check_request_on_document(f):
    """Decorator to check if the request is on document."""
    def inner(self, loan, **kwargs):
        document_pid = kwargs.get("document_pid")
        if document_pid and not kwargs.get("item_pid"):
            if not can_be_requested(loan):
                msg = "Cannot create a request for the document '{}'".format(
                    loan.get("document_pid")
                )
                raise RecordCannotBeRequestedError(description=msg)

            if self.assign_item:
                available_item_pid = get_available_item_by_doc_pid(
                    document_pid
                )
                if available_item_pid:
                    kwargs["item_pid"] = available_item_pid

        if kwargs.get("item_pid") and not kwargs.get("pickup_location_pid"):
            # if no pickup location was specified in the request,
            # assign a default one
            kwargs["pickup_location_pid"] = _get_item_location(
                kwargs["item_pid"])

        return f(self, loan, **kwargs)
    return inner


class CreatedToPending(Transition):
    """Action to request to loan an item."""

    def __init__(
        self, src, dest, trigger="next", permission_factory=None, **kwargs
    ):
        """Constructor."""
        super().__init__(
            src,
            dest,
            trigger=trigger,
            permission_factory=permission_factory,
            **kwargs
        )
        self.assign_item = kwargs.get("assign_item", True)

    @check_request_on_document
    def before(self, loan, **kwargs):
        """Check if the loan request can be created."""
        super().before(loan, **kwargs)

        if not can_be_requested(loan):
            msg = "Cannot create a request for the loan '{}'".format(loan)
            raise RecordCannotBeRequestedError(description=msg)


class PendingToItemAtDesk(Transition):
    """Validate pending request to prepare the item at desk of its location."""

    def before(self, loan, **kwargs):
        """Validate if the item is for this location or should transit."""
        super().before(loan, **kwargs)

        # check if a request on document has no item attached
        _ensure_item_attached_to_loan(loan)
        _ensure_same_location(
            loan["item_pid"],
            loan["pickup_location_pid"],
            self.dest,
            error_msg="Pickup is not at the same library. ",
        )


class PendingToItemInTransitPickup(Transition):
    """Validate pending request to send the item to the pickup location."""

    def before(self, loan, **kwargs):
        """Validate if the item is for this location or should transit."""
        super().before(loan, **kwargs)

        # check if a request on document has no item attached
        _ensure_item_attached_to_loan(loan)
        _ensure_not_same_location(
            loan["item_pid"],
            loan["pickup_location_pid"],
            self.dest,
            error_msg="Pickup is at the same library. ",
        )


class ItemOnLoanToItemOnLoan(Transition):
    """Extend action to perform a item loan extension."""

    @ensure_same_item
    def before(self, loan, **kwargs):
        """Validate extension action."""
        super().before(loan, **kwargs)
        _ensure_valid_extension(loan)


class ItemOnLoanToItemInTransitHouse(Transition):
    """Check-in action when returning an item not to its belonging location."""

    @ensure_same_item
    def before(self, loan, **kwargs):
        """Validate check-in action."""
        super().before(loan, **kwargs)

        _ensure_not_same_location(
            loan["item_pid"],
            loan["transaction_location_pid"],
            self.dest,
            error_msg="Item should be returned (already in house). ",
        )

        # set end loan date as transaction date when completing loan
        loan["end_date"] = loan["transaction_date"]


class ItemOnLoanToItemReturned(Transition):
    """Check-in action when returning an item to its belonging location."""

    def __init__(
        self, src, dest, trigger="next", permission_factory=None, **kwargs
    ):
        """Constructor."""
        super().__init__(
            src,
            dest,
            trigger=trigger,
            permission_factory=permission_factory,
            **kwargs
        )
        self.assign_item = kwargs.get("assign_item", True)

    @ensure_same_item
    def before(self, loan, **kwargs):
        """Validate check-in action."""
        super().before(loan, **kwargs)

        _ensure_same_location(
            loan["item_pid"],
            loan["transaction_location_pid"],
            self.dest,
            error_msg="Item should be in transit to house.",
        )

        # set end loan date as transaction date when completing loan
        loan["end_date"] = loan["transaction_date"]

    def after(self, loan):
        """Check for pending requests on this item after check-in."""
        super().after(loan)
        if self.assign_item:
            _update_document_pending_request_for_item(loan["item_pid"])


class ItemInTransitHouseToItemReturned(Transition):
    """Check-in action when returning an item to its belonging location."""

    def __init__(
        self, src, dest, trigger="next", permission_factory=None, **kwargs
    ):
        """Constructor."""
        super().__init__(
            src,
            dest,
            trigger=trigger,
            permission_factory=permission_factory,
            **kwargs
        )
        self.assign_item = kwargs.get("assign_item", True)

    @ensure_same_item
    def before(self, loan, **kwargs):
        """Validate check-in action."""
        super().before(loan, **kwargs)

        _ensure_same_location(
            loan["item_pid"],
            loan["transaction_location_pid"],
            self.dest,
            error_msg="Item should be in transit to house.",
        )

    def after(self, loan):
        """Check for pending requests on this item after check-in."""
        super().after(loan)
        if self.assign_item:
            _update_document_pending_request_for_item(loan["item_pid"])


class ToCancelled(Transition):
    """When cancelling a loan, ensure that the item is not changed."""

    @ensure_same_item
    def before(self, loan, **kwargs):
        """Validate cancel action."""
        super().before(loan, **kwargs)
