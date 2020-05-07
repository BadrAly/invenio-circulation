# -*- coding: utf-8 -*-
#
# Copyright (C) 2018-2020 CERN.
# Copyright (C) 2018-2020 RERO.
#
# Invenio-Circulation is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.

"""Invenio module for the circulation of bibliographic items."""

import os

from setuptools import find_packages, setup

readme = open('README.rst').read()
history = open('CHANGES.rst').read()

tests_require = [
    'check-manifest>=0.25',
    'coverage>=4.4',
    'isort>=4.3.11',
    'invenio-app>=1.0.4',
    'invenio-jsonschemas>=1.0.0',
    'mock>=1.3.0',
    'pydocstyle>=1.0.0',
    'pytest-cache>=1.0',
    'pytest-cov>=2.7.1',
    'pytest-pep8>=1.0.6',
    'pytest>=3.8.1',
    'pytest-invenio>=1.2.0',
]

invenio_search_version = '1.2.1'
invenio_db_version = '1.0.4'

extras_require = {
    'elasticsearch5': [
        'invenio-search[elasticsearch5]>={}'.format(invenio_search_version)
    ],
    'elasticsearch6': [
        'invenio-search[elasticsearch6]>={}'.format(invenio_search_version)
    ],
    'elasticsearch7': [
        'invenio-search[elasticsearch7]>={}'.format(invenio_search_version),
    ],
    'docs': [
        'Sphinx>=1.5.1'
    ],
    'mysql': [
        'invenio-db[mysql,versioning]>={}'.format(invenio_db_version)
    ],
    'postgresql': [
        'invenio-db[postgresql,versioning]>={}'.format(invenio_db_version)
    ],
    'sqlite': [
        'invenio-db[versioning]>={}'.format(invenio_db_version)
    ],
    'tests': tests_require
}

extras_require['all'] = []
for name, reqs in extras_require.items():
    if name in (
        'mysql',
        'postgresql',
        'sqlite',
        'elasticsearch5',
        'elasticsearch6',
        'elasticsearch7',
    ):
        continue
    extras_require['all'].extend(reqs)

setup_requires = ['Babel>=1.3', 'pytest-runner>=2.6.2']

install_requires = [
    'arrow>=0.15.0',
    'invenio-i18n>=1.0.0',
    'invenio-base>=1.0.1',
    'invenio-access>=1.3.1',
    'invenio-logging>=1.2.1',
    'invenio-pidstore>=1.0.0',
    'invenio-records-rest>=1.6.1',
    'invenio-jsonschemas>=1.0.0',
]

packages = find_packages()


# Get the version string. Cannot be done with import!
g = {}
with open(os.path.join('invenio_circulation', 'version.py'), 'rt') as fp:
    exec(fp.read(), g)
    version = g['__version__']

setup(
    name='invenio-circulation',
    version=version,
    description=__doc__,
    long_description=readme + '\n\n' + history,
    keywords='invenio TODO',
    license='MIT',
    author='CERN',
    author_email='info@inveniosoftware.org',
    url='https://github.com/inveniosoftware/invenio-circulation',
    packages=packages,
    zip_safe=False,
    include_package_data=True,
    platforms='any',
    python_requires='>=3',
    entry_points={
        'invenio_base.apps': [
            'invenio_circulation = invenio_circulation:InvenioCirculation'
        ],
        'invenio_base.api_apps': [
            'invenio_circulation = invenio_circulation:InvenioCirculation'
        ],
        'invenio_base.api_blueprints': [
            'invenio_circulation_loan_actions = '
            'invenio_circulation.views:create_loan_actions_blueprint',
            'invenio_circulation_loan_for_item = '
            'invenio_circulation_loan_replace_item = '
            'invenio_circulation.views:create_loan_replace_item_blueprint',

        ],
        'invenio_i18n.translations': ['messages = invenio_circulation'],
        'invenio_pidstore.fetchers': [
            'loanid = invenio_circulation.pidstore.fetchers:loan_pid_fetcher'
        ],
        'invenio_pidstore.minters': [
            'loanid = invenio_circulation.pidstore.minters:loan_pid_minter'
        ],
        'invenio_jsonschemas.schemas': [
            'loans = invenio_circulation.schemas'
        ],
        'invenio_search.mappings': ['loans = invenio_circulation.mappings'],
        "invenio_records.jsonresolver": [
            "item_resolver = invenio_circulation.records.jsonresolver.item",
            "patron_resolver = invenio_circulation.records.jsonresolver.patron",
            "document_resolver = invenio_circulation.records.jsonresolver.document",

        ],
    },
    extras_require=extras_require,
    install_requires=install_requires,
    setup_requires=setup_requires,
    tests_require=tests_require,
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Development Status :: 1 - Planning',
    ],
)
