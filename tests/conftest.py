# -*- coding: utf-8 -*-
#
# Copyright (C) 2018-2020 CERN.
# Copyright (C) 2018-2020 RERO.
#
# Invenio-Circulation is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.

"""Pytest configuration."""

from __future__ import absolute_import, print_function

import json
import uuid
from os.path import dirname, join

import mock
import pytest
from invenio_access import ActionRoles, superuser_access
from invenio_accounts.models import Role
from invenio_app.factory import create_api
from invenio_db import db
from invenio_indexer.api import RecordIndexer
from invenio_records_rest.utils import allow_all
from invenio_search import current_search

from invenio_circulation.api import Loan
from invenio_circulation.permissions import loan_read_access
from invenio_circulation.pidstore.minters import loan_pid_minter

from .helpers import create_loan, test_views_permissions_factory
from .utils import can_be_requested, document_exists, document_ref_builder, \
    get_default_extension_duration, get_default_extension_max_count, \
    get_default_loan_duration, is_loan_duration_valid, item_can_circulate, \
    item_exists, item_location_retriever, item_ref_builder, patron_exists, \
    patron_ref_builder, transaction_location_validator, \
    transaction_user_validator


@pytest.fixture(scope="module")
def create_app():
    """Return API app."""
    return create_api


@pytest.fixture(scope="module")
def app_config(app_config):
    """Flask application fixture."""
    app_config["JSONSCHEMAS_ENDPOINT"] = "/schema"
    app_config["JSONSCHEMAS_HOST"] = "localhost:5000"
    app_config["RECORDS_REST_DEFAULT_READ_PERMISSION_FACTORY"] = allow_all
    app_config["CIRCULATION_ITEM_EXISTS"] = item_exists
    app_config["CIRCULATION_DOCUMENT_EXISTS"] = document_exists
    app_config["CIRCULATION_PATRON_EXISTS"] = patron_exists
    app_config["CIRCULATION_ITEM_REF_BUILDER"] = item_ref_builder
    app_config["CIRCULATION_PATRON_REF_BUILDER"] = patron_ref_builder
    app_config["CIRCULATION_DOCUMENT_REF_BUILDER"] = document_ref_builder
    app_config["CIRCULATION_ITEM_LOCATION_RETRIEVER"] = item_location_retriever
    app_config["CIRCULATION_TRANSACTION_LOCATION_VALIDATOR"] = \
        transaction_location_validator
    app_config["CIRCULATION_TRANSACTION_USER_VALIDATOR"] = \
        transaction_user_validator
    app_config["CIRCULATION_DOCUMENT_RETRIEVER_FROM_ITEM"] = \
        lambda x: "document_pid"
    app_config["CIRCULATION_POLICIES"] = dict(
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
        request=dict(
            can_be_requested=can_be_requested
        )
    )
    return app_config


@pytest.fixture()
def loan_created(app):
    """Minimal Loan object."""
    record_uuid = uuid.uuid4()
    new_loan = {}
    loan_pid_minter(record_uuid, data=new_loan)
    loan = Loan.create(data=new_loan, id_=record_uuid)
    db.session.commit()
    yield loan


@pytest.fixture()
def params():
    """Params for API REST payload."""
    return dict(
        transaction_user_pid="user_pid",
        patron_pid="patron_pid",
        document_pid="document_pid",
        item_pid=dict(type="itemid", value="item_pid"),
        transaction_location_pid="loc_pid",
    )


@pytest.fixture()
def json_headers(app):
    """JSON headers."""
    return [
        ("Content-Type", "application/json"),
        ("Accept", "application/json"),
    ]


@pytest.fixture(scope="session")
def test_data():
    """Load test records."""
    path = "data/loans.json"
    with open(join(dirname(__file__), path)) as fp:
        loans = json.load(fp)
    yield loans


@pytest.fixture()
def test_loans(db, test_data):
    """Load test records."""
    loans = []
    for data in test_data:
        loans.append(create_loan(data))
    db.session.commit()
    yield loans


@pytest.fixture()
def indexed_loans(es, test_loans):
    """Get a function to wait for records to be flushed to index."""
    indexer = RecordIndexer()
    for pid, loan in test_loans:
        indexer.index(loan)
    current_search.flush_and_refresh(index="loans")

    yield test_loans

    for pid, loan in test_loans:
        indexer.delete_by_id(loan.id)
    current_search.flush_and_refresh(index="loans")


@pytest.fixture()
def mock_is_item_available_for_checkout():
    """Mock item_available check."""
    path = \
        "invenio_circulation.api.is_item_available_for_checkout"
    with mock.patch(path) as mock_is_item_available_for_checkout:
        mock_is_item_available_for_checkout.return_value = False
        yield mock_is_item_available_for_checkout


@pytest.fixture()
def mock_is_item_at_desk_available_for_checkout():
    """Mock item_at_desk_available check."""
    path = \
        "invenio_circulation.api.is_item_at_desk_available_for_checkout"
    with mock.patch(path) as mock_is_item_at_desk_available_for_checkout:
        mock_is_item_at_desk_available_for_checkout.return_value = False
        yield mock_is_item_at_desk_available_for_checkout


@pytest.fixture()
def mock_get_pending_loans_by_doc_pid():
    """Mock item_available check."""
    path = \
        "invenio_circulation.transitions.transitions" \
        ".get_pending_loans_by_doc_pid"
    # assert path exists
    with mock.patch(path) as mock_get_pending_loans_by_doc_pid:
        mock_get_pending_loans_by_doc_pid.return_value = False
        yield mock_get_pending_loans_by_doc_pid


@pytest.fixture()
def mock_ensure_item_is_available_for_checkout():
    """Mock ensure_item_is_available_for_checkout."""
    path = \
        "invenio_circulation.transitions.base.Transition" \
        ".ensure_item_is_available_for_checkout"
    with mock.patch(path) as mock_ensure_item_is_available_for_checkout:
        yield mock_ensure_item_is_available_for_checkout


@pytest.fixture()
def users(db, base_app):
    """Create admin, manager and user."""
    base_app.config[
        "CIRCULATION_VIEWS_PERMISSIONS_FACTORY"
    ] = test_views_permissions_factory

    with db.session.begin_nested():
        datastore = base_app.extensions["security"].datastore

        # create users
        manager = datastore.create_user(
            email="manager@test.com", password="123456", active=True
        )
        admin = datastore.create_user(
            email="admin@test.com", password="123456", active=True
        )
        user = datastore.create_user(
            email="user@test.com", password="123456", active=True
        )

        # Give role to admin
        admin_role = Role(name="admin")
        db.session.add(
            ActionRoles(action=superuser_access.value, role=admin_role)
        )
        datastore.add_role_to_user(admin, admin_role)
        # Give role to user
        manager_role = Role(name="manager")
        db.session.add(
            ActionRoles(action=loan_read_access.value, role=manager_role)
        )
        datastore.add_role_to_user(manager, manager_role)
    db.session.commit()

    return {"admin": admin, "manager": manager, "user": user}
