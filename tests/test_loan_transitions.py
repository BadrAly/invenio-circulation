# -*- coding: utf-8 -*-
#
# Copyright (C) 2018-2020 CERN.
# Copyright (C) 2018-2020 RERO.
#
# Invenio-Circulation is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.

"""Tests for loan states."""

import copy
from datetime import timedelta

import arrow
import pytest
from flask_security import login_user

from invenio_circulation.api import get_loan_for_item, \
    is_item_at_desk_available_for_checkout, is_item_available_for_checkout
from invenio_circulation.errors import ItemDoNotMatchError, \
    LoanMaxExtensionError, NoValidTransitionAvailableError, \
    RecordCannotBeRequestedError, TransitionConstraintsViolationError
from invenio_circulation.proxies import current_circulation
from invenio_circulation.utils import str2datetime

from .helpers import SwappedConfig, SwappedNestedConfig


def test_override_transaction_date(
    mock_get_pending_loans_by_doc_pid,
    loan_created,
    params,
    mock_is_item_available_for_checkout,
):
    """Test override transaction date."""
    mock_get_pending_loans_by_doc_pid.return_value = []
    mock_is_item_available_for_checkout.return_value = True
    assert loan_created["state"] == "CREATED"

    expected_transaction_date = arrow.utcnow() + timedelta(days=10)
    params["transaction_date"] = expected_transaction_date

    loan = current_circulation.circulation.trigger(
        loan_created, **dict(params, trigger="checkout")
    )
    assert loan["state"] == "ITEM_ON_LOAN"
    assert loan["transaction_date"] == expected_transaction_date.isoformat()


def test_loan_checkout_checkin(
    mock_get_pending_loans_by_doc_pid,
    loan_created,
    db,
    params,
    mock_is_item_available_for_checkout,
):
    """Test loan checkout and checkin actions."""

    mock_get_pending_loans_by_doc_pid.return_value = []
    mock_is_item_available_for_checkout.return_value = True
    assert loan_created["state"] == "CREATED"

    loan = current_circulation.circulation.trigger(
        loan_created, **dict(params, trigger="checkout")
    )
    assert loan["state"] == "ITEM_ON_LOAN"

    # set same transaction location to avoid "in transit"
    same_location = params["transaction_location_pid"]
    with SwappedConfig(
        "CIRCULATION_ITEM_LOCATION_RETRIEVER", lambda x: same_location
    ):
        loan = current_circulation.circulation.trigger(loan, **dict(params))
        assert loan["state"] == "ITEM_RETURNED"
        # Keep changes in database to make item available for checkout later
        db.session.commit()


def test_can_change_item_and_loc_pid_before_checkout(
    mock_get_pending_loans_by_doc_pid,
    loan_created,
    db,
    params,
    mock_is_item_available_for_checkout,
):
    """Test that item pid can be changed before the item is on loan."""

    mock_get_pending_loans_by_doc_pid.return_value = []
    mock_is_item_available_for_checkout.return_value = True
    item_pid = params["item_pid"]
    del params["item_pid"]

    # auto assign both available item pid and the location corresponding to it
    with SwappedConfig(
        "CIRCULATION_ITEMS_RETRIEVER_FROM_DOCUMENT", lambda x: [item_pid]
    ):
        with SwappedConfig(
            "CIRCULATION_ITEM_LOCATION_RETRIEVER",
            lambda x: "pickup_location_pid",
        ):
            loan = current_circulation.circulation.trigger(
                loan_created, **dict(params, trigger="request")
            )
    assert loan["state"] == "PENDING"
    assert loan["pickup_location_pid"] == "pickup_location_pid"
    assert loan["item_pid"] == dict(type="itemid", value="item_pid")

    with SwappedConfig(
        "CIRCULATION_ITEM_LOCATION_RETRIEVER", lambda x: "pickup_location_pid"
    ):
        changed_loan = copy.deepcopy(loan)
        changed_loan = current_circulation.circulation.trigger(
            changed_loan,
            **dict(
                params,
                trigger="next",
                item_pid=dict(type="itemid", value="other_item_pid_1"),
                pickup_location_pid="other_location_pid_1",
            )
        )
        db.session.commit()
        assert changed_loan["state"] == "ITEM_IN_TRANSIT_FOR_PICKUP"
        assert changed_loan["item_pid"] == dict(
            type="itemid", value="other_item_pid_1"
        )
        assert changed_loan["pickup_location_pid"] == "other_location_pid_1"

        changed_loan = copy.deepcopy(loan)
        changed_loan = current_circulation.circulation.trigger(
            changed_loan,
            **dict(
                params,
                trigger="next",
                item_pid=dict(type="itemid", value="other_item_pid_2"),
            )
        )
        db.session.commit()
        assert changed_loan["state"] == "ITEM_AT_DESK"
        assert changed_loan["item_pid"] == dict(
            type="itemid", value="other_item_pid_2"
        )
        assert changed_loan["pickup_location_pid"] == "pickup_location_pid"

        changed_loan = copy.deepcopy(loan)
        changed_loan = current_circulation.circulation.trigger(
            changed_loan,
            **dict(
                params,
                trigger="checkout",
                item_pid=dict(type="itemid", value="other_item_pid_3"),
                pickup_location_pid="other_location_pid_3",
            )
        )
        db.session.commit()
        assert changed_loan["state"] == "ITEM_ON_LOAN"
        assert changed_loan["item_pid"] == dict(
            type="itemid", value="other_item_pid_3"
        )
        assert changed_loan["pickup_location_pid"] == "other_location_pid_3"


def test_cannot_change_item_pid_after_checkout(
    mock_get_pending_loans_by_doc_pid,
    loan_created,
    params,
    mock_is_item_available_for_checkout,
):
    """Test that item pid cannot be changed after the item is on loan."""
    mock_get_pending_loans_by_doc_pid.return_value = []
    mock_is_item_available_for_checkout.return_value = True
    del params["item_pid"]

    # auto assign both available item pid and the location corresponding to it

    with SwappedConfig(
        "CIRCULATION_ITEM_LOCATION_RETRIEVER", lambda x: "pickup_location_pid"
    ):
        loan = current_circulation.circulation.trigger(
            loan_created,
            **dict(
                params,
                trigger="checkout",
                item_pid=dict(type="itemid", value="item_pid"),
            )
        )

    assert loan["state"] == "ITEM_ON_LOAN"
    assert loan["item_pid"] == dict(type="itemid", value="item_pid")
    assert loan["pickup_location_pid"] == "pickup_location_pid"

    with SwappedConfig(
        "CIRCULATION_ITEM_LOCATION_RETRIEVER", lambda x: "pickup_location_pid"
    ):
        changed_loan = copy.deepcopy(loan)
        with pytest.raises(ItemDoNotMatchError):
            current_circulation.circulation.trigger(
                changed_loan,
                **dict(
                    params,
                    trigger="next",
                    item_pid=dict(type="itemid", value="other_item_pid_1"),
                )
            )

        changed_loan = copy.deepcopy(loan)
        with pytest.raises(ItemDoNotMatchError):
            current_circulation.circulation.trigger(
                changed_loan,
                **dict(
                    params,
                    trigger="extend",
                    item_pid=dict(type="itemid", value="other_item_pid_2"),
                )
            )

        changed_loan = copy.deepcopy(loan)
        with pytest.raises(ItemDoNotMatchError):
            current_circulation.circulation.trigger(
                changed_loan,
                **dict(
                    params,
                    trigger="cancel",
                    item_pid=dict(type="itemid", value="other_item_pid_3"),
                )
            )


def test_loan_extend(
    loan_created, params, mock_ensure_item_is_available_for_checkout
):
    """Test loan extend action."""

    mock_ensure_item_is_available_for_checkout.side_effect = None

    loan = current_circulation.circulation.trigger(
        loan_created, **dict(params, trigger="checkout")
    )

    end_date = str2datetime(loan["end_date"])
    default_extension_duration = timedelta(days=30)
    end_date_with_ext = end_date + default_extension_duration

    with SwappedNestedConfig(
        ["CIRCULATION_POLICIES", "extension", "max_count"], lambda x: 0
    ):
        with pytest.raises(LoanMaxExtensionError):
            loan = current_circulation.circulation.trigger(
                loan, **dict(params, trigger="extend")
            )

    with SwappedNestedConfig(
        ["CIRCULATION_POLICIES", "extension", "max_count"], lambda x: 2
    ):
        loan = current_circulation.circulation.trigger(
            loan, **dict(params, trigger="extend")
        )

        new_end_date = loan["end_date"]
        assert str2datetime(new_end_date) == end_date_with_ext
        assert loan["extension_count"] == 1

        loan = current_circulation.circulation.trigger(
            loan, **dict(params, trigger="extend")
        )

        # test too many extensions
        with pytest.raises(LoanMaxExtensionError):
            loan = current_circulation.circulation.trigger(
                loan, **dict(params, trigger="extend")
            )


def test_loan_extend_from_enddate(
    loan_created, params, mock_ensure_item_is_available_for_checkout
):
    """Test loan extend action from transaction date."""

    mock_ensure_item_is_available_for_checkout.side_effect = None

    loan = current_circulation.circulation.trigger(
        loan_created, **dict(params, trigger="checkout")
    )
    extension_date = str2datetime(loan["transaction_date"])
    with SwappedNestedConfig(
        ["CIRCULATION_POLICIES", "extension", "from_end_date"], False
    ):
        loan = current_circulation.circulation.trigger(
            loan, **dict(params, trigger="extend")
        )

    default_extension_duration = timedelta(days=30)
    end_date_with_ext = extension_date + default_extension_duration
    assert loan["end_date"] == end_date_with_ext.date().isoformat()
    assert loan["extension_count"] == 1


def test_cancel_action(
    loan_created, params, mock_ensure_item_is_available_for_checkout
):
    """Test should pass when calling `cancel` from `ITEM_ON_LOAN`."""

    mock_ensure_item_is_available_for_checkout.side_effect = None

    loan = current_circulation.circulation.trigger(
        loan_created, **dict(params, trigger="checkout")
    )

    loan = current_circulation.circulation.trigger(
        loan, **dict(params, trigger="cancel")
    )
    assert loan["state"] == "CANCELLED"


def test_cancel_fail(loan_created, params):
    """Test should fail when calling `cancel` from `CREATED`."""
    with pytest.raises(NoValidTransitionAvailableError):
        current_circulation.circulation.trigger(
            loan_created, **dict(params, trigger="cancel")
        )


def test_validate_item_in_transit_for_pickup(loan_created, params):
    """Test transit item in different location."""
    loan = current_circulation.circulation.trigger(
        loan_created,
        **dict(
            params,
            trigger="request",
            pickup_location_pid="pickup_location_pid",
        )
    )
    assert loan["state"] == "PENDING"

    with SwappedConfig(
        "CIRCULATION_ITEM_LOCATION_RETRIEVER",
        lambda x: "external_location_pid",
    ):
        loan = current_circulation.circulation.trigger(loan, **dict(params))
        assert loan["state"] == "ITEM_IN_TRANSIT_FOR_PICKUP"


def test_checkout_extend_with_timedelta(
    loan_created, params, mock_ensure_item_is_available_for_checkout
):
    """Test checkout with a timedelta duration."""
    mock_ensure_item_is_available_for_checkout.side_effect = None

    duration = timedelta(hours=4)
    with SwappedNestedConfig(
        ["CIRCULATION_POLICIES", "checkout", "duration_default"],
        lambda x: duration,
    ):
        loan = current_circulation.circulation.trigger(
            loan_created, **dict(params, trigger="checkout")
        )

        expected_start_date = str2datetime(loan["transaction_date"])
        expected_end_date = str2datetime(loan["start_date"]) + duration
        assert loan["state"] == "ITEM_ON_LOAN"
        assert loan["start_date"] == expected_start_date.date().isoformat()
        assert loan["end_date"] == expected_end_date.date().isoformat()
        end_date = loan["end_date"]

    duration = timedelta(days=1)
    with SwappedNestedConfig(
        ["CIRCULATION_POLICIES", "extension", "duration_default"],
        lambda x: duration,
    ):
        # perform an extension
        loan = current_circulation.circulation.trigger(
            loan, **dict(params, trigger="extend")
        )
        expected_end_date = str2datetime(end_date) + duration
        assert loan["end_date"] == expected_end_date.date().isoformat()
        end_date = loan["end_date"]

    duration = timedelta(days=3, minutes=33)
    with SwappedNestedConfig(
        ["CIRCULATION_POLICIES", "extension", "duration_default"],
        lambda x: duration,
    ):
        # extend again
        loan = current_circulation.circulation.trigger(
            loan, **dict(params, trigger="extend")
        )
        expected_end_date = str2datetime(end_date) + duration
        assert loan["end_date"] == expected_end_date.date().isoformat()


def test_checkout_start_is_transaction_date(
    loan_created, params, mock_ensure_item_is_available_for_checkout
):
    """Test checkout start date to transaction date when not set."""
    mock_ensure_item_is_available_for_checkout.side_effect = None

    duration = timedelta(days=10)
    with SwappedNestedConfig(
        ["CIRCULATION_POLICIES", "checkout", "duration_default"],
        lambda x: duration,
    ):
        loan = current_circulation.circulation.trigger(
            loan_created, **dict(params, trigger="checkout")
        )

        expected_start_date = str2datetime(loan["transaction_date"])
        expected_end_date = str2datetime(loan["start_date"]) + duration
        assert loan["state"] == "ITEM_ON_LOAN"
        assert loan["start_date"] == expected_start_date.date().isoformat()
        assert loan["end_date"] == expected_end_date.date().isoformat()


def test_checkout_with_input_start_end_dates(
    loan_created, params, mock_ensure_item_is_available_for_checkout
):
    """Test checkout start and end dates are set as input."""

    mock_ensure_item_is_available_for_checkout.side_effect = None

    start_date = arrow.utcnow()
    end_date = start_date + timedelta(days=10)
    loan = current_circulation.circulation.trigger(
        loan_created,
        **dict(
            params,
            start_date=start_date,
            end_date=end_date,
            trigger="checkout",
        )
    )
    assert loan["state"] == "ITEM_ON_LOAN"
    assert loan["start_date"] == start_date.date().isoformat()
    assert loan["end_date"] == end_date.date().isoformat()


def test_checkout_fails_when_duration_invalid(
    loan_created, params, mock_ensure_item_is_available_for_checkout
):
    """Test checkout fails when wrong max duration."""

    mock_ensure_item_is_available_for_checkout.side_effect = None

    with pytest.raises(TransitionConstraintsViolationError):
        with SwappedNestedConfig(
            ["CIRCULATION_POLICIES", "checkout", "duration_validate"],
            lambda x: False,
        ):
            start_date = arrow.utcnow()
            end_date = start_date + timedelta(days=60)
            current_circulation.circulation.trigger(
                loan_created,
                **dict(
                    params,
                    start_date=start_date,
                    end_date=end_date,
                    trigger="checkout",
                )
            )


def test_checkin_end_date_is_transaction_date(
    mock_get_pending_loans_by_doc_pid,
    mock_ensure_item_is_available_for_checkout,
    loan_created,
    params,
):
    """Test date the checkin date is the transaction date."""
    mock_get_pending_loans_by_doc_pid.return_value = []
    mock_ensure_item_is_available_for_checkout.side_effect = None

    start_date = arrow.utcnow()
    end_date = start_date + timedelta(days=10)

    loan = current_circulation.circulation.trigger(
        loan_created,
        **dict(
            params,
            start_date=start_date,
            end_date=end_date,
            trigger="checkout",
        )
    )
    assert loan["state"] == "ITEM_ON_LOAN"
    assert loan["transaction_date"]
    transaction_date = loan["transaction_date"]

    same_location = params["transaction_location_pid"]
    params["transaction_date"] = arrow.utcnow()
    with SwappedConfig(
        "CIRCULATION_ITEM_LOCATION_RETRIEVER", lambda x: same_location
    ):
        loan = current_circulation.circulation.trigger(loan, **dict(params))

    assert loan["state"] == "ITEM_RETURNED"
    expected_end_date = str2datetime(transaction_date).date().isoformat()
    assert loan["end_date"] == expected_end_date


def test_item_availability(indexed_loans):
    """Test item_availability with various conditions."""
    assert is_item_available_for_checkout(
        item_pid=dict(type="itemid", value="item_pending_1")
    )
    assert not is_item_available_for_checkout(
        item_pid=dict(type="itemid", value="item_on_loan_2")
    )
    assert is_item_available_for_checkout(
        item_pid=dict(type="itemid", value="item_returned_3")
    )
    assert not is_item_available_for_checkout(
        item_pid=dict(type="itemid", value="item_in_transit_4")
    )
    assert not is_item_available_for_checkout(
        item_pid=dict(type="itemid", value="item_pending_on_loan_6")
    )
    assert is_item_available_for_checkout(
        item_pid=dict(type="itemid", value="item_returned_6")
    )
    assert is_item_available_for_checkout(
        item_pid=dict(type="itemid", value="no_loan")
    )
    # item is not available because it has a loan with state ITEM_AT_DESK
    assert not is_item_available_for_checkout(
        item_pid=dict(type="itemid", value="item_at_desk_5")
    )
    # item is available because the checked-out patron owns the active loan
    assert is_item_at_desk_available_for_checkout(
            item_pid=dict(type="itemid", value="item_at_desk_5"),
            patron_pid="1"
    )


def test_checkout_item_unavailable_steps(loan_created, params, users):
    """Test checkout attempt on unavailable item."""
    user = users["manager"]
    login_user(user)
    with pytest.raises(NoValidTransitionAvailableError):
        # loan created
        current_circulation.circulation.trigger(
            loan_created, **dict(params, trigger="request")
        )
        # loan pending
        current_circulation.circulation.trigger(
            loan_created, **dict(params, trigger="next")
        )
        loan_created["state"] = "ITEM_ON_LOAN"
        current_circulation.circulation.trigger(loan_created, **dict(params))

        # trying to checkout item already on loan
        current_circulation.circulation.trigger(
            loan_created, **dict(params, trigger="checkout")
        )


def test_deny_request(loan_created, params):
    """Test deny request action."""
    with SwappedNestedConfig(
        ["CIRCULATION_POLICIES", "request", "can_be_requested"],
        lambda x: False,
    ):
        with pytest.raises(RecordCannotBeRequestedError):
            current_circulation.circulation.trigger(
                loan_created,
                **dict(
                    params,
                    trigger="request",
                    pickup_location_pid="pickup_location_pid",
                )
            )
