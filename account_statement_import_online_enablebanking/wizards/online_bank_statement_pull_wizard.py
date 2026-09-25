from odoo import models
from odoo.exceptions import ValidationError


class OnlineBankStatementPullWizard(models.TransientModel):
    _inherit = "online.bank.statement.pull.wizard"

    def action_pull(self):
        self.ensure_one()
        provider = self._get_provider()
        if provider.service == "enablebanking":
            # Check for errors
            errors = provider._enablebanking_errors()
            if errors:
                raise ValidationError(errors)

        return super().action_pull()
