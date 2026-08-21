import base64
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import requests

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class EnablebankingApplication(models.Model):
    _name = "enablebanking.application"
    _description = "Application for Enablebanking authentication"
    _order = "application_id"
    _rec_name = "application_id"

    online_bank_statement_provider_ids = fields.One2many(
        comodel_name="online.bank.statement.provider",
        inverse_name="enablebanking_application_id",
        string="Bank statement providers",
    )
    application_id = fields.Char(
        string="Application ID",
        help="Application ID from your EnableBanking.com portal",
        required=True,
    )
    bank_id = fields.Many2one(
        comodel_name="res.bank",
        required=True,
    )
    redirect_url = fields.Char(
        string="Redirect URL", default=lambda self: self._default_redirect_url()
    )
    api_origin = fields.Char(
        string="API Origin", default="https://api.enablebanking.com", readonly=True
    )
    auth_code = fields.Char(string="Auth code", readonly=False, copy=False)
    jwt = fields.Char(string="Latest JWT", readonly=True)
    session = fields.Char(string="Latest session", readonly=True)
    valid_until = fields.Datetime(
        string="Valid until",
        help="Authentication valid until",
        readonly=True,
        compute="_compute_valid_until",
    )
    key = fields.Binary(
        string="Private key", help="Private key from your EnableBanking.com portal"
    )
    key_name = fields.Char()

    aspsp_name = fields.Char(string="ASPSP name")
    aspsp_country = fields.Many2one(string="ASPSP country", comodel_name="res.country")
    psu_type = fields.Selection(
        string="Account type",
        selection=[("business", "Business"), ("personal", "Personal")],
        default="personal",
    )
    enablebanking_state = fields.Char(
        help="Helper for identifying the correct provider"
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Responsible",
        help="The person to be notified about expired authentication or other problems",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )

    @api.onchange("user_id")
    def onchange_user_id(self):
        """
        When responsible user is changed, add them to follower
        """
        for record in self:
            if record.user_id:
                for provider in record.online_bank_statement_provider_ids:
                    provider.message_subscribe(
                        partner_ids=[record.user_id.partner_id.id]
                    )

    def _default_redirect_url(self):
        url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        url += "/enablebanking_auth"

        return url

    def _get_session_dict(self):
        """
        Get session as dict
        """
        self.ensure_one()
        if not self.session:
            return {}
        return json.loads(self.session)

    def _compute_valid_until(self):
        for record in self:
            session = record._get_session_dict()

            if session:
                _logger.debug(f"Session data: {session}")
                # Get valid until from session data
                valid_until = session.get("access", {}).get("valid_until")
                if valid_until:
                    # Replace Z with +00:00 and remove timezone info
                    valid_until = valid_until.replace("Z", "+00:00")
                    valid_until = datetime.fromisoformat(valid_until).replace(
                        tzinfo=None
                    )
                    record.valid_until = valid_until
                else:
                    record.valid_until = False
            else:
                record.valid_until = False

    # Enablebanking
    def action_enablebanking_authenticate(self):
        return self._enablebanking_authorize()

    def action_enablebanking_deauthorize(self):
        """
        Deauthorize the application by clearing the session and JWT.
        This will require re-authentication.
        """
        self.write({"session": {}, "jwt": False, "enablebanking_state": False})

    def action_enablebanking_get_aspsp(self):
        """
        Fetch ASPSP information using bank BIC in bank account
        """
        self.ensure_one()

        if not self.bank_id:
            raise ValidationError(self.env._("Please configure a bank account"))

        if not self.bank_id.bic:
            raise ValidationError(self.env._("Please add a BIC to your bank account"))

        bic = self.bank_id.bic

        jwt = self._enablebanking_get_jwt_token()
        base_headers = self._enablebanking_get_basic_headers(jwt)

        if not self.company_id.country_code:
            raise ValidationError(
                self.env._(
                    "Country code is missing! Please add a country for your company."
                )
            )

        body = {"psu_type": self.psu_type, "country": self.company_id.country_code}
        r = requests.get(
            f"{self.api_origin}/aspsps",
            params=body,
            headers=base_headers,
            timeout=10,
        ).json()

        _logger.debug(f"ASPSP response: {r}")

        aspsp_names = []

        for aspsp in r.get("aspsps", []):
            aspsp_name = aspsp.get("name")
            aspsp_names.append(aspsp_name)

            if aspsp.get("bic") and aspsp.get("bic") == bic:
                self.aspsp_name = aspsp_name
                self.aspsp_country = self.env["res.country"].search(
                    [("code", "=", aspsp.get("country"))]
                )

        if not self.aspsp_name:
            raise ValidationError(
                self.env._(
                    "Could not find ASPSP info. "
                    "Please check account type and your bank BIC. \n"
                    "Found ASPSPs: %(aspsp_names)s",
                    aspsp_names=", ".join(aspsp_names),
                )
            )

    def _enablebanking_get_basic_headers(self, jwt):
        base_headers = {"Authorization": f"Bearer {jwt}"}

        # Requesting application details
        # This doesn't really do anything but fetch and print the details
        r = requests.get(
            f"{self.api_origin}/application",
            headers=base_headers,
            timeout=10,
        )
        if r.status_code == 200:
            app = r.json()
            _logger.debug(f"Application details: {app}")
        else:
            raise ValidationError(
                self.env._(
                    "Error response %(status_code)s: %(response_text)s",
                    status_code=r.status_code,
                    response_text=r.text,
                )
            )

        if not app.get("active"):
            raise ValidationError(
                self.env._(
                    "This application is not yet activated. "
                    "Please do that before continuing"
                )
            )

        if self.redirect_url not in app.get("redirect_urls", []):
            raise ValidationError(
                self.env._(
                    "Redirect URL is not registered with your application. \n"
                    "Please add '%s' to allowed redirect URLs.",
                    self.redirect_url,
                )
            )

        return base_headers

    def _enablebanking_get_jwt_token(self):
        self.ensure_one()
        if not self.key:
            raise ValidationError(
                self.env._(
                    "Private key is missing! "
                    "Please add a private key for your application."
                )
            )

        iat = int(datetime.now().timestamp())

        # Generate JWT token
        jwt_body = {
            "iss": "enablebanking.com",
            "aud": "api.enablebanking.com",
            "iat": iat,
            "exp": iat + 3600,
        }
        jwt = pyjwt.encode(
            jwt_body,
            base64.b64decode(self.key).decode("utf-8"),
            algorithm="RS256",
            headers={"kid": self.application_id},
        )

        if not isinstance(jwt, str):
            jwt = jwt.decode("utf-8")

        _logger.debug(f"JWT: {jwt}")

        return jwt

    def _enablebanking_authorize(self):
        """
        Enable Banking: authorization
        """

        jwt = self._enablebanking_get_jwt_token()
        base_headers = self._enablebanking_get_basic_headers(jwt)
        enablebanking_state = str(uuid.uuid4())

        # Starting authorization
        validity = 90
        # TODO: fetch maximum validity from ASPSP information
        if self.aspsp_name in ["Nordea", "OP"]:
            validity = 180

        body = {
            "access": {
                # Maximum validity 90 days
                "valid_until": (
                    datetime.now(timezone.utc) + timedelta(days=validity)
                ).isoformat()
            },
            "aspsp": {"name": self.aspsp_name, "country": self.aspsp_country.code},
            "state": enablebanking_state,
            "redirect_url": self.redirect_url,
            "psu_type": self.psu_type,
        }
        r = requests.post(
            f"{self.api_origin}/auth",
            json=body,
            headers=base_headers,
            timeout=10,
        )
        if r.status_code == 200:
            # Save the jwt for controller
            self.sudo().jwt = jwt
            self.sudo().enablebanking_state = enablebanking_state
            auth_url = r.json()["url"]
            return {
                "type": "ir.actions.act_url",
                "url": auth_url,
                "target": "self",
            }
        else:
            raise ValidationError(
                self.env._(
                    "Error response %(status_code)s: %(response_text)s",
                    status_code=r.status_code,
                    response_text=r.text,
                )
            )

    def _enablebanking_get_account_ids(self):
        """
        Enablebanking: get available accounts
        """
        _logger.warning("Fetching accounts is not implemented")
        pass
