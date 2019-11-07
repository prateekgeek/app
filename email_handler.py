"""
Handle the email *forward* and *reply*. phase There are 3 actors:
- website: who sends emails to alias@sl.co address
- SL email handler (this script)
- user personal email

This script makes sure that in the forward phase, the email that is forwarded to user personal email has the following
envelope and header fields:
Envelope:
    mail from: srs@sl.co # managed by SRS
    rcpt to: @real
Header:
    From: @website
    To: alias@sl.co
    Reply-to: special@sl.co # magic here

And in the reply phase:
Envelope:
    mail from: srs@sl.co # managed by SRS
    rcpt to: @website

Header:
    From: alias@sl.co # magic here
    To: @website

The special@sl.co allows to hide user personal email when user clicks "Reply" to the forwarded email.
It should contain the following info:
- alias
- @website


"""
import time
from email.parser import Parser
from email.policy import default
from smtplib import SMTP

from aiosmtpd.controller import Controller

from app.config import EMAIL_DOMAIN
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, ForwardEmail
from app.utils import random_words


def parse_srs_email(srs) -> str:
    """
    Parse srs0=8lgw=y6=outlook.com=abcd@mailsl.meo.ovh and return abcd@outlook.com
    """
    local_part = srs[: srs.find("@")]  # srs0=8lgw=y6=outlook.com=abcd
    local_email_part = local_part[local_part.rfind("=") + 1 :]  # abcd

    rest = local_part[: local_part.rfind("=")]  # srs0=8lgw=y6=outlook.com
    domain_email_part = rest[rest.rfind("=") + 1 :]  # outlook.com

    return f"{local_email_part}@{domain_email_part}"


class MailHandler:
    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        if not address.endswith(EMAIL_DOMAIN):
            LOG.error(f"Not handle email  {address}")
            return "550 not relaying to that domain"

        envelope.rcpt_tos.append(address)

        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        LOG.debug(">>> handle_DATA <<<")

        LOG.debug("Mail from %s", envelope.mail_from)
        LOG.debug("Rcpt to %s", envelope.rcpt_tos)
        LOG.debug("Message data:\n")
        message_data = envelope.content.decode("utf8", errors="replace")
        LOG.debug(message_data)
        LOG.debug("End of message")

        client = SMTP("localhost", 25)
        msg = Parser(policy=default).parsestr(message_data)

        if not envelope.rcpt_tos[0].startswith("reply+"):  # Forward case
            LOG.debug("Forward phase, add Reply-To header")
            alias = envelope.rcpt_tos[0]  # alias@SL

            gen_email = GenEmail.get_by(email=alias)
            website_email = parse_srs_email(envelope.mail_from)

            forward_email = ForwardEmail.get_by(
                gen_email_id=gen_email.id, website_email=website_email
            )
            if not forward_email:
                LOG.debug(
                    "create forward email for alias %s and website email %s",
                    alias,
                    website_email,
                )
                # todo: make sure reply_email is unique
                reply_email = f"reply+{random_words()}@{EMAIL_DOMAIN}"
                forward_email = ForwardEmail.create(
                    gen_email_id=gen_email.id,
                    website_email=website_email,
                    reply_email=reply_email,
                )
                db.session.commit()

            # add custom header
            msg.add_header("X-SimpleLogin-Type", "Forward")
            msg.add_header("Reply-To", forward_email.reply_email)

            client.send_message(
                msg,
                from_addr=envelope.mail_from,
                to_addrs=[gen_email.user.emai],  # user personal email
                mail_options=envelope.mail_options,
                rcpt_options=envelope.rcpt_options,
            )
        else:
            LOG.debug("Reply phase")
            # todo: parse alias from envelope.rcpt_tos, e.g. ['reply+abcd+nguyenkims+hotmail.com@mailsl.meo.ovh']
            alias = "abcd"

            # email seems to come from alias
            msg.replace_header("From", f"{alias}{DOMAIN}")
            msg.replace_header("To", FROM)

            client.send_message(
                msg,
                from_addr=f"{alias}{DOMAIN}",
                to_addrs=[FROM],
                mail_options=envelope.mail_options,
                rcpt_options=envelope.rcpt_options,
            )

        return "250 Message accepted for delivery"


controller = Controller(MailHandler(), hostname="localhost", port=20381)

controller.start()
print(">>", controller.hostname, controller.port)

while True:
    time.sleep(10)