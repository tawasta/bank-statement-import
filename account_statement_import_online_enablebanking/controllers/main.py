import json
import logging

import requests
import werkzeug

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


class EnableBankingController(http.Controller):
    @http.route("/enablebanking_auth", type="http", auth="user")
    def enablebanking_auth(self, *args, **kwargs):
        auth_code = kwargs.get("code")
        enablebanking_state = kwargs.get("state")
        enablebanking = (
            request.env["enablebanking.application"]
            .sudo()
            .search([("enablebanking_state", "=", enablebanking_state)], limit=1)
        )

        if not enablebanking:
            raise ValidationError(
                request.env._(
                    "Could not find EnableBanking application for state: %s",
                    enablebanking_state,
                )
            )

        jwt = enablebanking._enablebanking_get_jwt_token()
        base_headers = {"Authorization": f"Bearer {jwt}"}
        _logger.debug(f"Using auth code: {auth_code}")

        r = requests.post(
            f"{enablebanking.api_origin}/sessions",
            json={"code": auth_code},
            headers=base_headers,
            timeout=10,
        )
        if r.status_code == 200:
            session = r.json()
            _logger.info(
                request.env._(
                    "New user session has been created: %s", session.get("session_id")
                )
            )
        else:
            raise ValidationError(
                request.env._(
                    "Error response %(status_code)s: %(response_text)s",
                    status_code=r.status_code,
                    response_text=r.text,
                )
            )

        enablebanking.session = json.dumps(session)

        action = request.env.ref("account.action_account_journal_form")
        base_url = request.env["ir.config_parameter"].sudo().get_param("web.base.url")

        # Redirect back to journals view
        redirect_url = f"{base_url}/odoo/action-{action.id}"

        return werkzeug.utils.redirect(redirect_url, 303)
