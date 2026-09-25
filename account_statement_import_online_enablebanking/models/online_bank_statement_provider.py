import logging
from datetime import datetime

import requests

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class OnlineBankStatementProviderEnablebanking(models.Model):
    _inherit = "online.bank.statement.provider"

    enablebanking_application_id = fields.Many2one(
        comodel_name="enablebanking.application", string="EnableBanking application"
    )
    enablebanking_valid_until = fields.Datetime(
        related="enablebanking_application_id.valid_until",
    )
    bank_id = fields.Many2one(comodel_name="res.bank", related="journal_id.bank_id")

    application_id = fields.Char(
        related="enablebanking_application_id.application_id", readonly=True
    )
    redirect_url = fields.Char(
        related="enablebanking_application_id.redirect_url", readonly=True
    )

    aspsp_name = fields.Char(
        related="enablebanking_application_id.aspsp_name", readonly=True
    )
    aspsp_country = fields.Many2one(
        related="enablebanking_application_id.aspsp_country", readonly=True
    )
    psu_type = fields.Selection(
        related="enablebanking_application_id.psu_type", readonly=True
    )

    enablebanking_user_id = fields.Many2one(
        related="enablebanking_application_id.user_id", readonly=True
    )

    @api.onchange("enablebanking_application_id")
    def onchange_enablebanking_application_id(self):
        """
        When EnableBanking application is changed, update related fields
        """
        for record in self:
            application = record.enablebanking_application_id
            if application:
                record.message_subscribe(
                    partner_ids=[application.user_id.partner_id.id]
                )

    @api.model
    def _get_available_services(self):
        return super()._get_available_services() + [
            ("enablebanking", "EnableBanking"),
        ]

    def _enablebanking_errors(self) -> str:
        """
        Check for any errors related to the EnableBanking application
        """
        self.ensure_one()
        if not self.service or self.service != "enablebanking":
            return ""

        errors = []
        application = self.enablebanking_application_id
        valid_until = application.valid_until

        if not application:
            errors.append(
                self.env._(
                    "EnableBanking application is not configured for this provider. "
                    "Please configure it."
                )
            )
        elif not application._get_session_dict():
            # The session is missing
            errors.append(
                self.env._("Your bank authentication is invalid. Please authenticate.")
            )
        elif not valid_until or valid_until < fields.Datetime.now():
            errors.append(
                self.env._(
                    "Bank authentication is invalid or expired.Please re-authenticate."
                )
            )

        return " \n".join(errors)

    def _obtain_statement_data(self, date_since, date_until):
        self.ensure_one()
        if self.service != "enablebanking":
            return super()._obtain_statement_data(date_since, date_until)
        return self._enablebanking_obtain_statement_data(date_since, date_until)

    def _enablebanking_obtain_statement_data(self, date_since, date_until):
        """
        EnableBanking: get bank statement data
        """
        self.ensure_one()
        enablebanking = self.enablebanking_application_id

        session = enablebanking._get_session_dict()
        # Using the first available account for the following API calls
        if not session.get("accounts"):
            raise ValidationError(
                self.env._(
                    "Did not find any accounts. "
                    "Please check linked accounts in Enable Banking management "
                    "and re-authenticate"
                )
            )

        _logger.debug(f"Accounts in session: {session['accounts']}")
        # TODO: search for the correct account
        accounts = {}
        for account in session["accounts"]:
            accounts[account.get("account_id").get("iban")] = account.get("uid")

        account_uid = accounts.get(self.account_number)

        _logger.info(f"Using account {self.account_number}")
        if not account_uid:
            raise ValidationError(
                self.env._(
                    "Account %(account_number)s not found.",
                    account_number=self.account_number,
                )
            )

        if date_until > datetime.now():
            # API won't allow using a future date here
            date_until = datetime.now()

        date_from = date_since.date().isoformat()
        date_to = date_until.date().isoformat()
        query = {
            "date_from": date_from,
            "date_to": date_to,
        }
        _logger.info(_logger.info(f"Fetching transactions for {date_from}-{date_to}"))

        jwt = enablebanking._enablebanking_get_jwt_token()
        base_headers = {"Authorization": f"Bearer {jwt}"}

        transactions = []
        sequence = 0
        continuation_key = None
        while True:
            if continuation_key:
                query["continuation_key"] = continuation_key
            r = requests.get(
                f"{enablebanking.api_origin}/accounts/{account_uid}/transactions",
                params=query,
                headers=base_headers,
                timeout=30,
            )
            if r.status_code == 200:
                resp_data = r.json()
                raw_transactions = resp_data["transactions"]
                _logger.info(f"Found {len(raw_transactions)} transactions")
                for transaction in raw_transactions:
                    sequence += 1
                    transaction_vals = self._get_transaction_vals(transaction, sequence)

                    transactions.append(transaction_vals)

                continuation_key = resp_data.get("continuation_key")
                if not continuation_key:
                    _logger.info(
                        f"No continuation key. "
                        f"All transactions were fetched for {self.account_number}"
                    )
                    break
                _logger.info(
                    f"Fetching more transactions with continuation key "
                    f"{continuation_key}"
                )
            elif r.status_code == 401:
                # Unauthorized (not authorized, expired, etc).
                _logger.info(f"Error response {r.status_code}: {r.text}")
                self.post_message(
                    body=self.env._(
                        "Bank authentication is invalid. "
                        "Please re-authenticate to fetch bank statements."
                    )
                )
            else:
                raise ValidationError(
                    self.env._(
                        "Error response %(status_code)s: %(response_text)s",
                        status_code=r.status_code,
                        response_text=r.text,
                    )
                )

        return transactions, {}

    def _get_transaction_vals(self, transaction, sequence):
        """
        Map EnableBanking transaction data to Odoo bank statement line values.
        """
        transaction_type = transaction.get("credit_debit_indicator")
        if transaction_type == "DBIT":
            multiplier = -1
        else:
            multiplier = 1

        value_date = transaction.get("value_date")
        booking_date = transaction.get("booking_date")

        if not value_date or value_date < booking_date:
            # Some banks don't seem to return a value date at all
            # If value date is missing, we use booking date as value date.

            # As value date may be some banking dates before booking date,
            # we may also encounter a situation
            # where we receive a transaction some days after the value date.
            # This can be even 3-4 days on weekends.
            # If a bank statement for that date is already handled in Odoo,
            # the transaction is silently dropped.
            # To avoid this, we set booking date as value date.
            # The value date in Odoo will be wrong and might cause
            # a slight miscalculation in overdue interest fee
            value_date = booking_date

        partner_name = transaction.get("creditor") and transaction.get("creditor").get(
            "name"
        )

        ref = transaction.get("reference_number") and transaction.get(
            "reference_number"
        ).lstrip("0")
        payment_ref = " ".join(transaction.get("remittance_information")) or ref

        vals = {
            "sequence": sequence,
            "date": value_date,
            "payment_ref": payment_ref,
            "ref": ref,
            "unique_import_id": transaction.get("entry_reference"),
            "amount": float(transaction.get("transaction_amount").get("amount"))
            * multiplier,  # TODO: currency
            "account_number": transaction.get("creditor_account")
            and transaction.get("creditor_account").get("name"),
            "partner_name": partner_name,
            "narration": partner_name,
        }

        if not vals.get("payment_ref"):
            vals["payment_ref"] = "-"

        # Try to find partner with exact name match
        if partner_name != "" and partner_name is not None:
            partner_id = (
                self.env["res.partner"]
                .sudo()
                .search([("name", "=ilike", partner_name)], limit=1)
            )
            if partner_id:
                vals["partner_id"] = partner_id.id

        if not vals["payment_ref"]:
            vals["payment_ref"] = vals["ref"]

        return vals
