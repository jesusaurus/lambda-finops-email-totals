import json
import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.DEBUG)

sagebase_email = '@sagebase.org'
sagebio_email = '@sagebionetworks.org'
synapse_email = '@synapse.org'

ses_client = boto3.client('ses')


def valid_recipient(email, team_sage):
    """
    Determine if a given recipient should receive an email
    """

    restrict = os.environ['RESTRICT']
    approved = os.environ['APPROVED'].split(',')
    skiplist = os.environ['SKIPLIST'].split(',')

    # Skip anyone who has opted out
    if email in skiplist:
        LOG.info(f"Skipping address: '{email}'")
        return False

    # If sending is restricted, check the approved list
    if restrict == 'True':
        if email in approved:
            return True
        LOG.info(f"Restricted, skipping address: '{email}'")
        return False

    # Check for internal domains
    if email.endswith(sagebase_email) or email.endswith(sagebio_email):
        return True

    # Check Synapse users against Team Sage
    if email.endswith(synapse_email):
        if email in team_sage:
            return True

        LOG.info(f"Skipping external synapse user: '{email}'")
        return False

    # Not all tag values are valid email addresses, and uncategorized
    # costs will be associated with an empty string value
    LOG.warning(f"Invalid email address: '{email}'")
    return False


def build_email_body(summary, account_names):
    """
    Generate an HTML and a plain-text message body for a summary entry
    """

    def _table_row_style(i):
        """
        Alternating table row background colors
        """
        if i % 2 == 0:
            return "style='background-color: WhiteSmoke;'"
        else:
            return ""

    def _build_usage_table(usage, html=False):
        """
        Build paragraph about directly-tagged resources

        Example usage block:
        ```
        111122223333:
            total: 10.0
        222233334444:
            total: 20.0
            change: 0.5
        ```
        """

        output = ''

        if html:
            output += ("<table border=1 style='border-collapse: collapse;'>"
                       "<tr style='background-color: LightSteelBlue'>"
                       "<th>Account Name</th><th>Account ID</th>"
                       "<th>Your Total</th><th>Month-over-Month</th></tr>")
            row_i = 0  # row index for coloring table rows
        else:
            output += '\t'.join(['Account Name', 'Account ID',
                                 'Total', 'Month-over-Month'])

        for account_id in usage:
            account_name = account_names[account_id]

            # Round total to 2 decimal places
            total = f"{usage[account_id]['total']:.2f}"

            change = ''
            if 'change' in usage[account_id]:
                # Convert to a percentage
                change = f"{usage[account_id]['change']:.2%}"

            if html:
                _td = (f"<td>{account_name}</td><td>{account_id}</td>"
                       f"<td>{total}</td><td>{change}</td>")

                _style = _table_row_style(row_i)
                output += f"<tr {_style}>{_td}</tr>"
                row_i += 1

            else:
                _td = [account_name, account_id, total, change]
                output = '\t'.join(_td) + '\n'

        if html:
            output += "</table>"

        return output

    def _build_accounts_usage(usage, html=False):
        """
        Build paragraph about owned accounts

        Example usage block:
        ```
        333344445555:
            total: 200.0
            change: -0.05
        444455556666:
            total: 1.0
        ```
        """

        output = ''

        descr = 'You are tagged as owning the following accounts:'
        table = _build_usage_table(usage, html)

        if html:
            output += f"<p>{descr}</p>{table}"
        else:
            output += f"{descr}\n{table}"

        return output

    def _build_resource_usage(usage, html=False):
        """
        Build paragraph about directly-tagged resources

        Example usage block:
        ```
        111122223333:
            total: 10.0
        222233334444:
            total: 20.0
            change: 0.5
        ```
        """

        output = ''

        descr = ('You are tagged as owning resources in the following '
                 'accounts: ')
        table = _build_usage_table(usage, html)

        if html:
            output += f"<p>{descr}</p>{table}"
        else:
            output += f"{descr}\n{table}"

        return output

    def _build_tags_table(missing, html=False):
        output = ''

        if html:
            output += ("<table border=1 padding=3 width=550px "
                       "style='border-collapse: collapse;'>"
                       "<tr style='background-color: LightSteelBlue'>"
                       "<th>Account Name</th><th>Account ID</th>"
                       "<th>Resources Missing Tag</th></tr>")
            row_i = 0  # row index for coloring table rows
        else:
            output += '\t'.join(['Account Name', 'Account ID',
                                 'Resources Missing Tags'])

        for account_id in missing:
            account_name = account_names[account_id]

            # Convert list to string
            untagged = json.dumps(missing[account_id])

            if html:
                _td = (f"<td>{account_name}</td><td>{account_id}</td>"
                       f"<td>{untagged}</td>")

                _style = _table_row_style(row_i)
                output += f"<tr {_style}>{_td}</tr>"
                row_i += 1

            else:
                _td = [account_name, account_id, untagged]
                output = '\t'.join(_td) + '\n'

        if html:
            output += "</table>"

        return output

    def _build_missing_tags(missing, html=False):
        """
        Build paragraph about resources missing CostCenterOther

        Example missing block:
        ```
        111122223333:
            - i-0abcdefg
        333344445555:
            - i-1hijklmnop
        ```
        """

        output = ''

        descr = ('Additionally, some of the above resources have a '
                 '"CostCenter" tag value of "Other / 000001" but do not have '
                 'a required "CostCenterOther" tag: ')
        table = _build_tags_table(missing, html)

        if html:
            output += f"<p>{descr}</p>{table}"
        else:
            output += f"{descr}\n{table}"

        return output

        return output

    title = 'AWS Monthly Cost Report Summary'
    intro = ('You are receiving this summary because you are tagged as '
             'the owner of AWS resources.')

    html_body = f"<div width=600px><h3>{title}</h3><br/><p>{intro}</p>"
    text_body = f"{title}\n\n{intro}\n"

    if 'resources' in summary:
        html_body += _build_resource_usage(summary['resources'], True)
        text_body += _build_resource_usage(summary['resources'], False)

    if 'accounts' in summary:
        html_body += _build_accounts_usage(summary['accounts'], True)
        text_body += _build_accounts_usage(summary['accounts'], False)

    if 'missing_other_tag' in summary:
        html_body += _build_missing_tags(summary['missing_other_tag'], True)
        text_body += _build_missing_tags(summary['missing_other_tag'], False)

    docs_prose = ('You can use AWS Cost Explorer to analyze these expenses by '
                  'filtering on the "Owner Email" category and/or account ID')
    docs_name = 'Using AWS Cost Explorer'
    docs_url = 'https://sagebionetworks.jira.com/wiki/spaces/IT/pages/2756935685/Using+AWS+Cost+Explorer'

    html_body += f"<p>{docs_prose}: <a href='{docs_url}'>{docs_name}</a></p></div>"
    text_body += f"\n{docs_prose}. See '{docs_name}' at: {docs_url}"

    LOG.debug(html_body)
    LOG.debug(text_body)

    return html_body, text_body


def send_report_email(recipient, body_html, body_text, period):
    """
    Send e-mail through SES
    """

    sender = os.environ['SENDER']
    subject = f"AWS Monthly Cost Report ({period})"

    # Python3 uses UTF-8
    charset = "UTF-8"

    # Try to send the email.
    try:
        response = ses_client.send_email(
            Destination={
                'ToAddresses': [
                    recipient,
                ],
            },
            Message={
                'Body': {
                    'Html': {
                        'Charset': charset,
                        'Data': body_html,
                    },
                    'Text': {
                        'Charset': charset,
                        'Data': body_text,
                    },
                },
                'Subject': {
                    'Charset': charset,
                    'Data': subject,
                },
            },
            Source=sender,
        )

        # We need to rate limit our calls to 'send_email', our current SES
        # quota allows for sending 14 emails per second, sleep for 72ms after
        # each call to send a maximum of 14 emails in 1008ms.
        time.sleep(0.072)

    # Display an error if something goes wrong.
    except ClientError as e:
        LOG.exception(e)
    else:
        LOG.info(f"Email sent! Message ID: {response['MessageId']}")
