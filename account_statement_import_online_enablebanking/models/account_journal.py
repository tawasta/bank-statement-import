from odoo import models
from odoo.exceptions import ValidationError


class AccountJournal(models.Model):
    _inherit = "account.journal"

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
