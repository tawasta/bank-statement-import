import json
from datetime import datetime

from odoo import fields, models
from odoo.exceptions import ValidationError


class OnlineBankStatementPullWizard(models.TransientModel):
    _inherit = "online.bank.statement.pull.wizard"

    def action_pull(self):
        self.ensure_one()
        provider = self._get_provider()
        if provider.service == "enablebanking":
            # Check if authentication is still valid
            enablebanking = provider.enablebanking_application_id
            msg = self.env._(
                "You bank authentication is invalid. Please authenticate and try again"
            )
            if not enablebanking.session:
                raise ValidationError(msg)

            session_dict = json.loads(enablebanking.session)
            valid_until = session_dict.get("access", {}).get("valid_until")
            if valid_until:
                datetime_format = "%Y-%m-%dT%H:%M:%S"
                valid_datetime = datetime.strptime(valid_until[0:19], datetime_format)
                if valid_datetime < fields.Datetime.now():
                    raise ValidationError(msg)

        return super().action_pull()
