# Copyright (C) 2007 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""A convenience class around smtplib."""

from email import Utils
import errno
import smtplib
import socket

from bzrlib import (
    config,
    ui,
    )
from bzrlib.errors import (
    NoDestinationAddress,
    SMTPError,
    DefaultSMTPConnectionRefused,
    SMTPConnectionRefused,
    )


class SMTPConnection(object):
    """Connect to an SMTP server and send an email.

    This is a gateway between bzrlib.config.Config and smtplib.SMTP. It
    understands the basic bzr SMTP configuration information: smtp_server,
    smtp_username, and smtp_password.
    """

    _default_smtp_server = 'localhost'

    def __init__(self, config, _smtp_factory=None):
        self._smtp_factory = _smtp_factory
        if self._smtp_factory is None:
            self._smtp_factory = smtplib.SMTP
        self._config = config
        self._config_smtp_server = config.get_user_option('smtp_server')
        self._smtp_server = self._config_smtp_server
        if self._smtp_server is None:
            self._smtp_server = self._default_smtp_server

        self._smtp_username = config.get_user_option('smtp_username')
        self._smtp_password = config.get_user_option('smtp_password')

        self._connection = None

    def _connect(self):
        """If we haven't connected, connect and authenticate."""
        if self._connection is not None:
            return

        self._create_connection()
        self._authenticate()

    def _create_connection(self):
        """Create an SMTP connection."""
        self._connection = self._smtp_factory()
        try:
            self._connection.connect(self._smtp_server)
        except socket.error, e:
            if e.args[0] == errno.ECONNREFUSED:
                if self._config_smtp_server is None:
                    raise DefaultSMTPConnectionRefused(socket.error,
                                                       self._smtp_server)
                else:
                    raise SMTPConnectionRefused(socket.error,
                                                self._smtp_server)
            else:
                raise

        # Say EHLO (falling back to HELO) to query the server's features.
        code, resp = self._connection.ehlo()
        if not (200 <= code <= 299):
            code, resp = self._connection.helo()
            if not (200 <= code <= 299):
                raise SMTPError("server refused HELO: %d %s" % (code, resp))

        # Use TLS if the server advertised it:
        if self._connection.has_extn("starttls"):
            code, resp = self._connection.starttls()
            if not (200 <= code <= 299):
                raise SMTPError("server refused STARTTLS: %d %s" % (code, resp))
            # Say EHLO again, to check for newly revealed features
            code, resp = self._connection.ehlo()
            if not (200 <= code <= 299):
                raise SMTPError("server refused EHLO: %d %s" % (code, resp))

    def _authenticate(self):
        """If necessary authenticate yourself to the server."""
        auth = config.AuthenticationConfig()
        if self._smtp_username is None:
            self._smtp_username = auth.get_user('smtp', self._smtp_server)
            if self._smtp_username is None:
                return

        if self._smtp_password is None:
            self._smtp_password = auth.get_password(
                'smtp', self._smtp_server, self._smtp_username)

        self._connection.login(self._smtp_username, self._smtp_password)

    @staticmethod
    def get_message_addresses(message):
        """Get the origin and destination addresses of a message.

        :param message: A message object supporting get() to access its
            headers, like email.Message or bzrlib.email_message.EmailMessage.
        :return: A pair (from_email, to_emails), where from_email is the email
            address in the From header, and to_emails a list of all the
            addresses in the To, Cc, and Bcc headers.
        """
        from_email = Utils.parseaddr(message.get('From', None))[1]
        to_full_addresses = []
        for header in ['To', 'Cc', 'Bcc']:
            value = message.get(header, None)
            if value:
                to_full_addresses.append(value)
        to_emails = [ pair[1] for pair in
                Utils.getaddresses(to_full_addresses) ]

        return from_email, to_emails

    def send_email(self, message):
        """Send an email message.

        The message will be sent to all addresses in the To, Cc and Bcc
        headers.

        :param message: An email.Message or email.MIMEMultipart object.
        :return: None
        """
        from_email, to_emails = self.get_message_addresses(message)

        if not to_emails:
            raise NoDestinationAddress

        try:
            self._connect()
            self._connection.sendmail(from_email, to_emails,
                                      message.as_string())
        except smtplib.SMTPRecipientsRefused, e:
            raise SMTPError('server refused recipient: %d %s' %
                    e.recipients.values()[0])
        except smtplib.SMTPResponseException, e:
            raise SMTPError('%d %s' % (e.smtp_code, e.smtp_error))
        except smtplib.SMTPException, e:
            raise SMTPError(str(e))
