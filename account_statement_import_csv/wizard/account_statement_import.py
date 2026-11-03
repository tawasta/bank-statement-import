import logging

from odoo import fields, models
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)


class AccountStatementImport(models.TransientModel):
    _inherit = "account.statement.import"

    is_csv = fields.Boolean(string="Is a CSV", default=False)

    def _parse_file(self, data_file):
        if not self.is_csv:
            return super()._parse_file(data_file)

        rows = data_file.splitlines()

        sequence = 0
        transactions = []

        for row in rows:
            # TODO: Smarter CSV parsing, handle quoted fields with semicolons inside
            cols = row.decode("utf-8").split(";")

            if len(cols) != 4:
                raise ValidationError(
                    self.env._(
                        "CSV file does not have exactly 4 columns."
                        "Please use a CSV file with columns for "
                        "Payer, Amount, Date, and Reference."
                    )
                )

            if sequence == 0:
                # Skip the header
                sequence += 1
                continue

            # The first value should be "Payer"
            partner_name = cols[0]
            amount = cols[1]
            value_date = cols[2]
            ref = cols[3]

            # Remove non-numeric characters from amount
            amount = amount.replace(",", "")
            amount = "".join(
                c for c in amount if c.isdigit() or c == "." or c == "-"
            ).strip()

            # Format date to iso format (YYYY-MM-DD)
            value_date = value_date.strip()
            if "/" in value_date:
                month, day, year = value_date.split("/")

                # Full year instance, if year is in two digits, prepend '20'
                if len(year) == 2:
                    year = "20" + year

                value_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"

            # Strip any leading/trailing whitespace from partner name and reference
            partner_name = partner_name.strip()
            ref = ref.strip()

            # Strip leading zeroes from ref
            ref = ref.lstrip("0")

            vals = {
                "sequence": sequence,
                "date": value_date,
                "payment_ref": ref,
                "ref": ref,
                "amount": float(amount),
                "account_number": "",
                "partner_name": partner_name,
                "narration": "",
            }

            partner_id = self.env["res.partner"].search(
                [("name", "=ilike", partner_name)], limit=1
            )
            if partner_id:
                vals["partner_id"] = partner_id.id

            transactions.append(vals)
            sequence += 1

        account_number = ""
        # TODO: support other currencies
        currency = "EUR"
        return currency, account_number, [{"transactions": transactions}]
