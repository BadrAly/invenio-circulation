# -*- coding: utf-8 -*-
#
# Copyright (C) 2018-2019 CERN.
# Copyright (C) 2018-2019 RERO.
#
# Invenio-Circulation is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.

"""Invenio module for the circulation of bibliographic items."""

from invenio_records_rest.utils import allow_all

from .api import Loan
from .links import loan_links_factory
from .permissions import views_permissions_factory
from .pidstore.pids import _LOANID_CONVERTER, CIRCULATION_LOAN_FETCHER, \
    CIRCULATION_LOAN_MINTER, CIRCULATION_LOAN_PID_TYPE
from .search.api import LoansSearch
from .transitions.transitions import CreatedToPending, \
    ItemAtDeskToItemOnLoan, ItemInTransitHouseToItemReturned, \
    ItemOnLoanToItemInTransitHouse, ItemOnLoanToItemOnLoan, \
    ItemOnLoanToItemReturned, PendingToItemAtDesk, \
    PendingToItemInTransitPickup, ToCancelled, ToItemOnLoan
from .utils import can_be_requested, document_exists, document_ref_builder, \
    get_default_extension_duration, get_default_extension_max_count, \
    get_default_loan_duration, is_loan_duration_valid, item_can_circulate, \
    item_exists, item_location_retriever, item_ref_builder, patron_exists, \
    patron_ref_builder, transaction_location_validator, \
    transaction_user_validator

CIRCULATION_ITEMS_RETRIEVER_FROM_DOCUMENT = None
"""Function that returns a list of item PIDs given a Document PID."""

CIRCULATION_DOCUMENT_RETRIEVER_FROM_ITEM = None
"""Function that returns the Document PID of a given Item PID."""

CIRCULATION_STATES_LOAN_REQUEST = ['PENDING']
"""Defines the list of states for which the loan is considered requested."""

CIRCULATION_STATES_LOAN_ACTIVE = ['ITEM_AT_DESK',
                                  'ITEM_ON_LOAN',
                                  'ITEM_IN_TRANSIT_FOR_PICKUP',
                                  'ITEM_IN_TRANSIT_TO_HOUSE',
                                  ]
"""Defines the list of Loan states for which a Loan is considered as active.

Items that have attached loans with these circulation statuses are
not available to be loaned by patrons."""

CIRCULATION_STATES_LOAN_COMPLETED = ['ITEM_RETURNED']
"""Defines the list of states that a loan is considered completed.

Loans with these states are considered as valid past loans for the item they
refer to."""

CIRCULATION_STATES_LOAN_ACTIVE_EXCEPT = ['ITEM_AT_DESK']
"""Defines the list of Loan states among the CIRCULATION_STATES_LOAN_ACTIVE
for which a checkout, for the concerned patron, is allowed."""

CIRCULATION_STATES_LOAN_CANCELLED = ["CANCELLED"]
"""Defines the list of states for which the loan is considered cancelled."""

CIRCULATION_LOAN_TRANSITIONS_DEFAULT_PERMISSION_FACTORY = allow_all
"""Default permission factory for all Loans transitions."""

CIRCULATION_LOAN_TRANSITIONS = {
    "CREATED": [
        dict(dest="PENDING", trigger="request", transition=CreatedToPending),
        dict(dest="ITEM_ON_LOAN", trigger="checkout", transition=ToItemOnLoan),
    ],
    "PENDING": [
        dict(dest="ITEM_AT_DESK", transition=PendingToItemAtDesk),
        dict(
            dest="ITEM_IN_TRANSIT_FOR_PICKUP",
            transition=PendingToItemInTransitPickup,
        ),
        dict(dest="ITEM_ON_LOAN", trigger="checkout", transition=ToItemOnLoan),
        dict(dest="CANCELLED", trigger="cancel", transition=ToCancelled),
    ],
    "ITEM_AT_DESK": [
        dict(dest="ITEM_ON_LOAN", transition=ItemAtDeskToItemOnLoan),
        dict(dest="CANCELLED", trigger="cancel", transition=ToCancelled),
    ],
    "ITEM_IN_TRANSIT_FOR_PICKUP": [
        dict(dest="ITEM_AT_DESK"),
        dict(dest="CANCELLED", trigger="cancel", transition=ToCancelled),
    ],
    "ITEM_ON_LOAN": [
        dict(dest="ITEM_RETURNED", transition=ItemOnLoanToItemReturned),
        dict(
            dest="ITEM_IN_TRANSIT_TO_HOUSE",
            transition=ItemOnLoanToItemInTransitHouse,
        ),
        dict(
            dest="ITEM_ON_LOAN",
            transition=ItemOnLoanToItemOnLoan,
            trigger="extend",
        ),
        dict(dest="CANCELLED", trigger="cancel", transition=ToCancelled),
    ],
    "ITEM_IN_TRANSIT_TO_HOUSE": [
        dict(
            dest="ITEM_RETURNED", transition=ItemInTransitHouseToItemReturned
        ),
        dict(dest="CANCELLED", trigger="cancel", transition=ToCancelled),
    ],
    "ITEM_RETURNED": [],
    "CANCELLED": [],
}
"""Default circulation Loans transitions."""

CIRCULATION_LOAN_INITIAL_STATE = "CREATED"
"""Define the initial state name of a Loan."""

CIRCULATION_PATRON_EXISTS = patron_exists
"""Function that returns True if the given Patron exists."""

CIRCULATION_ITEM_EXISTS = item_exists
"""Function that returns True if the given Item exists."""

CIRCULATION_DOCUMENT_EXISTS = document_exists
"""Function that returns True if the given Document exists."""

CIRCULATION_ITEM_LOCATION_RETRIEVER = item_location_retriever
"""Function that returns the Location PID of the given Item."""

CIRCULATION_TRANSACTION_LOCATION_VALIDATOR = transaction_location_validator
"""Function that validates the Location PID of the given transaction."""

CIRCULATION_TRANSACTION_USER_VALIDATOR = transaction_user_validator
"""Function that validates the User PID of the given transaction."""

# JSON Schema resolvers
CIRCULATION_ITEM_REF_BUILDER = item_ref_builder
"""Function that builds $ref to an `Item` record."""

CIRCULATION_ITEM_RESOLVING_PATH = ""
"""Path to use for the resolving of the item ref."""

CIRCULATION_ITEM_RESOLVER_ENDPOINT = None
"""Flask endpoint function to handle the item resolving."""

CIRCULATION_PATRON_REF_BUILDER = patron_ref_builder
"""Function that builds $ref to a `Patron` record."""

CIRCULATION_PATRON_RESOLVING_PATH = ""
"""Path to use for the resolving of the patron ref."""

CIRCULATION_PATRON_RESOLVER_ENDPOINT = None
"""Flask endpoint function to handle the patron resolving."""

CIRCULATION_DOCUMENT_REF_BUILDER = document_ref_builder
"""Function that builds $ref to a `Document` record."""

CIRCULATION_DOCUMENT_RESOLVING_PATH = ""
"""Path to use for the resolving of the document ref."""

CIRCULATION_DOCUMENT_RESOLVER_ENDPOINT = None
"""Flask endpoint function to handle the document resolving."""

CIRCULATION_POLICIES = dict(
    checkout=dict(
        duration_default=get_default_loan_duration,
        duration_validate=is_loan_duration_valid,
        item_can_circulate=item_can_circulate,
    ),
    extension=dict(
        from_end_date=True,
        duration_default=get_default_extension_duration,
        max_count=get_default_extension_max_count,
    ),
    request=dict(can_be_requested=can_be_requested),
)
"""Default circulation policies when performing an action on a Loan."""

CIRCULATION_REST_ENDPOINTS = dict(
    loanid=dict(
        pid_type=CIRCULATION_LOAN_PID_TYPE,
        pid_minter=CIRCULATION_LOAN_MINTER,
        pid_fetcher=CIRCULATION_LOAN_FETCHER,
        search_class=LoansSearch,
        search_type=None,
        record_class=Loan,
        record_loaders={
            "application/json": (
                "invenio_circulation.records.loaders:loan_loader"
            )
        },
        record_serializers={
            "application/json": (
                "invenio_records_rest.serializers:json_v1_response"
            )
        },
        search_serializers={
            "application/json": (
                "invenio_records_rest.serializers:json_v1_search"
            )
        },
        list_route="/circulation/loans/",
        item_route="/circulation/loans/<{0}:pid_value>".format(
            _LOANID_CONVERTER
        ),
        default_media_type="application/json",
        max_result_window=10000,
        error_handlers=dict(),
        create_permission_factory_imp=allow_all,
    )
)
"""REST endpoint configuration for circulation APIs."""

CIRCULATION_LOAN_LINKS_FACTORY = loan_links_factory
"""Links factory for Loan record."""

CIRCULATION_VIEWS_PERMISSIONS_FACTORY = views_permissions_factory
"""Permissions factory for circulation views to handle actions."""
