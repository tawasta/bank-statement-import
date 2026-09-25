from odoo import fields, models
from odoo.exceptions import ValidationError


class AccountJournal(models.Model):
    _inherit = "account.journal"

    enablebanking_warning = fields.Text(compute="_compute_enablebanking_warning")

    def _compute_enablebanking_warning(self):
        for record in self:
            provider = record.online_bank_statement_provider_id
            application = provider.enablebanking_application_id
            authenticated_accounts = application.authenticated_bank_accounts or ""

            if provider.service != "enablebanking":
                record.enablebanking_warning = False
                continue

            warning = provider._enablebanking_errors()

            if not warning:
                acc_number = record.bank_account_id.sanitized_acc_number
                if acc_number and acc_number not in authenticated_accounts:
                    warning += self.env._(
                        "This bank account is not authenticated with EnableBanking. "
                        "It will not be able to fetch bank statement information"
                    )

            record.enablebanking_warning = warning if warning else False

    def action_enablebanking_authenticate(self):
        # A shortcut for Enable Banking authentication
        self.ensure_one()
        if self.online_bank_statement_provider == "enablebanking":
            application = (
                self.online_bank_statement_provider_id.enablebanking_application_id
            )

            if not application:
                raise ValidationError(
                    self.env._(
                        "EnableBanking application not found. "
                        "Please check the configuration."
                    )
                )

            return application.action_enablebanking_authenticate()
        else:
            raise ValidationError(
                self.env._("This authentication only works for EnableBanking-provider")
            )
