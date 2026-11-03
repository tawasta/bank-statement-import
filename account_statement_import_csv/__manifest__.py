##############################################################################
#
#    Author: Futural Oy
#    Copyright 2026 Futural Oy (https://futural.fi)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program. If not, see http://www.gnu.org/licenses/agpl.html
#
##############################################################################

{
    "name": "CSV Bank Statements Import",
    "summary": "Import CSV lines as a bank statement",
    "version": "19.0.1.0.0",
    "category": "Invoicing",
    "website": "https://github.com/tawasta/bank-statement-import",
    "author": "Futural",
    "license": "AGPL-3",
    "application": False,
    "development_status": "Alpha",
    "installable": True,
    "external_dependencies": {"python": [], "bin": []},
    "depends": ["account_statement_import_file"],
    "data": [
        "wizard/account_statement_import_view.xml",
    ],
    "demo": [],
}
