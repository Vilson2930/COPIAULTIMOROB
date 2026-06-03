import os
import smtplib
from pathlib import Path
from email.message import EmailMessage

from report_engine import build_institutional_report


SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465


def get_required_secret(name):
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"Secret ausente: {name}")
    return value


def find_csv_files():
    allowed_files = [
        "outputs/executive_dashboard.csv",
        "outputs/risk_committee_integrated.csv",
        "outputs/orders_log_robo_macro.csv",
        "outputs/survival_audit.csv",
    ]

    files = []

    for file in allowed_files:
        path = Path(file)
        if path.exists() and path.is_file():
            files.append(path)

    return files


def send_email_report():
    email_user = get_required_secret("EMAIL_USER")
    email_password = get_required_secret("EMAIL_APP_PASSWORD")
    email_to = get_required_secret("EMAIL_TO")

    html_report = build_institutional_report()
    attachments = find_csv_files()

    msg = EmailMessage()
    msg["Subject"] = "ULTIMOROBO — Relatório Institucional Macro"
    msg["From"] = email_user
    msg["To"] = email_to

    msg.set_content(
        "Relatório institucional do ULTIMOROBO. "
        "Abra este email em modo HTML para visualizar o painel completo."
    )

    msg.add_alternative(html_report, subtype="html")

    for path in attachments:
        msg.add_attachment(
            path.read_bytes(),
            maintype="text",
            subtype="csv",
            filename=path.name,
        )

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.login(email_user, email_password)
        smtp.send_message(msg)

    print("====================================================")
    print("ULTIMOROBO — EMAIL ENVIADO")
    print("====================================================")
    print(f"Destino: {email_to}")
    print(f"Anexos enviados: {len(attachments)}")
    for path in attachments:
        print(f"- {path}")
    print("====================================================")


if __name__ == "__main__":
    send_email_report()
