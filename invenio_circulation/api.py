# -*- coding: utf-8 -*-
#
# Copyright (C) 2018-2020 CERN.
# Copyright (C) 2018-2020 RERO.
#
# Invenio-Circulation is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.

"""Circulation API."""

from elasticsearch import VERSION as ES_VERSION
from flask import current_app
from invenio_jsonschemas import current_jsonschemas
from invenio_pidstore.resolver import Resolver
from invenio_records.api import Record

from .errors import MissingRequiredParameterError, MultipleLoansOnItemError
from .pidstore.pids import CIRCULATION_LOAN_PID_TYPE
from .search.api import search_by_patron_item_or_document, search_by_pid
from .utils import str2datetime


class Loan(Record):
    """Loan record class."""

    DATE_FIELDS = [
        "start_date",
        "end_date",
        "request_expire_date",
        "request_start_date",
    ]
    DATETIME_FIELDS = ["transaction_date"]

    _schema = "loans/loan-v1.0.0.json"

    def __init__(self, data, model=None):
        """Constructor."""
        self.item_ref_builder = current_app.config[
            "CIRCULATION_ITEM_REF_BUILDER"]
        self["state"] = current_app.config["CIRCULATION_LOAN_INITIAL_STATE"]
        super().__init__(data, model)

    @classmethod
    def build_resolver_fields(cls, data):
        """Build all resolver fields."""
        item_ref = current_app.config["CIRCULATION_ITEM_REF_BUILDER"]
        data["item"] = item_ref(data["pid"], data)
        patron_ref = current_app.config["CIRCULATION_PATRON_REF_BUILDER"]
        data["patron"] = patron_ref(data["pid"], data)
        document_ref = current_app.config["CIRCULATION_DOCUMENT_REF_BUILDER"]
        data["document"] = document_ref(data["pid"], data)

    @classmethod
    def create(cls, data, id_=None, **kwargs):
        """Create Loan record."""
        data["$schema"] = current_jsonschemas.path_to_url(cls._schema)
        cls.build_resolver_fields(data)

        # resolve document if `item_pid` provided
        if data.get("item_pid"):
            data["document_pid"] = get_document_pid_by_item_pid(
                data["item_pid"])

        return super().create(data, id_=id_, **kwargs)

    def update(self, *args, **kwargs):
        """Update Loan record."""
        super().update(*args, **kwargs)
        self.build_resolver_fields(self)

    def date_fields2datetime(self):
        """Convert string datetime fields to Python datetime."""
        for field in self.DATE_FIELDS + self.DATETIME_FIELDS:
            if field in self:
                self[field] = str2datetime(self[field])

    def date_fields2str(self):
        """Convert Python datetime fields to string."""
        for field in self.DATE_FIELDS:
            if field in self:
                self[field] = self[field].date().isoformat()
        for field in self.DATETIME_FIELDS:
            if field in self:
                self[field] = self[field].isoformat()

    @classmethod
    def get_record_by_pid(cls, pid, with_deleted=False):
        """Get ils record by pid value."""
        resolver = Resolver(
            pid_type=CIRCULATION_LOAN_PID_TYPE,
            object_type="rec",
            getter=cls.get_record,
        )
        _, record = resolver.resolve(str(pid))
        return record

    def update_item_ref(self, item_pid):
        """Replace item reference.

        :param item_pid: a dict containing `value` and `type` fields to
            uniquely identify the item.
        """
        if not item_pid:
            msg = "Missing required arg 'item_pid' when updating loan '{}'"
            raise MissingRequiredParameterError(
                description=msg.format(self["pid"])
            )
        self["item_pid"] = item_pid


def is_item_available_for_checkout(item_pid):
    """Return True if the given item is available for loan, False otherwise.

    :param item_pid: a dict containing `value` and `type` fields to
        uniquely identify the item.
    """
    config = current_app.config
    cfg_item_can_circulate = config["CIRCULATION_POLICIES"]["checkout"].get(
        "item_can_circulate"
    )
    if not cfg_item_can_circulate(item_pid):
        return False

    search = search_by_pid(
        item_pid=item_pid,
        filter_states=config.get("CIRCULATION_STATES_LOAN_ACTIVE"),
    )
    search_result = search.execute()
    if ES_VERSION[0] >= 7:
        return search_result.hits.total.value == 0
    else:
        return search_result.hits.total == 0


def is_item_at_desk_available_for_checkout(item_pid, patron_pid):
    """Return True if the ITEM_AT_DESK is available for loan, False instead."""
    # Try first to accept the availability for given patron
    item_exception_loans = 0
    search = search_by_patron_item_or_document(
        item_pid=item_pid,
        patron_pid=patron_pid,
        filter_states=["ITEM_AT_DESK"],
    )
    search_result = search.execute()
    if ES_VERSION[0] >= 7:
        item_exception_loans = search_result.hits.total.value
    else:
        item_exception_loans = search_result.hits.total

    if item_exception_loans == 1:
        return True

    # Then use normal behaviour if it failed with patron
    return is_item_available_for_checkout(item_pid)


def can_be_requested(loan):
    """Return True if the given record can be requested, False otherwise."""
    config = current_app.config
    cfg_can_be_requested = config["CIRCULATION_POLICIES"]["request"].get(
        "can_be_requested"
    )
    return cfg_can_be_requested(loan)


def get_pending_loans_by_item_pid(item_pid):
    """Return any pending loans for the given item.

    :param item_pid: a dict containing `value` and `type` fields to
        uniquely identify the item.
    """
    search = search_by_pid(
        item_pid=item_pid,
        filter_states=current_app.config["CIRCULATION_STATES_LOAN_REQUEST"]
    )
    for result in search.scan():
        yield Loan.get_record_by_pid(result["pid"])


def get_pending_loans_by_doc_pid(document_pid):
    """Return any pending loans for the given document."""
    search = search_by_pid(
        document_pid=document_pid,
        filter_states=current_app.config.get(
            "CIRCULATION_STATES_LOAN_REQUEST"
        ),
    )
    for result in search.scan():
        yield Loan.get_record_by_pid(result["pid"])


def get_available_item_by_doc_pid(document_pid):
    """Return an item pid available for this document."""
    for item_pid in get_items_by_doc_pid(document_pid):
        if is_item_available_for_checkout(item_pid):
            return item_pid
    return None


def get_items_by_doc_pid(document_pid):
    """Return a list of item PIDs for this document."""
    return current_app.config["CIRCULATION_ITEMS_RETRIEVER_FROM_DOCUMENT"](
        document_pid
    )


def get_document_pid_by_item_pid(item_pid):
    """Return the document pid of this item_pid."""
    return current_app.config["CIRCULATION_DOCUMENT_RETRIEVER_FROM_ITEM"](
        item_pid
    )


def get_loan_for_item(item_pid):
    """Return the Loan attached to the given item, if any.

    :param item_pid: a dict containing `value` and `type` fields to
        uniquely identify the item.
    """
    if not item_pid:
        return

    search = search_by_pid(
        item_pid=item_pid,
        filter_states=current_app.config["CIRCULATION_STATES_LOAN_ACTIVE"],
    )
    loan = None
    hits = list(search.scan())
    if hits:
        if len(hits) > 1:
            raise MultipleLoansOnItemError(item_pid=item_pid)
        loan = Loan.get_record_by_pid(hits[0]["pid"])
    return loan
